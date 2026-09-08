"""ANONYMIZED REAL RFP PILOT workflow (``bidfusion-rfp-api-pilot``).

Controlled end-to-end pilot over one operator-supplied local RFP path:

    security scan -> parse -> extract requirements -> deterministic
    normalization -> bounded Orange Proxy normalization -> validation ->
    golden matching for BOTH paths -> local comparison artifacts ->
    metadata-only summary

Hard gates, all fail-closed:

- the operator must pass the explicit acknowledgement flag asserting the
  RFP is anonymized and authorized for the Orange LLM pilot (never an
  automated claim);
- ``BIDFUSION_LLM_ENABLED=true`` (plus a present API key) is required —
  the safe default stays OFF and nothing is processed without it;
- at most ``--max-requirements`` (default 20, hard cap 50) requirements
  are sent externally, one bounded requirement per call, no retry storm
  beyond the gateway's existing bounded retries;
- a pre-send identifier warning blocks that requirement unless the
  operator explicitly passes the labeled override flag.

The RFP file stays where the operator keeps it (read-only ingestion into
a staging copy); it is never committed, and the pilot artifacts go to
the private, gitignored pilot store. RFP text is never printed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from json import loads
from pathlib import Path

from bidfusion.bid_intelligence.matching.adapter import adapt_requirement, requirement_text
from bidfusion.bid_intelligence.matching.claims_access import load_claims_snapshot
from bidfusion.bid_intelligence.matching.contracts import KnowledgeStoreState
from bidfusion.golden_dataset.store import GoldenKnowledgeStore
from bidfusion.llm_gateway.errors import LlmGatewayError
from bidfusion.llm_gateway.orange_proxy import OrangeProxyAdapter
from bidfusion.llm_gateway.port import LlmClient
from bidfusion.llm_gateway.secrets import EnvironmentSecretResolver
from bidfusion.llm_gateway.settings import load_orange_proxy_settings
from bidfusion.orchestration import run_package, verify_run_integrity
from bidfusion.rfp_api_pilot.comparison import compare_normalizations
from bidfusion.rfp_api_pilot.golden_paths import GoldenMatchComparison, compare_golden_matches
from bidfusion.rfp_api_pilot.metrics import PilotRunMetrics, format_summary
from bidfusion.rfp_api_pilot.service import (
    LlmNormalizationValidationStatus,
    normalize_requirement_with_llm,
)
from bidfusion.rfp_api_pilot.store import (
    PilotRequirementRecord,
    PilotRunSummaryRecord,
    RfpApiPilotStore,
)
from bidfusion.schemas.extraction import RequirementExtractionResult
from bidfusion.security.gate_policy import PackageGateDecision

ACKNOWLEDGEMENT_FLAG = "--operator-confirms-anonymized-and-authorized"
ACKNOWLEDGEMENT_TEXT = (
    "Operator confirms this RFP has been anonymized and is authorized for the Orange LLM pilot."
)
PRESEND_OVERRIDE_FLAG = "--override-presend-warnings"

DEFAULT_MAX_REQUIREMENTS = 20
HARD_MAX_REQUIREMENTS = 50

_REQUIREMENTS_AUDIT = "extraction/requirement-extraction.audit.json"

_EXTERNALLY_ATTEMPTED = frozenset(
    {
        LlmNormalizationValidationStatus.VALIDATED,
        LlmNormalizationValidationStatus.GATEWAY_FAILED,
        LlmNormalizationValidationStatus.REQUIREMENT_ID_MISMATCH,
    }
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bidfusion-rfp-api-pilot",
        description=(
            "ANONYMIZED REAL RFP PILOT: bounded Orange Proxy requirement "
            "normalization as a challenger to the deterministic normalizer. "
            "MACHINE NORMALIZATION — HUMAN EVALUATION REQUIRED — NOT A "
            "COMPLIANCE DECISION."
        ),
        # The operator acknowledgement must be typed in full; argparse prefix
        # abbreviation would let "--operator-confirms" count as the explicit
        # anonymization/authorization assertion.
        allow_abbrev=False,
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Local anonymized RFP file or package directory (read-only, never committed).",
    )
    parser.add_argument("--bid-id", required=True, help="Bid identifier (BID-YYYY-NNNNNN).")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Pipeline output root outside any repository checkout (default: a temp dir).",
    )
    parser.add_argument(
        "--pilot-store-root",
        type=Path,
        default=None,
        help="Pilot artifact store root (default: runtime/rfp_api_pilot of this checkout).",
    )
    parser.add_argument(
        "--golden-store-root",
        type=Path,
        default=None,
        help="Golden knowledge store root (default: runtime/golden_dataset of this checkout).",
    )
    parser.add_argument(
        "--max-requirements",
        type=int,
        default=DEFAULT_MAX_REQUIREMENTS,
        help=(
            "Upper bound of requirements sent to the Orange Proxy in this run "
            f"(default {DEFAULT_MAX_REQUIREMENTS}, hard cap {HARD_MAX_REQUIREMENTS})."
        ),
    )
    parser.add_argument(
        ACKNOWLEDGEMENT_FLAG,
        action="store_true",
        dest="operator_acknowledged",
        help=ACKNOWLEDGEMENT_TEXT,
    )
    parser.add_argument(
        PRESEND_OVERRIDE_FLAG,
        action="store_true",
        dest="presend_override",
        help=(
            "Send requirements despite pre-send identifier warnings (explicit "
            "operator override of the labeled pilot policy; warnings stay recorded)."
        ),
    )
    return parser


def _load_requirements(run_directory: Path) -> RequirementExtractionResult:
    """Requirement extraction result after the run's own integrity re-check."""
    if verify_run_integrity(run_directory):
        msg = "the pipeline run failed its integrity re-check; refusing to continue"
        raise RuntimeError(msg)
    payload = loads((run_directory / _REQUIREMENTS_AUDIT).read_text(encoding="utf-8"))
    return RequirementExtractionResult.model_validate(payload)


def _stage_input(input_path: Path) -> Path:
    """Package directory for the pipeline; single files get a staging copy."""
    if input_path.is_dir():
        return input_path
    staging = Path(tempfile.mkdtemp(prefix="bidfusion-rfp-pilot-input-"))
    shutil.copyfile(input_path, staging / input_path.name)
    return staging


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    llm_client: LlmClient | None = None,
    now: datetime | None = None,
) -> int:
    """Run the pilot workflow; return a process exit code."""
    arguments = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ

    if not arguments.operator_acknowledged:
        print(
            "RFP API pilot refused: the explicit operator acknowledgement is "
            f"required. Pass {ACKNOWLEDGEMENT_FLAG} to assert: {ACKNOWLEDGEMENT_TEXT}",
            file=sys.stderr,
        )
        return 1

    try:
        settings = load_orange_proxy_settings(env)
    except LlmGatewayError as failure:
        print(f"RFP API pilot refused: {failure.code.value}", file=sys.stderr)
        return 1
    if not settings.enabled:
        print(
            "RFP API pilot refused: the Orange LLM Proxy Gateway is disabled. "
            "Explicit enablement (BIDFUSION_LLM_ENABLED=true and a configured "
            "API key) is required for the external pilot.",
            file=sys.stderr,
        )
        return 1

    if not 1 <= arguments.max_requirements <= HARD_MAX_REQUIREMENTS:
        print(
            f"RFP API pilot refused: --max-requirements must be between 1 and "
            f"{HARD_MAX_REQUIREMENTS}.",
            file=sys.stderr,
        )
        return 1
    if not arguments.input.exists():
        print("RFP API pilot refused: the input path does not exist.", file=sys.stderr)
        return 1

    moment = datetime.now(UTC) if now is None else now
    output_root = (
        Path(tempfile.mkdtemp(prefix="bidfusion-rfp-pilot-run-"))
        if arguments.output is None
        else arguments.output
    )

    try:
        summary = run_package(
            input_dir=_stage_input(arguments.input),
            output_dir=output_root,
            bid_id=arguments.bid_id,
            process=True,
            authorized_non_production_test=True,
            now=moment,
        )
    except ValueError as failure:
        print(f"RFP API pilot refused: {failure}", file=sys.stderr)
        return 1

    # The security gate must have CLEARED the package; a quality-gate
    # "review-required" outcome is acceptable for the pilot (extraction is
    # sealed, and the whole pilot is review-first anyway), but a gate hold,
    # block, or pipeline failure never reaches the LLM.
    gate_cleared = summary.gate.decision is PackageGateDecision.CLEARED
    if summary.outcome not in {"completed", "review-required"} or not gate_cleared:
        print(
            f"RFP API pilot aborted before any LLM call: pipeline outcome "
            f"'{summary.outcome}', package gate '{summary.gate.decision.value}' "
            f"(run {summary.run_id}). Nothing was sent externally.",
            file=sys.stderr,
        )
        return 2

    try:
        extraction = _load_requirements(summary.run_directory)
    except RuntimeError as failure:
        print(f"RFP API pilot aborted: {failure}", file=sys.stderr)
        return 2

    requirements = extraction.requirements
    selected = requirements[: arguments.max_requirements]

    golden_root = (
        GoldenKnowledgeStore.default_root()
        if arguments.golden_store_root is None
        else arguments.golden_store_root
    )
    snapshot = load_claims_snapshot(golden_root)

    client: LlmClient = (
        OrangeProxyAdapter(settings=settings, secret_resolver=EnvironmentSecretResolver(env))
        if llm_client is None
        else llm_client
    )
    store = RfpApiPilotStore(
        RfpApiPilotStore.default_root()
        if arguments.pilot_store_root is None
        else arguments.pilot_store_root
    )

    attempted = valid = blocked = 0
    agreements = []
    golden_agree = 0
    for requirement in selected:
        adapted = adapt_requirement(requirement)
        wrapped = normalize_requirement_with_llm(
            requirement,
            client=client,
            now=moment,
            presend_override=arguments.presend_override,
        )
        if wrapped.validation_status in _EXTERNALLY_ATTEMPTED:
            attempted += 1
        if wrapped.validation_status is LlmNormalizationValidationStatus.VALIDATED:
            valid += 1
        if wrapped.validation_status is (LlmNormalizationValidationStatus.BLOCKED_BY_PRESEND_CHECK):
            blocked += 1

        comparison = compare_normalizations(adapted, wrapped)
        agreements.append(comparison.agreement)
        golden_comparison: GoldenMatchComparison | None = None
        if snapshot.state is KnowledgeStoreState.AVAILABLE:
            golden_comparison = compare_golden_matches(adapted, wrapped, snapshot.claims)
            if golden_comparison.match_agreement:
                golden_agree += 1

        store.write_requirement_record(
            PilotRequirementRecord(
                bid_id=requirement.bid_id,
                run_id=summary.run_id,
                requirement_id=requirement.requirement_id,
                requirement_text=requirement_text(requirement)[:16000],
                llm=wrapped,
                normalization_comparison=comparison,
                golden_comparison=golden_comparison,
            )
        )

    agree_count = sum(1 for agreement in agreements if agreement.value == "AGREE")
    metrics = PilotRunMetrics.from_counts(
        requirements_total=len(requirements),
        llm_valid=valid,
        llm_failed=attempted - valid,
        agreements=tuple(agreements),
        golden_match_agree=golden_agree,
        human_evaluation_pending=len(selected) - agree_count,
    )
    store.write_summary(
        PilotRunSummaryRecord(
            bid_id=arguments.bid_id,
            run_id=summary.run_id,
            created_at=moment,
            metrics=metrics,
        )
    )

    print(format_summary(metrics))
    print(f"Run: {summary.run_id}")
    print(f"Blocked by pre-send identifier check: {blocked}")
    if len(selected) < len(requirements):
        print(
            f"Run bound applied: {len(requirements) - len(selected)} requirement(s) "
            "were not sent (raise --max-requirements deliberately if needed)."
        )
    print(f"Golden knowledge: {snapshot.note}")
    print(f"Pilot artifacts: {store.root}")
    return 0


def cli() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
