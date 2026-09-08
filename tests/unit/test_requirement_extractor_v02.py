"""Extractor-level tests for requirement extraction v0.2 (label-free rules).

All documents built here are invented synthetic German procurement text
run through the real preflight -> gate -> parser chain.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from conftest import build_package_canonicals
from openpyxl import Workbook

from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.schemas import CanonicalDocument, RequirementModality
from bidfusion.schemas.extraction import RequirementExtractionResult

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

LB_TXT = "\n".join(
    [
        "Synthetische Leistungsbeschreibung Sicherheitsdienste",
        "1. Beschreibung der bestehenden Umgebung",
        "Der Auftraggeber betreibt 12 Standorte mit rund 1.500 Arbeitsplaetzen.",
        "2. Anforderungen an den Betrieb",
        "2.1 Der Dienstleister muss ein Service Desk an Werktagen",
        "von 8 bis 18 Uhr betreiben.",
        "2.2 Die Betriebsdokumentation ist quartalsweise zu aktualisieren.",
        "2.3 Das Kundenportal soll eine Exportfunktion anbieten.",
        "2.4 Ein eigenes Rechenzentrum muss nicht betrieben werden.",
        "REQ-Z1: The operator must run a synthetic legacy labelled control.",
        "3. Hinweise",
        "Die Preise verstehen sich netto zuzueglich Umsatzsteuer.",
    ]
)


def canonicals_for(tmp_path: Path, files: dict[str, bytes]) -> tuple[CanonicalDocument, ...]:
    package = tmp_path / "package"
    package.mkdir()
    for name, content in files.items():
        (package / name).write_bytes(content)
    return build_package_canonicals(package, tuple(files))


@pytest.fixture
def lb_canonicals(tmp_path: Path) -> tuple[CanonicalDocument, ...]:
    return canonicals_for(tmp_path, {"leistung.txt": LB_TXT.encode("utf-8")})


def extract(
    documents: tuple[CanonicalDocument, ...],
) -> RequirementExtractionResult:
    return extract_requirements(
        documents,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000021",
        created_at=NOW,
    )


def test_label_free_clauses_are_extracted_with_families(
    lb_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    result = extract(lb_canonicals)
    texts = {item.normalized_text for item in result.requirements}

    assert any(
        text and text.startswith("Der Dienstleister muss ein Service Desk") for text in texts
    )
    assert any(text and text.startswith("Die Betriebsdokumentation") for text in texts)
    assert any(text and text.startswith("Das Kundenportal soll") for text in texts)
    # facts, headings, and price notes stay out
    assert not any(text and "1.500 Arbeitsplaetzen" in text for text in texts)
    assert not any(text and "netto" in text for text in texts)
    assert not any(text and text.startswith("Beschreibung der bestehenden") for text in texts)


def test_explicit_labels_keep_first_ids_and_method(
    lb_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    result = extract(lb_canonicals)
    first = result.requirements[0]
    assert first.requirement_id == "REQ-000001"
    assert first.original_text.startswith("REQ-Z1:")
    assert first.extraction.method == "rule"
    # label-free detections come after every explicit label and carry
    # their rule family in the extraction method
    families = {item.extraction.method for item in result.requirements[1:]}
    assert families <= {
        "rule/numbered-modal",
        "rule/criterion-or-question",
        "rule/contractual-obligation",
        "rule/structured-table",
    }
    assert "rule/numbered-modal" in families


def test_multi_line_clause_is_joined_with_honest_provenance(
    lb_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    result = extract(lb_canonicals)
    joined = next(
        item
        for item in result.requirements
        if item.normalized_text and item.normalized_text.startswith("Der Dienstleister muss")
    )
    assert joined.original_text.endswith("von 8 bis 18 Uhr betreiben.")
    assert joined.source.locator.paragraph_id is not None
    assert len(joined.additional_sources) == 1
    assert joined.additional_sources[0].locator.paragraph_id is not None
    assert joined.modality is RequirementModality.MUST


def test_negated_clause_is_not_a_positive_requirement(
    lb_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    result = extract(lb_canonicals)
    negated = next(
        item
        for item in result.requirements
        if item.normalized_text and "muss nicht betrieben werden" in item.normalized_text
    )
    assert negated.modality is RequirementModality.INFORMATIONAL
    assert negated.confidence <= 0.5


def test_extraction_is_deterministic_across_runs(
    lb_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    first = extract(lb_canonicals)
    second = extract(lb_canonicals)
    assert [item.requirement_id for item in first.requirements] == [
        item.requirement_id for item in second.requirements
    ]
    assert [item.original_text for item in first.requirements] == [
        item.original_text for item in second.requirements
    ]


def test_same_occurrence_is_never_emitted_twice(
    lb_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    result = extract(lb_canonicals)
    occurrences = [
        (item.source.locator.paragraph_id, item.original_text) for item in result.requirements
    ]
    assert len(occurrences) == len(set(occurrences))


def build_table_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Anforderungen"
    rows = [
        ("Nr.", "Anforderung", "Modalitaet"),
        ("A-1", "Der Anbieter betreibt ein zertifiziertes ISMS.", "Muss"),
        ("A-2", "Die Berichte sind monatlich vorzulegen.", ""),
        ("K-3", "Wie gewaehrleisten Sie die Datensicherung?", "B"),
        ("4", "Anzahl Arbeitsplaetze", "1500"),
        ("5", "Serverpauschale pro Monat", "1.250,00 EUR"),
        ("Summe", "", "120000"),
    ]
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_structured_xlsx_rows_are_extracted_with_cell_provenance(
    tmp_path: Path,
) -> None:
    documents = canonicals_for(tmp_path, {"matrix.xlsx": build_table_workbook()})
    result = extract(documents)

    texts = [item.normalized_text for item in result.requirements]
    assert "Der Anbieter betreibt ein zertifiziertes ISMS." in texts
    assert "Die Berichte sind monatlich vorzulegen." in texts
    assert "Wie gewaehrleisten Sie die Datensicherung?" in texts
    assert len(result.requirements) == 3

    isms = result.requirements[0]
    assert isms.modality is RequirementModality.MUST
    assert isms.source.locator.cell_id is not None
    assert isms.source.locator.cell_id.startswith("Anforderungen!")
    assert isms.extraction.method == "rule/structured-table"
