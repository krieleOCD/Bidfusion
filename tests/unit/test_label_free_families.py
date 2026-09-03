"""Rule families B-E of requirement extractor v0.2 over invented text.

The classifiers are pure text functions; canonical-document wiring is
covered separately in the extractor tests. All content is synthetic.
"""

from __future__ import annotations

import pytest

from bidfusion.extraction.requirements.label_free import (
    RuleFamily,
    classify_block,
    classify_row,
)
from bidfusion.schemas import RequirementModality

# ---------------------------------------------------------------------------
# Family B - NUMBERED_MODAL_REQUIREMENT
# ---------------------------------------------------------------------------


def test_numbered_clause_with_muss_is_a_must_requirement() -> None:
    detection = classify_block("1.2 Der Dienstleister muss ein 24x7-Servicedesk betreiben.")
    assert detection is not None
    assert detection.family is RuleFamily.NUMBERED_MODAL_REQUIREMENT
    assert detection.modality is RequirementModality.MUST
    assert detection.normalized_text.startswith("Der Dienstleister muss")


def test_numbered_clause_with_soll_is_a_should_requirement() -> None:
    detection = classify_block("1.2.3 Das Portal soll eine Selbstbedienung anbieten.")
    assert detection is not None
    assert detection.family is RuleFamily.NUMBERED_MODAL_REQUIREMENT
    assert detection.modality is RequirementModality.SHOULD


def test_paragraph_clause_with_hat_zu_is_a_must_requirement() -> None:
    detection = classify_block("§ 7 Der Betreiber hat die Wartungsfenster abzustimmen.")
    assert detection is not None
    assert detection.modality is RequirementModality.MUST


def test_ziffer_clause_with_ist_zu_is_a_must_requirement() -> None:
    detection = classify_block("Ziffer 5.3 Ein Betriebshandbuch ist zu pflegen.")
    assert detection is not None
    assert detection.modality is RequirementModality.MUST


def test_anforderung_clause_with_modality_is_detected() -> None:
    detection = classify_block("Anforderung 7 Die Anmeldung muss protokolliert werden.")
    assert detection is not None
    assert detection.family is RuleFamily.NUMBERED_MODAL_REQUIREMENT


@pytest.mark.parametrize(
    "text",
    [
        # a number alone is never a requirement
        "3.1",
        # numbered descriptive heading without a requirement signal
        "3.1 Beschreibung der bestehenden Umgebung",
        # numbered fact / sizing statements stay facts
        "2.1 Die Umgebung umfasst 1.500 Arbeitsplaetze an 12 Standorten.",
        # modality without structural identifier is not family B
        "Der Dienstleister muss ein Ticketsystem betreiben.",
        # dates, versions, CVEs, addresses never qualify
        "24.08.2026 endet die Angebotsfrist.",
        "CVE-2026-1234 wurde bereits behoben.",
        "10.1.2.3 ist die Adresse des Gateways.",
        # cross reference without obligation
        "4.5 Siehe hierzu die Ausfuehrungen in Abschnitt 2.3.",
    ],
)
def test_family_b_rejects_non_requirements(text: str) -> None:
    detection = classify_block(text)
    assert detection is None or detection.family is not RuleFamily.NUMBERED_MODAL_REQUIREMENT


# ---------------------------------------------------------------------------
# Family C - CRITERION_OR_QUESTION
# ---------------------------------------------------------------------------


def test_explicit_kriterium_with_question_is_detected() -> None:
    detection = classify_block("Kriterium 12 Wie stellen Sie die Erreichbarkeit sicher?")
    assert detection is not None
    assert detection.family is RuleFamily.CRITERION_OR_QUESTION


def test_alphanumeric_criterion_with_evidence_request_is_detected() -> None:
    detection = classify_block("A-12 Vorlage einer aktuellen ISO-Zertifizierung als Nachweis.")
    assert detection is not None
    assert detection.family is RuleFamily.CRITERION_OR_QUESTION


def test_question_criterion_row_identifier_is_detected() -> None:
    detection = classify_block("K-17 Beschreiben Sie Ihr Eskalationsverfahren?")
    assert detection is not None
    assert detection.family is RuleFamily.CRITERION_OR_QUESTION


def test_exclusion_criterion_marker_is_detected() -> None:
    detection = classify_block(
        "Ausschlusskriterium: Eine Eigenerklaerung zur Zuverlaessigkeit ist einzureichen."
    )
    assert detection is not None
    assert detection.family is RuleFamily.CRITERION_OR_QUESTION


def test_numbered_criterion_with_confirmation_structure_is_detected() -> None:
    detection = classify_block(
        "2.4 Bestätigung: Der Bewerber bestätigt die Einhaltung der Mindestanforderung."
    )
    assert detection is not None
    assert detection.family is RuleFamily.CRITERION_OR_QUESTION


def test_arbitrary_prose_question_is_not_a_criterion() -> None:
    assert classify_block("Haben Sie noch Fragen zu dieser Unterlage?") is None


def test_descriptive_heading_with_kriterium_word_alone_is_not_detected() -> None:
    assert classify_block("Aufbau des Kriterienkatalogs") is None


def test_numbered_heading_with_bare_criterion_keyword_is_not_detected() -> None:
    # a section heading such as "2. Nachweise" carries a criterion keyword
    # but no criterion clause; headings must never become requirements
    assert classify_block("2. Nachweise") is None
    assert classify_block("3. Erklärungen") is None


# ---------------------------------------------------------------------------
# Family D - CONTRACTUAL_OBLIGATION
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Der Auftragnehmer ist verpflichtet, die Leistungen fristgerecht zu erbringen.",
        "Der Auftragnehmer gewährleistet die Verfügbarkeit der Plattform.",
        "Der Auftragnehmer hat die Nachweise jaehrlich vorzulegen.",
        "Der Auftragnehmer muss die Vertraulichkeit wahren.",
        "Der Auftragnehmer stellt sicher, dass alle Mitarbeitenden geschult sind.",
        "Die Dokumentation ist durch den Auftragnehmer aktuell zu halten.",
    ],
)
def test_contractual_obligations_are_detected_as_must(text: str) -> None:
    detection = classify_block(text)
    assert detection is not None
    assert detection.family is RuleFamily.CONTRACTUAL_OBLIGATION
    assert detection.modality is RequirementModality.MUST


@pytest.mark.parametrize(
    "text",
    [
        # narrative legal background without an obligation structure
        "Die Vertragsparteien haben diesen Vertrag nach deutschem Recht geschlossen.",
        "Fuer Streitigkeiten gilt der Gerichtsstand des Auftraggebers.",
        # a party mention alone is not an obligation
        "Der Auftragnehmer wurde im Jahr 2020 gegruendet.",
    ],
)
def test_legal_background_is_not_an_obligation(text: str) -> None:
    detection = classify_block(text)
    assert detection is None or detection.family is not RuleFamily.CONTRACTUAL_OBLIGATION


# ---------------------------------------------------------------------------
# Negation inside any family (Phase 4): never a positive MUST/SHOULD
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "3.4 Ein eigenes Rechenzentrum muss nicht betrieben werden.",
        "3.5 Eine Vor-Ort-Praesenz ist nicht erforderlich.",
        "3.6 Die Altsysteme sind nicht Bestandteil der Leistung.",
        "3.7 Schulungen liegen außerhalb des Leistungsumfangs.",
        "3.8 Die Migration ist nicht zu erbringen.",
    ],
)
def test_no_obligation_negations_are_never_positive_requirements(text: str) -> None:
    detection = classify_block(text)
    assert detection is not None
    assert detection.modality not in (
        RequirementModality.MUST,
        RequirementModality.SHOULD,
    )
    assert detection.modality is RequirementModality.INFORMATIONAL


def test_prohibitions_are_preserved_but_not_positive() -> None:
    detection = classify_block(
        "§ 9.2 Der Auftragnehmer darf personenbezogene Daten nicht außerhalb der EU verarbeiten."
    )
    assert detection is not None
    assert detection.modality not in (
        RequirementModality.MUST,
        RequirementModality.SHOULD,
    )


# ---------------------------------------------------------------------------
# Family E - STRUCTURED_TABLE_REQUIREMENT
# ---------------------------------------------------------------------------


def test_identifier_requirement_modality_row_is_detected() -> None:
    detection = classify_row(("A-3", "Der Anbieter betreibt ein zertifiziertes ISMS.", "Muss"))
    assert detection is not None
    assert detection.family is RuleFamily.STRUCTURED_TABLE_REQUIREMENT
    assert detection.modality is RequirementModality.MUST
    assert detection.text_cell_index == 1


def test_row_with_german_signal_in_text_cell_is_detected() -> None:
    detection = classify_row(("7", "Die Berichte sind monatlich vorzulegen."))
    assert detection is not None
    assert detection.modality is RequirementModality.MUST


def test_criterion_row_with_question_is_detected() -> None:
    detection = classify_row(("K-4", "Wie gewaehrleisten Sie die Datensicherung?", "B"))
    assert detection is not None
    assert detection.family is RuleFamily.STRUCTURED_TABLE_REQUIREMENT


# ---------------------------------------------------------------------------
# Bounded refinements surfaced by the synthetic fixture design
# ---------------------------------------------------------------------------


def test_kann_clause_with_obligated_party_is_a_may_requirement() -> None:
    detection = classify_block("4.1 Der Dienstleister kann zusaetzlich Schulungen anbieten.")
    assert detection is not None
    assert detection.modality is RequirementModality.MAY


def test_kann_reference_without_party_is_not_a_requirement() -> None:
    assert classify_block("4.2 Weitere Informationen können dem Anhang entnommen werden.") is None


def test_numbered_contract_clause_with_obligation_verb_is_detected() -> None:
    detection = classify_block(
        "§ 2 Der Auftragnehmer gewährleistet eine Verfügbarkeit von 99,5 Prozent."
    )
    assert detection is not None
    assert detection.family is RuleFamily.CONTRACTUAL_OBLIGATION
    assert detection.modality is RequirementModality.MUST


def test_exclusion_statement_with_identifier_is_detected_as_criterion() -> None:
    detection = classify_block("2.4 Verspaetete Antraege sind vom Verfahren ausgeschlossen.")
    assert detection is not None
    assert detection.family is RuleFamily.CRITERION_OR_QUESTION
    assert detection.modality not in (RequirementModality.MUST, RequirementModality.SHOULD)


@pytest.mark.parametrize(
    "cells",
    [
        # header rows
        ("Nr.", "Anforderung", "Modalitaet"),
        ("Pos.", "Beschreibung", "Preis"),
        # totals
        ("Summe", "", "120000"),
        ("Gesamt", "Gesamtpreis pro Jahr", "98000"),
        # price-only rows
        ("3", "Serverpauschale pro Monat", "1.250,00 EUR"),
        # sizing-only rows
        ("4", "Anzahl Arbeitsplaetze", "1500"),
        ("5", "Standorte", "12"),
        # purely numeric rows
        ("1", "2", "3"),
        # blank rows
        ("", "", ""),
        # informational row without requirement structure
        ("Hinweis", "Die Preise verstehen sich netto.", ""),
    ],
)
def test_non_requirement_rows_are_ignored(cells: tuple[str, ...]) -> None:
    assert classify_row(cells) is None
