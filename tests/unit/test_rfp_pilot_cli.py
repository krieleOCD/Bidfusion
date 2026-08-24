"""Pilot CLI tests: authorization gates, bounds, and metadata-only output.

The pilot workflow runs the EXISTING pipeline (security gate, parsing,
extraction) on an operator-supplied local path, then normalizes a
bounded number of requirements through an injected ``LlmClient``.
Everything here is offline: the LLM client is a fake, and the CLI must
refuse to do anything without the explicit operator acknowledgement and
the ``BIDFUSION_LLM_ENABLED`` gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import populate_synthetic_golden_store
from pydantic import BaseModel

from bidfusion.llm_gateway.port import (
    GuardrailStatus,
    LlmCallStatus,
    SchemaValidationStatus,
    StructuredLlmRequest,
    StructuredLlmResult,
)
from bidfusion.rfp_api_pilot.contracts import LlmRequirementNormalization
from bidfusion.rfp_api_pilot.pilot_run import (
    ACKNOWLEDGEMENT_FLAG,
    ACKNOWLEDGEMENT_TEXT,
    DEFAULT_MAX_REQUIREMENTS,
    main,
)
from bidfusion.rfp_api_pilot.store import RfpApiPilotStore
from bidfusion.schemas.llm import LLMFinishReason

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)

ENABLED_ENV = {
    "BIDFUSION_LLM_ENABLED": "true",
    "BIDFUSION_LLM_API_KEY": "offline-test-orange-key",
}


@dataclass
class EchoingClient:
    """Offline LlmClient returning a valid normalization echoing the requirement id."""

    requests: list[StructuredLlmRequest] = field(default_factory=list)

    def complete_structured[T: BaseModel](
        self,
        *,
        request: StructuredLlmRequest,
        response_type: type[T],
    ) -> StructuredLlmResult[T]:
        self.requests.append(request)
        user_content = request.messages[-1].content
        requirement_id = next(
            line.split(": ", 1)[1]
            for line in user_content.splitlines()
            if line.startswith("requirement_id: ")
        )
        output = LlmRequirementNormalization.model_validate(
            {
                "schema_version": "1.0.0",
                "requirement_id": requirement_id,
                "requirement_type": "obligation",
                "mandatory_status": "mandatory",
                "technology": "microsoft_sentinel",
                "capability": "microsoft_sentinel_support",
                "normalization_status": "normalized",
                "confidence_band": "HIGH",
                "rationale": "Echoed synthetic normalization.",
            }
        )
        assert isinstance(output, response_type)
        return StructuredLlmResult(
            request_id=request.request_id,
            operation=request.operation,
            model_requested="openai/gpt-5.4-mini",
            model_reported="openai/gpt-5.4-mini",
            status=LlmCallStatus.COMPLETED,
            validated_output=output,
            finish_reason=LLMFinishReason.COMPLETED,
            usage=None,
            duration_ms=10,
            attempts=1,
            guardrail_status=GuardrailStatus.NOT_APPLIED,
            schema_validation_status=SchemaValidationStatus.VALID,
        )


def write_package(tmp_path: Path, lines: list[str]) -> Path:
    package = tmp_path / "anonymized-package"
    package.mkdir()
    (package / "requirements.txt").write_text("\n\n".join(lines), encoding="utf-8")
    return package


def base_argv(tmp_path: Path, package: Path, golden_root: Path) -> list[str]:
    return [
        "--input",
        str(package),
        "--bid-id",
        "BID-2026-000123",
        "--output",
        str(tmp_path / "run-output"),
        "--pilot-store-root",
        str(tmp_path / "pilot-store"),
        "--golden-store-root",
        str(golden_root),
        ACKNOWLEDGEMENT_FLAG,
    ]


def golden_root_for(tmp_path: Path) -> Path:
    root = tmp_path / "golden-store"
    populate_synthetic_golden_store(root)
    return root


# --- authorization gates -----------------------------------------------------


def test_missing_acknowledgement_refuses_to_run(tmp_path: Path, capsys: object) -> None:
    package = write_package(tmp_path, ["REQ-1: Sentinel monitoring is required."])
    argv = base_argv(tmp_path, package, golden_root_for(tmp_path))
    argv.remove(ACKNOWLEDGEMENT_FLAG)

    exit_code = main(argv, environ=ENABLED_ENV, llm_client=EchoingClient(), now=NOW)

    assert exit_code == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert ACKNOWLEDGEMENT_TEXT in captured.err
    assert not (tmp_path / "run-output").exists()


def test_disabled_gateway_refuses_before_any_processing(tmp_path: Path, capsys: object) -> None:
    package = write_package(tmp_path, ["REQ-1: Sentinel monitoring is required."])
    client = EchoingClient()
    exit_code = main(
        base_argv(tmp_path, package, golden_root_for(tmp_path)),
        environ={"BIDFUSION_LLM_ENABLED": "false"},
        llm_client=client,
        now=NOW,
    )

    assert exit_code == 1
    assert client.requests == []
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "BIDFUSION_LLM_ENABLED" in captured.err
    assert not (tmp_path / "run-output").exists()


def test_abbreviated_acknowledgement_flag_is_rejected(tmp_path: Path, capsys: object) -> None:
    """Only the full explicit flag counts; argparse prefix abbreviation must not."""
    package = write_package(tmp_path, ["REQ-1: Sentinel monitoring is required."])
    argv = base_argv(tmp_path, package, golden_root_for(tmp_path))
    argv.remove(ACKNOWLEDGEMENT_FLAG)
    argv.append("--operator-confirms-anonymized")  # abbreviated / malformed alias

    client = EchoingClient()
    with pytest.raises(SystemExit):
        main(argv, environ=ENABLED_ENV, llm_client=client, now=NOW)

    assert client.requests == []
    assert not (tmp_path / "run-output").exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "unrecognized arguments" in captured.err


# --- happy path ---------------------------------------------------------------


def test_pilot_run_writes_records_and_prints_metadata_only(tmp_path: Path, capsys: object) -> None:
    package = write_package(
        tmp_path,
        [
            "REQ-1: The service must support Microsoft Sentinel.",
            "REQ-2: 24/7 monitoring must be provided.",
        ],
    )
    client = EchoingClient()
    exit_code = main(
        base_argv(tmp_path, package, golden_root_for(tmp_path)),
        environ=ENABLED_ENV,
        llm_client=client,
        now=NOW,
    )

    assert exit_code == 0
    assert len(client.requests) == 2

    store = RfpApiPilotStore(tmp_path / "pilot-store")
    run_ids = [path.name for path in sorted((tmp_path / "pilot-store").iterdir())]
    assert len(run_ids) == 1
    records = store.read_requirement_records(run_ids[0])
    assert len(records) == 2
    assert records[0].llm.validation_status.value == "VALIDATED"
    assert records[0].golden_comparison is not None
    summary = store.read_summary(run_ids[0])
    assert summary is not None
    assert summary.metrics.requirements_total == 2
    assert summary.metrics.llm_valid == 2

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "ANONYMIZED REAL RFP PILOT" in captured.out
    assert "Requirements extracted: 2" in captured.out
    assert "Valid LLM results: 2" in captured.out
    # Metadata only: never the requirement text.
    assert "Sentinel" not in captured.out
    assert "24/7 monitoring must be provided" not in captured.out


def test_run_bound_limits_external_calls(tmp_path: Path, capsys: object) -> None:
    package = write_package(
        tmp_path,
        [
            "REQ-1: The service must support Microsoft Sentinel.",
            "REQ-2: 24/7 monitoring must be provided.",
            "REQ-3: Splunk support is required.",
        ],
    )
    client = EchoingClient()
    argv = base_argv(tmp_path, package, golden_root_for(tmp_path))
    argv += ["--max-requirements", "2"]

    exit_code = main(argv, environ=ENABLED_ENV, llm_client=client, now=NOW)

    assert exit_code == 0
    assert len(client.requests) == 2
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "Requirements extracted: 3" in captured.out
    assert "Sent to LLM: 2" in captured.out


def test_default_bound_is_conservative() -> None:
    assert DEFAULT_MAX_REQUIREMENTS <= 25


def test_presend_warning_blocks_that_requirement(tmp_path: Path, capsys: object) -> None:
    package = write_package(
        tmp_path,
        [
            "REQ-1: The service must support Microsoft Sentinel.",
            "REQ-2: Send reports to soc@customer-example.com.",
        ],
    )
    client = EchoingClient()
    exit_code = main(
        base_argv(tmp_path, package, golden_root_for(tmp_path)),
        environ=ENABLED_ENV,
        llm_client=client,
        now=NOW,
    )

    assert exit_code == 0
    assert len(client.requests) == 1  # the flagged requirement was never sent

    store = RfpApiPilotStore(tmp_path / "pilot-store")
    run_id = next(iter(sorted(path.name for path in (tmp_path / "pilot-store").iterdir())))
    records = store.read_requirement_records(run_id)
    statuses = {record.requirement_id: record.llm.validation_status.value for record in records}
    assert statuses["REQ-000002"] == "BLOCKED_BY_PRESEND_CHECK"
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "pre-send" in captured.out.lower()
    assert "soc@customer-example.com" not in captured.out
