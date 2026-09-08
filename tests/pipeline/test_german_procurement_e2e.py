"""End-to-end test: synthetic German tender through gate, parser, and v0.2.

Everything in ``fixtures/synthetic/rfp-german-procurement`` is invented.
The expected counts below are the fixture's specification: 43 requirement
occurrences across the five documents plus a bank of negative controls
(headings, facts/sizing, prices, dates, versions, CVEs, cross references,
legal background) that must never be extracted.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from bidfusion.orchestration import run_package

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "fixtures" / "synthetic" / "rfp-german-procurement"
BID_ID = "BID-2026-000123"

EXPECTED_BY_DOCUMENT = {
    "leistungsbeschreibung.pdf": 16,
    "kriterienkatalog.pdf": 8,
    "teilnahmebedingungen.pdf": 7,
    "vertrag.pdf": 8,
    "preisblatt.xlsx": 4,
}
EXPECTED_BY_FAMILY = {
    "rule/numbered-modal": 21,
    "rule/criterion-or-question": 16,
    "rule/contractual-obligation": 2,
    "rule/structured-table": 4,
}
EXPECTED_BY_MODALITY = {
    "MUST": 28,
    "SHOULD": 2,
    "MAY": 2,
    "UNKNOWN": 9,
    "INFORMATIONAL": 2,
}
NEGATIVE_CONTROL_SNIPPETS = (
    "1.500 Arbeitsplätzen",  # sizing fact
    "35 Server",  # sizing fact
    "Version 3.2.1",  # version reference
    "Ortsbegehung",  # date/event statement
    "2.400 Stück",  # quantity fact
    "CVE-2026-1234",  # vulnerability identifier
    "Punktzahl",  # evaluation metadata
    "Anhang entnommen",  # cross reference without obligation
    "Grundpauschale",  # price row
    "Anzahl Standorte",  # sizing row
    "gesetzlichen Regelungen",  # reference-only contract clause
    "Anlage 2",  # reference-only contract clause
    "deutschem Recht",  # legal background
    "langfristige Zusammenarbeit",  # narrative background
)


def extract_via_pipeline(tmp_path: Path) -> dict[str, Any]:
    summary = run_package(
        input_dir=PACKAGE,
        output_dir=tmp_path / "out",
        bid_id=BID_ID,
        process=True,
    )
    assert summary.gate.decision.value == "CLEARED"
    assert all(state.parse_status == "PARSED" for state in summary.documents)
    payload: dict[str, Any] = json.loads(
        (summary.run_directory / "extraction" / "requirement-extraction.payload.json").read_text()
    )["payload"]
    return payload


def test_german_package_extraction_counts_and_negative_controls(tmp_path: Path) -> None:
    payload = extract_via_pipeline(tmp_path)
    requirements = payload["requirements"]
    assert len(requirements) == sum(EXPECTED_BY_DOCUMENT.values()) == 43

    by_document = Counter(Path(item["source"]["filename"]).name for item in requirements)
    assert dict(by_document) == EXPECTED_BY_DOCUMENT

    by_family = Counter(item["extraction"]["method"] for item in requirements)
    assert dict(by_family) == EXPECTED_BY_FAMILY

    by_modality = Counter(item["modality"] for item in requirements)
    assert dict(by_modality) == EXPECTED_BY_MODALITY

    joined_texts = "\n".join(item["original_text"] for item in requirements)
    for snippet in NEGATIVE_CONTROL_SNIPPETS:
        assert snippet not in joined_texts, f"negative control leaked: {snippet}"


def test_german_package_negations_never_become_positive(tmp_path: Path) -> None:
    payload = extract_via_pipeline(tmp_path)
    negated = [
        item
        for item in payload["requirements"]
        if "nicht erforderlich" in item["original_text"]
        or "nicht Bestandteil" in item["original_text"]
        or "darf" in item["original_text"]
    ]
    assert negated, "the fixture negation controls must be detected"
    assert all(item["modality"] not in ("MUST", "SHOULD") for item in negated)


def test_german_package_provenance_and_determinism(tmp_path: Path) -> None:
    first = extract_via_pipeline(tmp_path / "a")
    second = extract_via_pipeline(tmp_path / "b")
    assert [item["requirement_id"] for item in first["requirements"]] == [
        item["requirement_id"] for item in second["requirements"]
    ]
    assert [item["original_text"] for item in first["requirements"]] == [
        item["original_text"] for item in second["requirements"]
    ]

    for item in first["requirements"]:
        assert item["source"]["canonical_artifact_id"] is not None
        locator = item["source"]["locator"]
        if Path(item["source"]["filename"]).suffix == ".xlsx":
            assert locator["cell_id"] is not None
        else:
            assert locator["page"] is not None
            assert locator["paragraph_id"] is not None

    joined = next(
        item
        for item in first["requirements"]
        if item["original_text"].endswith("des Auftraggebers vorzulegen.")
    )
    assert len(joined["additional_sources"]) == 1
