"""Atomic requirement splitting v0.4 over invented text.

The splitter is a pure structural function on assembled clause blocks: it
turns one compound detection into atomic children with full provenance and
never invents text. All content is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from bidfusion.document_understanding.canonical import build_canonical_document
from bidfusion.document_understanding.parsers import parser_for
from bidfusion.extraction.requirements.label_free import RuleFamily, classify_block
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.extraction.requirements.splitting import (
    AtomicSplit,
    SplitRule,
    split_block,
)
from bidfusion.extraction.support import TextUnit
from bidfusion.schemas import (
    ArtifactReference,
    ArtifactType,
    CanonicalDocument,
    SecurityClearedArtifact,
    SecurityVerdict,
)
from bidfusion.schemas.extraction import Requirement
from bidfusion.schemas.provenance import SourceLocator, SourceReference
from bidfusion.security import DeterministicPreflightScanner, decide_document

_NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _unit(text: str, index: int) -> TextUnit:
    return TextUnit(
        text=text,
        source=SourceReference(
            bid_id="BID-2026-000123",
            document_id="DOC-001",
            filename="synthetic.txt",
            document_hash="ab" * 32,
            locator=SourceLocator(page=1, paragraph_id=f"P-{index:03d}"),
        ),
    )


def _units(*texts: str) -> tuple[TextUnit, ...]:
    return tuple(_unit(text, index) for index, text in enumerate(texts))


def _split(units: tuple[TextUnit, ...]) -> tuple[AtomicSplit, ...]:
    text = " ".join(unit.text for unit in units)
    detection = classify_block(text)
    assert detection is not None, f"synthetic block must classify: {text!r}"
    return split_block(units, detection)


def _own_paragraph_ids(split: AtomicSplit) -> tuple[str, ...]:
    return tuple(unit.source.locator.paragraph_id or "" for unit in split.units)


# ---------------------------------------------------------------------------
# BULLET_ITEM - positive structures
# ---------------------------------------------------------------------------


def test_bulleted_deliverables_under_leadin_split_into_atomic_children() -> None:
    units = _units(
        "Der Auftragnehmer erbringt folgende Leistungen:",
        "◼ Bereitstellung der Protokollierungsplattform",
        "◼ Erstellung monatlicher Betriebsberichte",
        "◼ Meldung kritischer Ereignisse innerhalb kurzer Fristen",
    )
    splits = _split(units)
    assert [split.split_rule for split in splits] == [SplitRule.BULLET_ITEM] * 3
    assert [split.original_text for split in splits] == [
        "◼ Bereitstellung der Protokollierungsplattform",
        "◼ Erstellung monatlicher Betriebsberichte",
        "◼ Meldung kritischer Ereignisse innerhalb kurzer Fristen",
    ]
    # the colon lead-in is inherited context, not a child of its own
    for split in splits:
        assert "folgende Leistungen" in split.effective_text
        assert split.effective_text.endswith(split.original_text.lstrip("◼ ").strip())
    assert [split.split_index for split in splits] == [1, 2, 3]
    assert all(split.split_total == 3 for split in splits)


def test_group_heading_becomes_context_of_its_subitems() -> None:
    units = _units(
        "◼ Planungsphase",
        "▪ Erstellung des Umsetzungskonzepts",
        "▪ Definition der Testszenarien",
        "◼ Betriebsphase",
        "▪ Bereitstellung der Ergebnisberichte",
    )
    splits = _split(units)
    assert len(splits) == 3
    assert splits[0].original_text == "▪ Erstellung des Umsetzungskonzepts"
    assert "Planungsphase" in splits[0].effective_text
    assert "Planungsphase" in splits[1].effective_text
    assert "Betriebsphase" in splits[2].effective_text
    assert "Planungsphase" not in splits[2].effective_text
    # heading units are provenance context, never own text
    assert "P-000" not in _own_paragraph_ids(splits[0])
    assert "P-000" in tuple(unit.source.locator.paragraph_id for unit in splits[0].context_units)


def test_continuation_lines_stay_with_their_bullet_item() -> None:
    units = _units(
        "◼ Nachverfolgung erkannter Schwachstellen von der Meldung",
        "bis zur nachweisbaren Behebung im Zielsystem",
        "◼ Bewertung der Schwachstellen nach Kritikalität",
    )
    splits = _split(units)
    assert len(splits) == 2
    assert splits[0].original_text == (
        "◼ Nachverfolgung erkannter Schwachstellen von der Meldung "
        "bis zur nachweisbaren Behebung im Zielsystem"
    )
    assert _own_paragraph_ids(splits[0]) == ("P-000", "P-001")


def test_consecutive_short_items_join_into_one_residual_child() -> None:
    units = _units(
        "◼ Kontaktkanäle für Meldungen",
        "▪ Telefon",
        "▪ E-Mail",
        "▪ Meldeportal",
        "▪ Übermittlung strukturierter Ereignisberichte",
    )
    splits = _split(units)
    assert len(splits) == 2
    assert splits[0].original_text == "▪ Telefon ▪ E-Mail ▪ Meldeportal"
    assert splits[1].original_text == "▪ Übermittlung strukturierter Ereignisberichte"
    assert "Kontaktkanäle" in splits[0].effective_text


def test_leading_normative_prose_without_colon_becomes_first_child() -> None:
    units = _units(
        "Der Auftragnehmer muss die folgenden Unterlagen einreichen.",
        "■ Angebotsschreiben mit rechtsverbindlicher Unterschrift",
        "■ Vollständig ausgefülltes Preisblatt",
    )
    splits = _split(units)
    assert len(splits) == 3
    assert splits[0].original_text == (
        "Der Auftragnehmer muss die folgenden Unterlagen einreichen."
    )
    assert splits[1].original_text == ("■ Angebotsschreiben mit rechtsverbindlicher Unterschrift")


def test_page_furniture_lead_is_context_only_and_out_of_effective_text() -> None:
    units = _units(
        "Seite 7 (15) zur Leistungsbeschreibung (Version 1)",
        "◼ Verschlüsselung der Übertragungswege zwischen den Systemen",
        "◼ Hochverfügbare Auslegung der Plattforminfrastruktur",
    )
    splits = _split(units)
    assert len(splits) == 2
    for split in splits:
        assert "Seite 7" not in split.effective_text
        assert "Seite 7" not in split.original_text
    # the furniture unit stays traceable as context of the first child
    context_ids = tuple(unit.source.locator.paragraph_id for unit in splits[0].context_units)
    assert "P-000" in context_ids


def test_every_block_unit_stays_traceable_across_children() -> None:
    units = _units(
        "Der Auftragnehmer erbringt folgende Leistungen:",
        "◼ Planungsphase",
        "▪ Erstellung des Umsetzungskonzepts",
        "▪ Telefon",
        "▪ Definition der Testszenarien",
        "◼ Bereitstellung der Ergebnisberichte im Regelbetrieb",
    )
    splits = _split(units)
    covered: set[str] = set()
    for split in splits:
        covered.update(_own_paragraph_ids(split))
        covered.update(unit.source.locator.paragraph_id or "" for unit in split.context_units)
    assert covered == {f"P-{index:03d}" for index in range(len(units))}


def test_children_keep_document_order_and_consistent_totals() -> None:
    units = _units(
        "◼ Bereitstellung der Protokollierungsplattform",
        "◼ Erstellung monatlicher Betriebsberichte",
        "◼ Meldung kritischer Ereignisse innerhalb kurzer Fristen",
    )
    splits = _split(units)
    assert [split.split_index for split in splits] == [1, 2, 3]
    assert {split.split_total for split in splits} == {3}
    first_ids = [_own_paragraph_ids(split)[0] for split in splits]
    assert first_ids == sorted(first_ids)


def test_long_lead_prose_continuation_survives_as_first_child() -> None:
    # the tail of a sentence whose start closed the previous block must
    # not vanish from the output text
    units = _units(
        "übernimmt dabei die Koordination der beteiligten Dienstleister im",
        "Störungsfall bis zur Wiederherstellung des vereinbarten Regelbetriebs",
        "◼ Anbindung des Meldewegs an das Ticketsystem des Auftraggebers",
        "◼ Bereitstellung einer Schnittstelle für Statusabfragen",
    )
    splits = _split(units)
    assert len(splits) == 3
    assert splits[0].original_text.startswith("übernimmt dabei die Koordination")
    assert "Regelbetriebs" in splits[0].original_text


def test_group_with_abbreviation_only_items_stays_one_child() -> None:
    # abbreviation-only enumeration entries ("BHB", "PHB") cannot stand
    # alone and their heading prefix must not become a free-floating
    # candidate either: the whole group honestly stays compound
    units = _units(
        "◼ Betriebsdokumentation",
        "▪ BHB",
        "▪ PHB",
        "▪ Anbindung der Quellsysteme",
        "◼ Erklärung der Abnahmebereitschaft",
    )
    splits = _split(units)
    assert len(splits) == 2
    assert splits[0].original_text == (
        "◼ Betriebsdokumentation ▪ BHB ▪ PHB ▪ Anbindung der Quellsysteme"
    )
    assert splits[1].original_text == "◼ Erklärung der Abnahmebereitschaft"


def test_flattened_enumeration_lead_stays_requirement_text() -> None:
    # a lead run without colon or numbering is content, not a heading —
    # its words must survive in a child's original text
    units = _units(
        "Dokumentationen Lizenzen Räumlichkeiten Ansprechpartner Daten weiteres",
        "▪ Allgemeine vorbereitende Maßnahmen",
        "▪ Vorgehen zum Wissenstransfer",
    )
    splits = _split(units)
    assert len(splits) == 3
    assert splits[0].original_text == (
        "Dokumentationen Lizenzen Räumlichkeiten Ansprechpartner Daten weiteres"
    )


def test_numbered_heading_lead_is_context_not_a_child() -> None:
    units = _units(
        "13. Checkliste der einzureichenden Unterlagen",
        "■ Angebotsschreiben mit rechtsverbindlicher Unterschrift",
        "■ Nachweis der Betriebshaftpflichtversicherung",
    )
    splits = _split(units)
    assert len(splits) == 2
    assert splits[0].original_text == ("■ Angebotsschreiben mit rechtsverbindlicher Unterschrift")
    assert "Checkliste" in splits[0].effective_text


def test_assignment_marker_fragment_merges_into_next_item() -> None:
    # a one-word responsibility-matrix row ("Analyse AN") is not an
    # independently assessable obligation; it stays with its neighbour
    units = _units(
        "• Analyse AN",
        "• Nachverfolgung der eröffneten Vorfälle mit allen beteiligten Stellen AN",
        "• Einleitung von Gegenmaßnahmen AN",
    )
    splits = _split(units)
    assert len(splits) == 2
    assert splits[0].original_text == (
        "• Analyse AN • Nachverfolgung der eröffneten Vorfälle mit allen beteiligten Stellen AN"
    )
    assert splits[1].original_text == "• Einleitung von Gegenmaßnahmen AN"


# ---------------------------------------------------------------------------
# BULLET_ITEM - negative structures (no split)
# ---------------------------------------------------------------------------


def test_single_requirement_prose_is_never_split() -> None:
    units = _units(
        "Der Auftragnehmer muss einen Überwachungsdienst unter Nutzung",
        "der vorhandenen Protokollquellen des Auftraggebers bereitstellen.",
    )
    assert _split(units) == ()


def test_single_bullet_item_is_not_split() -> None:
    units = _units(
        "Der Auftragnehmer erbringt folgende Leistungen:",
        "◼ Bereitstellung der Protokollierungsplattform im Regelbetrieb",
    )
    assert _split(units) == ()


def test_only_short_items_yield_no_split() -> None:
    units = _units(
        "◼ Entgegennahme von Meldungen",
        "▪ Telefon",
        "▪ E-Mail",
        "▪ Meldeportal",
    )
    assert _split(units) == ()


# ---------------------------------------------------------------------------
# NORMATIVE_SENTENCE - repeated modality inside one clause block
# ---------------------------------------------------------------------------


def test_repeated_modal_sentences_split_into_atomic_children() -> None:
    units = _units(
        "9.2 Das Preisangebot muss die gekennzeichneten Pflichtfelder enthalten. "
        "Es sind sämtliche Preise an den vorgesehenen Eingabefeldern anzugeben. "
        "Andere Eintragungen als Beträge dürfen nicht vorgenommen werden.",
    )
    splits = _split(units)
    assert [split.split_rule for split in splits] == [SplitRule.NORMATIVE_SENTENCE] * 3
    assert splits[0].original_text == (
        "9.2 Das Preisangebot muss die gekennzeichneten Pflichtfelder enthalten."
    )
    assert splits[1].original_text == (
        "Es sind sämtliche Preise an den vorgesehenen Eingabefeldern anzugeben."
    )
    assert splits[2].original_text == (
        "Andere Eintragungen als Beträge dürfen nicht vorgenommen werden."
    )
    assert [split.split_index for split in splits] == [1, 2, 3]


def test_sentence_children_map_to_their_source_units() -> None:
    # one wrapped line carries the end of sentence one and the start of
    # sentence two: it belongs to both children's provenance
    units = _units(
        "3.4 Der Auftragnehmer muss die Störungsannahme rund um die",
        "Uhr besetzen. Der Auftragnehmer soll Eskalationen innerhalb",
        "einer Stunde an den Auftraggeber berichten.",
    )
    splits = _split(units)
    assert len(splits) == 2
    assert splits[0].original_text.endswith("rund um die Uhr besetzen.")
    assert splits[1].original_text.startswith("Der Auftragnehmer soll Eskalationen")
    assert _own_paragraph_ids(splits[0]) == ("P-000", "P-001")
    assert _own_paragraph_ids(splits[1]) == ("P-001", "P-002")


def test_non_normative_sentence_stays_with_the_preceding_child() -> None:
    units = _units(
        "5.1 Der Auftragnehmer muss ein Betriebshandbuch pflegen. Das Betriebshandbuch",
        "beschreibt die vereinbarten Serviceprozesse. Der Auftragnehmer muss Änderungen",
        "mit dem Auftraggeber abstimmen.",
    )
    splits = _split(units)
    assert len(splits) == 2
    assert "beschreibt die vereinbarten Serviceprozesse" in splits[0].original_text
    assert splits[1].original_text == (
        "Der Auftragnehmer muss Änderungen mit dem Auftraggeber abstimmen."
    )


def test_abbreviations_and_numbering_are_never_sentence_boundaries() -> None:
    units = _units(
        "7.2 Der Bieter muss Referenzen, z.B. vergleichbare Projekte, ggf. mit",
        "Ansprechpartnern, bis zum 24.08.2026 einreichen und muss die",
        "Vollständigkeit gemäß Ziff. 4 bestätigen.",
    )
    assert _split(units) == ()


def test_performative_blocks_are_not_sentence_split() -> None:
    # performative contractor commitments describe one capability across
    # sentences; measured against real tender text, sentence children of
    # this family broke more requirement units than they freed
    units = _units(
        "Der Auftragnehmer stellt die historischen Versionsstände der Handbücher "
        "über die Vertragslaufzeit bereit. Der Auftragnehmer gewährt dem "
        "Auftraggeber jederzeit Zugriff auf die älteren Versionsstände.",
    )
    detection = classify_block(units[0].text)
    assert detection is not None
    assert detection.family is RuleFamily.PERFORMATIVE_OBLIGATION
    assert split_block(units, detection) == ()


def test_partyless_modal_statements_are_not_sentence_split() -> None:
    # party-less modal prose is the noisiest detection family; measured on
    # real tender text its sentence children mapped to nothing
    units = _units(
        "Die Nachweise müssen zum Zeitpunkt der Angebotsabgabe gültig sein. "
        "Der Ausgleich ist durch geeignete Unterlagen nachzuweisen.",
    )
    detection = classify_block(units[0].text)
    assert detection is not None
    assert detection.family is RuleFamily.MODAL_STATEMENT
    assert split_block(units, detection) == ()


# ---------------------------------------------------------------------------
# ASSIGNMENT_ROW - responsibility-matrix rows with trailing party markers
# ---------------------------------------------------------------------------


def test_assignment_rows_split_at_trailing_markers() -> None:
    units = _units(
        "Sammlung und Aufbereitung von",
        "Bedrohungsmeldungen und Ableitung",
        "umsetzbarer Maßnahmen",
        "AN",
        "Pflege der Wissensdatenbank AN",
        "Runbooks erarbeiten oder aktualisieren",
        "und zur Abnahme bringen",
        "Mitwirkung: Abnahme",
        "AN AG",
        "Optimierung der Analyseplattform AN",
    )
    splits = _split(units)
    assert [split.split_rule for split in splits] == [SplitRule.ASSIGNMENT_ROW] * 4
    assert splits[0].original_text == (
        "Sammlung und Aufbereitung von Bedrohungsmeldungen und Ableitung umsetzbarer Maßnahmen AN"
    )
    assert splits[1].original_text == "Pflege der Wissensdatenbank AN"
    assert splits[2].original_text == (
        "Runbooks erarbeiten oder aktualisieren und zur Abnahme bringen Mitwirkung: Abnahme AN AG"
    )
    assert splits[3].original_text == "Optimierung der Analyseplattform AN"
    # the assignment marker is layout, not requirement wording
    assert splits[1].effective_text == "Pflege der Wissensdatenbank"
    assert splits[2].effective_text.endswith("Mitwirkung: Abnahme")


def test_bullet_items_with_inner_assignment_rows_split_further() -> None:
    units = _units(
        "• Nachverfolgung der eröffneten Vorfälle AN",
        "• Einleitung von Gegenmaßnahmen AN",
        "Einbindung weiterer Dienstleister, sofern erforderlich AN",
        "Information der beteiligten Fachbereiche AN",
    )
    splits = _split(units)
    assert len(splits) == 4
    assert splits[1].original_text == "• Einleitung von Gegenmaßnahmen AN"
    assert splits[2].original_text == ("Einbindung weiterer Dienstleister, sofern erforderlich AN")
    assert splits[2].split_rule is SplitRule.ASSIGNMENT_ROW
    assert splits[3].original_text == "Information der beteiligten Fachbereiche AN"


def test_prose_ending_in_contractor_reference_is_not_an_assignment_row() -> None:
    # a wrapped line ending "... durch den AN" is contract prose, not a
    # responsibility-matrix row terminator
    units = _units(
        "Die Pflege der Systemdokumentation erfolgt fortlaufend durch den AN",
        "Die Aktualisierung erfolgt mindestens quartalsweise durch den AN",
    )
    detection = classify_block(" ".join(unit.text for unit in units))
    assert detection is not None
    assert split_block(units, detection) == ()


def test_may_sentences_do_not_create_sentence_children() -> None:
    # a bare possibility ("können") is advisory prose, not a second
    # independent obligation next to the real one
    units = _units(
        "8.4 Für die Angebotserstellung sind die übersandten Formulare zu verwenden. "
        "Soweit Ergänzungen erforderlich erscheinen, können sie als besondere "
        "Anlage beigefügt werden.",
    )
    assert _split(units) == ()


def test_single_obligation_with_definitions_is_not_sentence_split() -> None:
    units = _units(
        "3.1 Die Reaktionszeit beginnt mit der Alarmmeldung im System.",
        "Meldungen werden durch einen Analysten angenommen und bewertet.",
    )
    splits = _split(units)
    assert splits == ()


# ---------------------------------------------------------------------------
# POSITION_ROW - flattened catalogue rows keyed by position codes
# ---------------------------------------------------------------------------


def test_flattened_position_rows_split_at_position_codes() -> None:
    units = _units(
        "SO-XYZ-001 Basisdienst Betrieb M SO-XYZ-002 Zusatzdienst",
        "Bereitstellung E SO-XYZ-003 Erweiterte Analyse E",
    )
    splits = _split(units)
    assert [split.split_rule for split in splits] == [SplitRule.POSITION_ROW] * 3
    assert splits[0].original_text == "SO-XYZ-001 Basisdienst Betrieb M"
    assert splits[1].original_text == "SO-XYZ-002 Zusatzdienst Bereitstellung E"
    assert splits[2].original_text == "SO-XYZ-003 Erweiterte Analyse E"
    assert _own_paragraph_ids(splits[1]) == ("P-000", "P-001")


def test_standard_references_are_not_position_row_boundaries() -> None:
    units = _units(
        "SO-XYZ-004 Managementsystem nach ISO-27001 zertifiziert und gemäß",
        "BSI-200-2 dokumentiert M",
    )
    assert _split(units) == ()


# ---------------------------------------------------------------------------
# Extractor wiring: children replace the compound candidate deterministically
# ---------------------------------------------------------------------------


def _canonical_from_lines(*lines: str) -> CanonicalDocument:
    content = "\n".join(lines).encode("utf-8")
    filename = "synthetic-notes.txt"
    raw = ArtifactReference(
        artifact_id="ART-20260804-000001",
        bid_id="BID-2026-000123",
        run_id="RUN-20260804-0001",
        artifact_type=ArtifactType.RAW_DOCUMENT,
        schema_version="1.0.0",
        content_ref=f"package/{filename}",
        content_hash=sha256(content).hexdigest(),
    )
    assessment = DeterministicPreflightScanner().assess(
        artifact=raw,
        document_id="DOC-001",
        filename=filename,
        content=content,
        assessed_at=_NOW,
    )
    result = decide_document(assessment)
    assert result.verdict is SecurityVerdict.ALLOW
    cleared = SecurityClearedArtifact(artifact=raw, document_id="DOC-001", security_result=result)
    parser = parser_for("txt")
    assert parser is not None
    parsed = parser.parse(
        cleared=cleared,
        content=content,
        filename=filename,
        canonical_artifact_id="ART-20260804-000011",
    )
    return build_canonical_document(
        cleared,
        parsed,
        filename=filename,
        canonical_artifact_id="ART-20260804-000011",
        run_id="RUN-20260804-0001",
        created_at=_NOW,
        parser_name=parser.parser_name,
        parser_version=parser.parser_version,
    )


def _extract(document: CanonicalDocument) -> tuple[Requirement, ...]:
    result = extract_requirements(
        (document,),
        bid_id="BID-2026-000123",
        run_id="RUN-20260804-0001",
        artifact_id="ART-20260804-000021",
        created_at=_NOW,
    )
    return result.requirements


def test_children_replace_the_compound_candidate_with_provenance() -> None:
    document = _canonical_from_lines(
        "REQ-T1: Backups must be encrypted at rest.",
        "",
        "◼ Planungsphase",
        "▪ Erstellung des Umsetzungskonzepts",
        "▪ Definition der Testszenarien",
    )
    requirements = _extract(document)
    assert [item.requirement_id for item in requirements] == [
        "REQ-000001",
        "REQ-000002",
        "REQ-000003",
    ]
    # v0.1 explicit label untouched and first
    assert requirements[0].extraction.method == "rule"
    assert requirements[0].original_text.startswith("REQ-T1:")

    first, second = requirements[1], requirements[2]
    assert first.extraction.method == "rule/list-service-item"
    assert first.original_text == "▪ Erstellung des Umsetzungskonzepts"
    assert first.normalized_text == "Planungsphase: Erstellung des Umsetzungskonzepts"
    assert first.cross_references == (
        "split:bullet-item/1-of-2",
        "split-parent:para-1-002",
    )
    assert first.source.locator.paragraph_id == "para-1-003"
    context_ids = [item.locator.paragraph_id for item in first.additional_sources]
    assert context_ids == ["para-1-002"]
    assert second.cross_references == (
        "split:bullet-item/2-of-2",
        "split-parent:para-1-002",
    )
    # children inherit the compound detection's modality when their own
    # text carries no separate signal
    assert first.modality is second.modality


def test_unsplit_blocks_and_extraction_determinism_are_unchanged() -> None:
    document = _canonical_from_lines(
        "1.2 Der Dienstleister muss ein 24x7-Servicedesk betreiben.",
    )
    once = _extract(document)
    twice = _extract(document)
    assert once == twice
    assert len(once) == 1
    assert once[0].cross_references == ()
