"""Local walking-skeleton pipeline: package directory to working package.

Security before intelligence, on package level: the versioned MVP gate
policy decides per document against the exact registered document/artifact
set, and downstream document understanding starts only when the whole
package is cleared *and* the operator explicitly opted in with
``--process``.

After parsing, extraction, and normalization the versioned MVP quality
gate (``bidfusion-mvp-quality-gate``) separates technical execution from
business usability: only an ``ACCEPTABLE`` run produces the working
package; ``REVIEW_REQUIRED`` produces a clearly marked, incomplete review
package instead; ``FAILED`` produces neither.

Real-sample lock: full processing is allowed for ``fixtures/synthetic/``
inputs only, unless the operator passes
``--authorized-non-production-test`` — an explicit statement that this is
an authorized, non-production test. The flag never bypasses the security
or quality gates and never unlocks the repository ``inbox``/``results``
harness directories. Outputs must always live outside any repository
checkout. All outputs are written confidential-by-default (0700/0600,
atomic) via :mod:`bidfusion.shared.secure_io`.

Persistence follows the hash convention in :mod:`bidfusion.shared.payloads`:
for every sealed artifact the canonical payload file at
``ArtifactEnvelope.content_ref`` is the authoritative representation, a
full ``*.audit.json`` file is a derived convenience view only, and
``integrity-manifest.json`` records whole-file digests of everything the
run wrote.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePosixPath

from bidfusion.document_understanding.canonical import (
    CANONICAL_DOMAIN,
    DocumentParser,
    ParserError,
    UnsupportedDocumentError,
    build_canonical_document,
    operator_safe_parser_message,
    sanitize_error_code,
)
from bidfusion.document_understanding.parsers import parser_for
from bidfusion.extraction.deadlines.rule_based import extract_deadlines
from bidfusion.extraction.formalities.rule_based import extract_formalities
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.extraction.support import extraction_domain
from bidfusion.intake import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    RegisteredDocument,
    RejectedFile,
    register_package,
)
from bidfusion.normalization import merge_extractions
from bidfusion.normalization.merge import NORMALIZED_DOMAIN
from bidfusion.quality import (
    QUALITY_GATE_ID,
    ParsedDocumentQuality,
    QualityGateReport,
    QualityGateStatus,
    UnprocessedDocument,
    build_review_package,
    evaluate_quality,
    render_review_markdown,
)
from bidfusion.schemas import (
    CanonicalDocument,
    DeadlineExtractionResult,
    DocumentInventoryEntry,
    ExtractionStream,
    FormalityExtractionResult,
    ProcessingRun,
    ProcessingStage,
    ProcessingStatus,
    RequirementExtractionResult,
    SecurityResult,
)
from bidfusion.schemas.artifact import ArtifactReference
from bidfusion.security import (
    DeterministicPreflightScanner,
    PackageGateDecision,
    PackageGateResult,
    PreflightConfig,
    decide_document,
    decide_package,
)
from bidfusion.shared.identifiers import ArtifactIdAllocator, run_id_for, validate_bid_id
from bidfusion.shared.pathguards import (
    is_inside_repository_checkout,
    is_repository_harness_path,
    is_trusted_synthetic_input,
)
from bidfusion.shared.payloads import (
    HASH_CONVENTION,
    EnvelopedArtifact,
    artifact_payload_bytes,
)
from bidfusion.shared.secure_io import ensure_private_directory, write_private_bytes
from bidfusion.working_package import build_working_package, render_markdown
from bidfusion.working_package.builder import WORKING_PACKAGE_DOMAIN

PIPELINE_NAME = "bidfusion-local-pipeline"
PIPELINE_VERSION = "0.3.0"

MANIFEST_FILENAME = "integrity-manifest.json"

_EXTRACTORS: tuple[tuple[ExtractionStream, str], ...] = (
    (ExtractionStream.REQUIREMENT, "requirement"),
    (ExtractionStream.DEADLINE, "deadline"),
    (ExtractionStream.FORMALITY, "formality"),
)
_STAGE_NAMES = (
    "intake",
    "preflight",
    "package_gate",
    "parsing",
    "extraction",
    "normalization",
    "quality_gate",
    "working_package",
)


class StageOutcome(StrEnum):
    """Explicit business-level result of one pipeline stage.

    ``attempted``/``succeeded`` keep reporting *technical execution*;
    the outcome reports the stage's gate-level result separately, so a
    review condition is never conflated with a technical failure.
    """

    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    SUCCEEDED = "SUCCEEDED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"


StageReport = dict[str, object]


def _initial_stages() -> dict[str, StageReport]:
    return {
        name: {
            "attempted": False,
            "succeeded": False,
            "outcome": StageOutcome.NOT_ATTEMPTED.value,
        }
        for name in _STAGE_NAMES
    }


@dataclass(frozen=True, slots=True)
class DocumentRunState:
    """Per-document outcome of one local pipeline run.

    ``parse_detail`` is always a static operator-safe message; the stable
    machine-readable identifier is ``parse_error_code``. Raw exception
    texts are never stored here.
    """

    document_id: str
    filename: str
    verdict: str | None
    assessment_error: str | None = None
    parse_status: str | None = None
    parse_detail: str | None = None
    parse_error_code: str | None = None
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "verdict": self.verdict,
            "assessment_error": self.assessment_error,
            "parse_status": self.parse_status,
            "parse_detail": self.parse_detail,
            "parse_error_code": self.parse_error_code,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class PipelineRunSummary:
    """Outcome of one local pipeline run."""

    run_id: str
    bid_id: str
    package_name: str
    outcome: str
    processed: bool
    gate: PackageGateResult
    documents: tuple[DocumentRunState, ...]
    run_directory: Path
    outputs: dict[str, str] = field(default_factory=dict)
    failed_streams: tuple[ExtractionStream, ...] = ()
    rejected: tuple[RejectedFile, ...] = ()
    stages: dict[str, StageReport] = field(default_factory=dict)
    quality: QualityGateReport | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def exit_code(self) -> int:
        """0 for a fully clean run at the executed depth, 2 otherwise."""
        return 0 if self.outcome in {"completed", "security-only"} else 2


class _RunWriter:
    """Write confidential run files below one run directory with digests."""

    def __init__(self, run_directory: Path) -> None:
        self._run_directory = run_directory
        self._digests: dict[str, str] = {}

    def write_bytes(self, relative: str, data: bytes) -> None:
        write_private_bytes(self._run_directory / relative, data, root=self._run_directory)
        self._digests[relative] = sha256(data).hexdigest()

    def write_text(self, relative: str, text: str) -> None:
        self.write_bytes(relative, text.encode("utf-8"))

    def write_json(self, relative: str, payload: dict[str, object] | list[object]) -> None:
        self.write_bytes(
            relative,
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )

    def write_sealed(self, model: EnvelopedArtifact, *, domain: str) -> None:
        """Persist the authoritative payload file plus the derived audit view."""
        content_ref = model.artifact.content_ref
        self.write_bytes(content_ref, artifact_payload_bytes(model, domain=domain))
        self.write_json(_audit_ref(content_ref), model.model_dump(mode="json", exclude=set()))

    def write_manifest(self) -> None:
        """Write whole-file digests of everything this run produced."""
        manifest = {
            "hash_convention": HASH_CONVENTION,
            "files": dict(sorted(self._digests.items())),
        }
        write_private_bytes(
            self._run_directory / MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            root=self._run_directory,
        )


def _audit_ref(content_ref: str) -> str:
    if not content_ref.endswith(".payload.json"):  # pragma: no cover - convention guard
        msg = f"sealed artifacts must use .payload.json content refs, got {content_ref!r}"
        raise ValueError(msg)
    return content_ref.removesuffix(".payload.json") + ".audit.json"


_SHA256_HEX_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _parsed_integrity_entries(manifest: object) -> dict[str, str] | None:
    """Validate and return the manifest's ``files`` mapping, or ``None``.

    Fails closed on any structural surprise — wrong top-level type, a
    non-mapping ``files`` value, a non-string path or digest, a
    malformed digest, an absolute or traversal path, or two raw keys
    that normalize to the same path — rather than raising or silently
    treating a malformed manifest as "nothing to check". Unknown
    top-level keys besides ``files`` are ignored (forward compatible);
    only the ``files`` mapping itself is a closed shape.
    """
    if not isinstance(manifest, dict):
        return None
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        return None

    entries: dict[str, str] = {}
    seen_normalized: set[str] = set()
    for relative, digest in files.items():
        if not isinstance(relative, str) or not isinstance(digest, str):
            return None
        if not _SHA256_HEX_PATTERN.fullmatch(digest):
            return None
        normalized = _normalized_relative_path(relative)
        if normalized is None or normalized in seen_normalized:
            return None
        seen_normalized.add(normalized)
        entries[relative] = digest
    return entries


def _normalized_relative_path(relative: str) -> str | None:
    """A safe, normalized relative POSIX path, or ``None`` if unsafe."""
    if not relative or relative != relative.strip() or "\\" in relative:
        return None
    candidate = PurePosixPath(relative)
    if candidate.is_absolute():
        return None
    parts = candidate.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        return None
    return candidate.as_posix()


def verify_run_integrity(run_directory: Path) -> tuple[str, ...]:
    """Re-hash every manifest entry and report deviations and unlisted files."""
    manifest_path = run_directory / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return ("integrity manifest is missing",)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ("integrity manifest is unreadable or not valid JSON",)

    listed = _parsed_integrity_entries(manifest)
    if listed is None:
        return ("integrity manifest is structurally invalid",)

    issues: list[str] = []
    for relative, digest in sorted(listed.items()):
        path = run_directory / relative
        if not path.is_file():
            issues.append(f"missing file: {relative}")
            continue
        if sha256(path.read_bytes()).hexdigest() != digest:
            issues.append(f"digest mismatch: {relative}")
    for path in sorted(run_directory.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        relative = path.relative_to(run_directory).as_posix()
        if relative not in listed:
            issues.append(f"unlisted file: {relative}")
    return tuple(issues)


def run_package(
    *,
    input_dir: Path,
    output_dir: Path,
    bid_id: str,
    process: bool,
    authorized_non_production_test: bool = False,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    preflight_config: PreflightConfig | None = None,
    scanner: DeterministicPreflightScanner | None = None,
    parser_registry: Callable[[str], DocumentParser | None] = parser_for,
) -> PipelineRunSummary:
    """Run intake, preflight, package gate, and (only if cleared and
    explicitly requested) parsing, extraction, normalization, the quality
    gate, and the working or review package."""
    validate_bid_id(bid_id)
    input_root = input_dir.resolve()
    output_root = output_dir.resolve()
    _validate_directories(
        input_root,
        output_root,
        process=process,
        authorized_non_production_test=authorized_non_production_test,
    )

    if now is not None:
        tick: Callable[[], datetime] = lambda: now  # noqa: E731 - frozen clock
    elif clock is not None:
        tick = clock
    else:
        tick = lambda: datetime.now(UTC)  # noqa: E731

    started_at = tick()
    run_id = run_id_for(started_at)
    artifact_ids = ArtifactIdAllocator(started_at)
    active_scanner = scanner or DeterministicPreflightScanner(config=preflight_config)
    size_limit = (
        preflight_config.max_file_size_bytes
        if preflight_config is not None
        else DEFAULT_MAX_FILE_SIZE_BYTES
    )
    stages = _initial_stages()

    # The final run path is fully constructed, resolved, and containment-
    # checked before intake, so nothing is ever written for a run whose
    # bid ID or path did not validate — including empty packages.
    run_directory = _validated_run_directory(output_root, bid_id=bid_id, run_id=run_id)

    stages["intake"]["attempted"] = True
    package = register_package(
        input_root,
        bid_id=bid_id,
        run_id=run_id,
        artifact_ids=artifact_ids,
        max_file_size_bytes=size_limit,
    )
    stages["intake"]["succeeded"] = True
    stages["intake"]["outcome"] = (
        StageOutcome.REVIEW_REQUIRED.value if package.rejected else StageOutcome.SUCCEEDED.value
    )
    ensure_private_directory(run_directory, root=output_root)
    writer = _RunWriter(run_directory)

    document_results: list[SecurityResult] = []
    states: dict[str, DocumentRunState] = {}
    stages["preflight"]["attempted"] = bool(package.documents)
    for item in package.documents:
        document = item.document
        try:
            assessment = active_scanner.assess(
                artifact=document.artifact,
                document_id=document.document_id,
                filename=Path(document.filename).name,
                content=item.content,
                assessed_at=started_at,
            )
        except Exception:
            states[document.document_id] = DocumentRunState(
                document_id=document.document_id,
                filename=document.filename,
                verdict=None,
                assessment_error="preflight assessment failed; document stays untrusted",
            )
            continue
        writer.write_json(
            f"security/{document.document_id}-preflight.json",
            assessment.model_dump(mode="json"),
        )
        result = decide_document(assessment, decided_at=started_at)
        writer.write_json(
            f"security/{document.document_id}-security-result.json",
            result.model_dump(mode="json"),
        )
        document_results.append(result)
        states[document.document_id] = DocumentRunState(
            document_id=document.document_id,
            filename=document.filename,
            verdict=result.verdict.value,
        )
    preflight_complete = stages["preflight"]["attempted"] and len(document_results) == len(
        package.documents
    )
    stages["preflight"]["succeeded"] = preflight_complete
    if stages["preflight"]["attempted"]:
        stages["preflight"]["outcome"] = (
            StageOutcome.SUCCEEDED.value if preflight_complete else StageOutcome.FAILED.value
        )

    stages["package_gate"]["attempted"] = True
    gate = decide_package(
        tuple(document_results),
        registered=tuple(
            (item.document.document_id, item.document.artifact) for item in package.documents
        ),
        bid_id=bid_id,
        run_id=run_id,
        intake_rejections=tuple(
            f"{rejected.filename}: {rejected.reason}" for rejected in package.rejected
        ),
    )
    stages["package_gate"]["succeeded"] = True
    stages["package_gate"]["outcome"] = {
        PackageGateDecision.CLEARED: StageOutcome.SUCCEEDED,
        PackageGateDecision.REVIEW_REQUIRED: StageOutcome.REVIEW_REQUIRED,
        PackageGateDecision.BLOCKED: StageOutcome.FAILED,
    }[gate.decision].value
    writer.write_json(
        "security/package-gate.json",
        {
            "policy_id": gate.policy_id,
            "decision": gate.decision.value,
            "reasons": list(gate.reasons),
            "registered": [
                {
                    "document_id": item.document.document_id,
                    "artifact_id": item.document.artifact.artifact_id,
                }
                for item in package.documents
            ],
            "intake_rejections": [
                {"filename": rejected.filename, "reason": rejected.reason}
                for rejected in package.rejected
            ],
            "documents": [
                {"document_id": result.document_id, "verdict": result.verdict.value}
                for result in gate.document_results
            ],
            "cleared_documents": [cleared.document_id for cleared in gate.cleared],
        },
    )

    outcome, outputs, failed_streams, produced, quality = _downstream(
        package_documents=package.documents,
        gate=gate,
        states=states,
        process=process,
        writer=writer,
        bid_id=bid_id,
        run_id=run_id,
        artifact_ids=artifact_ids,
        started_at=started_at,
        parser_registry=parser_registry,
        stages=stages,
    )

    completed_at = tick()
    summary = PipelineRunSummary(
        run_id=run_id,
        bid_id=bid_id,
        package_name=package.package_name,
        outcome=outcome,
        processed=process and gate.allows_processing,
        gate=gate,
        documents=tuple(states[item.document.document_id] for item in package.documents),
        run_directory=run_directory,
        outputs=outputs,
        failed_streams=failed_streams,
        rejected=package.rejected,
        stages=stages,
        quality=quality,
        started_at=started_at,
        completed_at=completed_at,
    )
    _write_inventory(writer, package.documents, package.rejected, gate, summary)
    _write_summary(writer, summary, started_at, completed_at, produced)
    writer.write_manifest()
    return summary


def _downstream(
    *,
    package_documents: tuple[RegisteredDocument, ...],
    gate: PackageGateResult,
    states: dict[str, DocumentRunState],
    process: bool,
    writer: _RunWriter,
    bid_id: str,
    run_id: str,
    artifact_ids: ArtifactIdAllocator,
    started_at: datetime,
    parser_registry: Callable[[str], DocumentParser | None],
    stages: dict[str, StageReport],
) -> tuple[
    str,
    dict[str, str],
    tuple[ExtractionStream, ...],
    tuple[ArtifactReference, ...],
    QualityGateReport | None,
]:
    """Run parsing, extraction, normalization, quality gate, and packaging."""
    produced: list[ArtifactReference] = [item.document.artifact for item in package_documents]
    outputs: dict[str, str] = {}

    if gate.decision is PackageGateDecision.BLOCKED:
        return "blocked", outputs, (), tuple(produced), None
    if gate.decision is PackageGateDecision.REVIEW_REQUIRED:
        return "review-required", outputs, (), tuple(produced), None
    if not process:
        return "security-only", outputs, (), tuple(produced), None

    content_by_document = {item.document.document_id: item for item in package_documents}
    canonicals: list[CanonicalDocument] = []
    unsupported_documents = False
    technical_parse_failure = False
    stages["parsing"]["attempted"] = True
    for cleared in gate.cleared:
        item = content_by_document[cleared.document_id]
        document = item.document
        state = states[document.document_id]
        parser = parser_registry(document.file_type)
        if parser is None:
            unsupported_documents = True
            states[document.document_id] = DocumentRunState(
                document_id=state.document_id,
                filename=state.filename,
                verdict=state.verdict,
                parse_status="UNSUPPORTED",
                parse_detail=operator_safe_parser_message("PARSER_MISSING"),
                parse_error_code="PARSER_MISSING",
            )
            continue
        canonical_artifact_id = artifact_ids.allocate()
        try:
            parsed = parser.parse(
                cleared=cleared,
                content=item.content,
                filename=document.filename,
                canonical_artifact_id=canonical_artifact_id,
            )
            canonical = build_canonical_document(
                cleared,
                parsed,
                filename=document.filename,
                canonical_artifact_id=canonical_artifact_id,
                run_id=run_id,
                created_at=started_at,
                parser_name=parser.parser_name,
                parser_version=parser.parser_version,
            )
        except ParserError as failure:
            # Never persist str(failure) or a raw error_code attribute:
            # exception texts and attributes may carry document content or
            # library internals. Only an allowlisted code and its static
            # operator-safe message are recorded.
            if isinstance(failure, UnsupportedDocumentError):
                unsupported_documents = True
                parse_status = "UNSUPPORTED"
            else:
                technical_parse_failure = True
                parse_status = "FAILED"
            error_code = sanitize_error_code(failure.error_code)
            states[document.document_id] = DocumentRunState(
                document_id=state.document_id,
                filename=state.filename,
                verdict=state.verdict,
                parse_status=parse_status,
                parse_detail=operator_safe_parser_message(error_code),
                parse_error_code=error_code,
            )
            continue
        canonicals.append(canonical)
        produced.append(canonical.artifact.as_reference())
        writer.write_sealed(canonical, domain=CANONICAL_DOMAIN)
        states[document.document_id] = DocumentRunState(
            document_id=state.document_id,
            filename=state.filename,
            verdict=state.verdict,
            parse_status="PARSED",
            warnings=parsed.warnings,
        )
    stages["parsing"]["succeeded"] = not technical_parse_failure
    if technical_parse_failure:
        stages["parsing"]["outcome"] = StageOutcome.FAILED.value
    elif unsupported_documents:
        stages["parsing"]["outcome"] = StageOutcome.REVIEW_REQUIRED.value
    else:
        stages["parsing"]["outcome"] = StageOutcome.SUCCEEDED.value

    documents = tuple(canonicals)
    requirements: RequirementExtractionResult | None = None
    deadlines: DeadlineExtractionResult | None = None
    formalities: FormalityExtractionResult | None = None
    failed: list[ExtractionStream] = []
    stages["extraction"]["attempted"] = True
    for stream, stream_name in _EXTRACTORS:
        try:
            result_artifact: EnvelopedArtifact
            if stream is ExtractionStream.REQUIREMENT:
                requirements = extract_requirements(
                    documents,
                    bid_id=bid_id,
                    run_id=run_id,
                    artifact_id=artifact_ids.allocate(),
                    created_at=started_at,
                )
                result_artifact = requirements
            elif stream is ExtractionStream.DEADLINE:
                deadlines = extract_deadlines(
                    documents,
                    bid_id=bid_id,
                    run_id=run_id,
                    artifact_id=artifact_ids.allocate(),
                    created_at=started_at,
                )
                result_artifact = deadlines
            else:
                formalities = extract_formalities(
                    documents,
                    bid_id=bid_id,
                    run_id=run_id,
                    artifact_id=artifact_ids.allocate(),
                    created_at=started_at,
                )
                result_artifact = formalities
        except Exception:
            failed.append(stream)
            continue
        produced.append(result_artifact.artifact.as_reference())
        writer.write_sealed(result_artifact, domain=extraction_domain(stream_name))
    stages["extraction"]["succeeded"] = not failed
    stages["extraction"]["outcome"] = (
        StageOutcome.FAILED.value if failed else StageOutcome.SUCCEEDED.value
    )

    stages["normalization"]["attempted"] = True
    dataset = merge_extractions(
        bid_id=bid_id,
        run_id=run_id,
        artifact_id=artifact_ids.allocate(),
        created_at=started_at,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        failed_streams=tuple(failed),
    )
    stages["normalization"]["succeeded"] = True
    stages["normalization"]["outcome"] = StageOutcome.SUCCEEDED.value
    produced.append(dataset.artifact.as_reference())
    writer.write_sealed(dataset, domain=NORMALIZED_DOMAIN)

    stages["quality_gate"]["attempted"] = True
    parsed_quality = tuple(
        ParsedDocumentQuality(
            document_id=state.document_id,
            filename=state.filename,
            warnings=state.warnings,
        )
        for state in states.values()
        if state.parse_status == "PARSED"
    )
    unprocessed = tuple(
        UnprocessedDocument(
            document_id=state.document_id,
            filename=state.filename,
            reason=state.parse_detail or "not processed",
        )
        for state in states.values()
        if state.parse_status in {"UNSUPPORTED", "FAILED"}
    )
    quality = evaluate_quality(
        parsed=parsed_quality,
        unprocessed=unprocessed,
        canonicals=documents,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        evaluated_at=started_at,
    )
    # Technical execution of the gate succeeded; its business status is
    # reported separately as the stage outcome.
    stages["quality_gate"]["succeeded"] = True
    stages["quality_gate"]["outcome"] = {
        QualityGateStatus.ACCEPTABLE: StageOutcome.SUCCEEDED,
        QualityGateStatus.REVIEW_REQUIRED: StageOutcome.REVIEW_REQUIRED,
        QualityGateStatus.FAILED: StageOutcome.FAILED,
    }[quality.status].value
    writer.write_json("quality/quality-gate.json", quality.model_dump(mode="json"))

    if quality.status is QualityGateStatus.FAILED:
        return "failed", outputs, tuple(failed), tuple(produced), quality
    if quality.status is QualityGateStatus.REVIEW_REQUIRED:
        review = build_review_package(
            quality,
            bid_id=bid_id,
            run_id=run_id,
            generated_at=started_at,
            requirements=requirements,
            deadlines=deadlines,
            formalities=formalities,
            dataset=dataset,
            parser_warnings=tuple(
                warning for state in parsed_quality for warning in state.warnings
            ),
        )
        writer.write_json("review-package/review-package.json", review.model_dump(mode="json"))
        writer.write_text("review-package/review-package.md", render_review_markdown(review))
        outputs["review_package_json"] = "review-package/review-package.json"
        outputs["review_package_markdown"] = "review-package/review-package.md"
        return "review-required", outputs, tuple(failed), tuple(produced), quality

    stages["working_package"]["attempted"] = True
    assert requirements is not None and deadlines is not None and formalities is not None
    package = build_working_package(
        dataset,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        quality=quality,
        artifact_id=artifact_ids.allocate(),
        generated_at=started_at,
    )
    produced.append(package.artifact.as_reference())
    writer.write_sealed(package, domain=WORKING_PACKAGE_DOMAIN)
    requirements_by_id = {item.requirement_id: item for item in requirements.requirements}
    markdown = render_markdown(
        package,
        requirements=tuple(
            requirements_by_id[reference.object_id] for reference in dataset.requirements
        ),
        completeness=dataset.completeness,
    )
    writer.write_text("working-package/working-package.md", markdown)
    stages["working_package"]["succeeded"] = True
    stages["working_package"]["outcome"] = StageOutcome.SUCCEEDED.value
    outputs["working_package_payload"] = package.artifact.content_ref
    outputs["working_package_audit"] = _audit_ref(package.artifact.content_ref)
    outputs["working_package_markdown"] = "working-package/working-package.md"
    return "completed", outputs, (), tuple(produced), quality


def _validate_directories(
    input_root: Path,
    output_root: Path,
    *,
    process: bool,
    authorized_non_production_test: bool,
) -> None:
    if input_root == output_root:
        msg = "input and output directories must be different"
        raise ValueError(msg)
    if input_root in output_root.parents or output_root in input_root.parents:
        msg = "input and output directories must not be nested inside each other"
        raise ValueError(msg)
    for path in (input_root, output_root):
        if is_repository_harness_path(path):
            msg = (
                "the repository inbox/ and results/ harness directories (and paths "
                "below them) are not permitted as pipeline directories; choose "
                "explicit local paths"
            )
            raise ValueError(msg)
    if is_inside_repository_checkout(output_root):
        msg = (
            "the output directory must live outside any repository checkout; "
            "choose a local working directory instead"
        )
        raise ValueError(msg)
    if process and not is_trusted_synthetic_input(input_root):
        if not authorized_non_production_test:
            msg = (
                "full processing (--process) is limited to this repository's "
                "own fixtures/synthetic/ inputs; for other local test data "
                "pass --authorized-non-production-test (this is NOT a "
                "production release and does not bypass any gate)"
            )
            raise ValueError(msg)


def _validated_run_directory(output_root: Path, *, bid_id: str, run_id: str) -> Path:
    """Construct, resolve, and containment-check the final run directory.

    The bid ID is re-validated against the strict allowlist, the fully
    constructed path is resolved (following any pre-existing symlinks), and
    the resolved result must still lie below ``output_root`` and outside
    every repository checkout and harness directory.
    """
    validate_bid_id(bid_id)
    resolved = (output_root / bid_id / run_id).resolve()
    if resolved == output_root or not resolved.is_relative_to(output_root):
        msg = "the run directory must lie below the output directory"
        raise ValueError(msg)
    if is_repository_harness_path(resolved):
        msg = (
            "the resolved run directory points into a repository inbox/ or "
            "results/ harness directory; refusing to write"
        )
        raise ValueError(msg)
    if is_inside_repository_checkout(resolved):
        msg = "the resolved run directory points inside a repository checkout; refusing to write"
        raise ValueError(msg)
    return resolved


def _write_inventory(
    writer: _RunWriter,
    package_documents: tuple[RegisteredDocument, ...],
    rejected: tuple[RejectedFile, ...],
    gate: PackageGateResult,
    summary: PipelineRunSummary,
) -> None:
    """Record every registered document — decided, unassessed, or rejected."""
    verdicts = {result.document_id: result for result in gate.document_results}
    states = {state.document_id: state for state in summary.documents}
    entries: list[DocumentInventoryEntry] = []
    unassessed: list[dict[str, object]] = []
    for item in package_documents:
        document = item.document
        result = verdicts.get(document.document_id)
        if result is None:
            state = states[document.document_id]
            unassessed.append(
                {
                    "document_id": document.document_id,
                    "filename": document.filename,
                    "sha256": document.sha256,
                    "reason": state.assessment_error
                    or "no security decision exists for this document",
                }
            )
            continue
        state = states[document.document_id]
        if state.parse_status == "PARSED":
            processing_status = ProcessingStatus.COMPLETED
        elif state.parse_status in {"UNSUPPORTED", "FAILED"}:
            processing_status = ProcessingStatus.REQUIRES_REVIEW
        else:
            processing_status = ProcessingStatus.PENDING
        entries.append(
            DocumentInventoryEntry(
                bid_id=document.bid_id,
                document_id=document.document_id,
                artifact=document.artifact,
                filename=document.filename,
                file_type=document.file_type,
                mime_type=document.mime_type,
                hash=document.sha256,
                size=document.size_bytes,
                security_status=result.verdict,
                processing_status=processing_status,
            )
        )
    writer.write_json(
        "inventory/inventory.json",
        {
            "documents": [entry.model_dump(mode="json") for entry in entries],
            "unassessed": unassessed,
            "rejected_at_intake": [
                {"filename": item.filename, "reason": item.reason} for item in rejected
            ],
        },
    )


def _write_summary(
    writer: _RunWriter,
    summary: PipelineRunSummary,
    started_at: datetime,
    completed_at: datetime,
    produced: tuple[ArtifactReference, ...],
) -> None:
    if summary.outcome == "completed":
        stage = ProcessingStage.WORKING_PACKAGE_READY
        status = ProcessingStatus.COMPLETED
    elif summary.outcome == "security-only":
        stage = ProcessingStage.SECURITY_SCAN
        status = ProcessingStatus.COMPLETED
    elif summary.outcome == "failed":
        stage = ProcessingStage.QA
        status = ProcessingStatus.FAILED
    elif summary.quality is not None:
        stage = ProcessingStage.QA
        status = ProcessingStatus.REQUIRES_REVIEW
    else:
        stage = ProcessingStage.SECURITY_SCAN
        status = ProcessingStatus.REQUIRES_REVIEW

    errors = [f"{rejected.filename}: {rejected.reason}" for rejected in summary.rejected]
    errors.extend(
        f"{state.document_id}: {state.assessment_error or state.parse_detail}"
        for state in summary.documents
        if state.assessment_error or state.parse_detail
    )
    processing_run = ProcessingRun(
        run_id=summary.run_id,
        bid_id=summary.bid_id,
        stage=stage,
        status=status,
        started_at=started_at,
        updated_at=completed_at,
        completed_at=completed_at,
        artifacts=produced,
        errors=tuple(errors),
    )
    writer.write_json(
        "run-summary.json",
        {
            "pipeline": {"name": PIPELINE_NAME, "version": PIPELINE_VERSION},
            "run_id": summary.run_id,
            "bid_id": summary.bid_id,
            "package": summary.package_name,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "outcome": summary.outcome,
            "processed": summary.processed,
            "stages": summary.stages,
            "package_gate": {
                "policy_id": summary.gate.policy_id,
                "decision": summary.gate.decision.value,
                "reasons": list(summary.gate.reasons),
            },
            "quality_gate": (
                None
                if summary.quality is None
                else {
                    "gate": QUALITY_GATE_ID,
                    "status": summary.quality.status.value,
                    "signals": [
                        signal.model_dump(mode="json") for signal in summary.quality.signals
                    ],
                }
            ),
            "failed_streams": [stream.value for stream in summary.failed_streams],
            "rejected_files": [
                {"filename": rejected.filename, "reason": rejected.reason}
                for rejected in summary.rejected
            ],
            "documents": [state.as_dict() for state in summary.documents],
            "outputs": summary.outputs,
            "processing_run": processing_run.model_dump(mode="json"),
        },
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the ``bidfusion-run`` command line interface."""
    parser = argparse.ArgumentParser(
        prog="bidfusion-run",
        description=(
            "Run the local BidFusion walking skeleton for one RFP package: "
            "intake, deterministic preflight, versioned package gate, and — "
            "only with --process on a fully cleared package — parsing, "
            "extraction, normalization, the quality gate, and the working or "
            "review package."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Package directory with the RFP documents (never the repository inbox/).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help=(
            "Directory for run artifacts; must live outside any repository "
            "checkout (never the repository results/)."
        ),
    )
    parser.add_argument("--bid-id", default=None)
    parser.add_argument(
        "--process",
        action="store_true",
        help="Explicitly release downstream processing for a fully cleared package.",
    )
    parser.add_argument(
        "--authorized-non-production-test",
        action="store_true",
        help=(
            "Confirm an authorized, NON-PRODUCTION test on local data outside "
            "fixtures/synthetic/. This is not a production release and does "
            "not bypass the security or quality gates."
        ),
    )
    parser.add_argument("--max-file-size-mb", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.max_file_size_mb <= 0:
        parser.error("--max-file-size-mb must be positive")
    started_at = datetime.now(UTC)
    bid_id = arguments.bid_id or f"BID-{started_at.year}-000001"

    try:
        summary = run_package(
            input_dir=arguments.input,
            output_dir=arguments.output,
            bid_id=bid_id,
            process=arguments.process,
            authorized_non_production_test=arguments.authorized_non_production_test,
            preflight_config=PreflightConfig(
                max_file_size_bytes=arguments.max_file_size_mb * 1024 * 1024
            ),
        )
    except (OSError, ValueError) as failure:
        print(f"bidfusion-run: {failure}", file=sys.stderr)
        return 2

    quality_note = "" if summary.quality is None else f", quality {summary.quality.status.value}"
    print(
        f"Package {summary.package_name!r}: gate {summary.gate.decision.value}"
        f"{quality_note}, outcome {summary.outcome} "
        f"({len(summary.documents)} document(s))."
    )
    for reason in summary.gate.reasons:
        print(f"  - {reason}")
    print(f"Run directory: {summary.run_directory}")
    if "working_package_markdown" in summary.outputs:
        print(
            "Working package: "
            f"{summary.run_directory / summary.outputs['working_package_markdown']}"
        )
    if "review_package_markdown" in summary.outputs:
        print(
            "Review package (NOT a complete working package): "
            f"{summary.run_directory / summary.outputs['review_package_markdown']}"
        )
    return summary.exit_code


def cli() -> None:
    """Installed console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
