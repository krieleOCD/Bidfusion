"""Rule families B-E of requirement extractor v0.2 over invented text.

The classifiers are pure text functions; canonical-document wiring is
covered separately in the extractor tests. All content is synthetic.
"""

from __future__ import annotations

import pytest

from bidfusion.extraction.requirements.label_free import (
    RuleFamily,
    assemble_blocks,
    classify_block,
    classify_row,
)
from bidfusion.extraction.support import TextUnit
from bidfusion.schemas import RequirementModality
from bidfusion.schemas.provenance import SourceLocator, SourceReference

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


# ---------------------------------------------------------------------------
# Family F - PERFORMATIVE_OBLIGATION (v0.3): performative present / future /
# passive-agent contractor obligations without an explicit modality keyword
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # performative present with the AN abbreviation
        "Der AN erbringt Managed Security Services zur Optimierung der IT-Sicherheit.",
        # performative present with the full party noun
        "Der Auftragnehmer betreibt die zentrale Plattform im eigenen Rechenzentrum.",
        # future-tense commitment
        "Der Auftragnehmer wird die aufgeführten Aktivitäten eigenverantwortlich ausführen.",
        # verb-first inversion
        "Auf Anforderung stellt der AN der Auftraggeberin alle erforderlichen Daten zur Verfügung.",
        # passive voice with contractor agent
        "Die Runbooks werden durch den AN vorbereitet und gepflegt.",
        "Die Sicherstellung relevanter Informationen erfolgt durch den Auftragnehmer.",
    ],
)
def test_performative_contractor_obligations_are_must_requirements(text: str) -> None:
    detection = classify_block(text)
    assert detection is not None
    assert detection.family is RuleFamily.PERFORMATIVE_OBLIGATION
    assert detection.modality is RequirementModality.MUST


def test_numbered_performative_obligation_is_detected() -> None:
    detection = classify_block(
        "2.2 Der AN erbringt die folgenden Leistungen zur Aufrechterhaltung der IT-Sicherheit."
    )
    assert detection is not None
    assert detection.family is RuleFamily.PERFORMATIVE_OBLIGATION
    assert detection.modality is RequirementModality.MUST


def test_an_abbreviation_with_modality_keyword_is_a_contractual_obligation() -> None:
    detection = classify_block("Der AN muss die Verfügbarkeit von 99,5 Prozent sicherstellen.")
    assert detection is not None
    assert detection.family is RuleFamily.CONTRACTUAL_OBLIGATION
    assert detection.modality is RequirementModality.MUST


@pytest.mark.parametrize(
    "text",
    [
        # the customer's own activities are never contractor obligations
        "Der Auftraggeber betreibt eine primär Windows-basierte IT-Infrastruktur.",
        "Die Abnahme erfolgt durch den Auftraggeber.",
        # indefinite background about an existing provider
        "Ein Dienstleister verantwortet derzeit Basisleistungen im Bereich Server und Storage.",
        # the contractor as a passive recipient (dative) is not a subject
        "Die Auftraggeberin stellt dem AN die erforderlichen Zugänge bereit.",
        # past tense stays background
        "Der Auftragnehmer wurde im Jahr 2020 gegründet.",
        # capitalized AN only: the German word "an" never counts as a party
        "Die Unterlagen sind an der Pforte abzugeben und der Antrag wird an die Stelle geleitet.",
    ],
)
def test_background_and_customer_activity_is_not_a_performative_obligation(text: str) -> None:
    detection = classify_block(text)
    assert detection is None or detection.family is not RuleFamily.PERFORMATIVE_OBLIGATION


def test_negated_performative_statement_is_never_a_positive_obligation() -> None:
    detection = classify_block(
        "Der AN darf personenbezogene Daten nicht außerhalb der EU verarbeiten."
    )
    assert detection is None or detection.modality not in (
        RequirementModality.MUST,
        RequirementModality.SHOULD,
    )


# ---------------------------------------------------------------------------
# Family G - MODAL_STATEMENT (v0.3): normative modality in plain prose
# without a structural identifier or party mention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "modality"),
    [
        (
            "Die Datenverarbeitung und Speicherung muss DSGVO-konform innerhalb der EU erfolgen.",
            RequirementModality.MUST,
        ),
        (
            "Die Berichte sind monatlich in elektronischer Form vorzulegen.",
            RequirementModality.MUST,
        ),
        (
            "Sämtliche Unterlagen sind vollständig auszufüllen.",
            RequirementModality.MUST,
        ),
        (
            "Die Übergabe soll innerhalb von vier Wochen abgeschlossen sein.",
            RequirementModality.SHOULD,
        ),
    ],
)
def test_plain_modal_statements_are_detected(text: str, modality: RequirementModality) -> None:
    detection = classify_block(text)
    assert detection is not None
    assert detection.family is RuleFamily.MODAL_STATEMENT
    assert detection.modality is modality


def test_plain_prohibition_is_preserved_but_not_positive() -> None:
    detection = classify_block(
        "Personenbezogene Daten dürfen nicht außerhalb der EU verarbeitet werden."
    )
    assert detection is not None
    assert detection.family is RuleFamily.MODAL_STATEMENT
    assert detection.modality not in (RequirementModality.MUST, RequirementModality.SHOULD)


@pytest.mark.parametrize(
    "text",
    [
        # a bare possibility without an obligated party stays out
        "Weitere Einzelheiten können der Anlage entnommen werden.",
        # informational prose without modality
        "Die Preise verstehen sich netto zuzüglich Umsatzsteuer.",
        # too short to be a requirement clause
        "Es muss erfolgen.",
        # table-of-contents dot leaders are never requirements
        "1.3 Beschreibung der Leistungspflichten ............................ 3",
        "Die Leistungen müssen erbracht werden ............................. 12",
    ],
)
def test_non_requirement_prose_is_not_a_modal_statement(text: str) -> None:
    detection = classify_block(text)
    assert detection is None or detection.family is not RuleFamily.MODAL_STATEMENT


# ---------------------------------------------------------------------------
# Family H - LIST_SERVICE_ITEM (v0.3): bulleted service/deliverable items and
# activity-assignment rows; structure plus action-noun or passive evidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # bullet + action-noun deliverable
        "◼ Bereitstellung und Betrieb eines Security Operation Centers mit qualifiziertem Team.",
        "▪ Erstellung eines Transitionskonzepts als Gesamtkonzept je Managed Service",
        # bullet + passive specification
        "◼ Security Incidents werden mindestens in drei Kategorien eingeteilt:",
        # customer cooperation duties are still requirement-bearing units
        "▪ Mitwirkungspflichten des Auftraggebers in Bezug auf Dokumentationen und Lizenzen",
        # activity-assignment row with a trailing contractor marker
        "Sammlung, Filterung und Aufbereitung von Threat-Intelligence-Meldungen AN",
    ],
)
def test_list_service_items_are_detected(text: str) -> None:
    detection = classify_block(text)
    assert detection is not None
    assert detection.family is RuleFamily.LIST_SERVICE_ITEM
    assert detection.modality is RequirementModality.UNKNOWN


def test_numbered_heading_with_bulleted_service_item_is_detected() -> None:
    detection = classify_block(
        "4.1.2 Grundsätzliche Anforderungen Projektmanagement "
        "▪ Projektplanung und Vorbereitung in Abstimmung mit dem Auftraggeber"
    )
    assert detection is not None
    assert detection.family is RuleFamily.LIST_SERVICE_ITEM


@pytest.mark.parametrize(
    "text",
    [
        # product and inventory enumerations are facts, never requirements
        "▪ Microsoft Entra ▪ Microsoft Defender ▪ Microsoft 365",
        "▪ FortiGate 100F  (8 Stück) ▪ FortiGate 200F  (2 Stück)",
        "▪ Windows Server   (168 Stück) ▪ Linux Server    (20 Stück)",
        # bare contact-channel nouns carry no action
        "• Telefon • E-Mail • SIEM",
        # a numbered heading alone is not a service item
        "2.2.5 Reporting und Meetings",
        # plain prose with an action noun but neither bullet nor assignment
        "Annahme des Angebots durch den Auftraggeber",
    ],
)
def test_non_service_lists_are_not_detected(text: str) -> None:
    detection = classify_block(text)
    assert detection is None or detection.family is not RuleFamily.LIST_SERVICE_ITEM


# ---------------------------------------------------------------------------
# Family I - PRICED_POSITION (v0.3): service-catalogue rows in price sheets;
# a position code plus a described deliverable is a requirement carrier
# ---------------------------------------------------------------------------


def test_priced_position_row_with_service_code_is_detected() -> None:
    detection = classify_row(
        ("SO-ITSec-001", "Security Operations Center", "M", "1", "1", "1", "0", "0", "0")
    )
    assert detection is not None
    assert detection.family is RuleFamily.PRICED_POSITION
    assert detection.modality is RequirementModality.UNKNOWN
    assert detection.text_cell_index == 1


def test_priced_position_row_with_two_word_description_is_detected() -> None:
    detection = classify_row(("SO-ITSec-005", "Pentest (Tagessatz)", "E", "2", "2", "2"))
    assert detection is not None
    assert detection.family is RuleFamily.PRICED_POSITION


@pytest.mark.parametrize(
    "cells",
    [
        # section/TOC rows with sums are navigation, not positions
        ("2.2.6", "Preismodell", "0", "0", "0"),
        ("4.1.4", "Preismodell", "0", "0", "0"),
        # header rows carry no position code
        ("SK#", "SO#", "Service Objekt", "V", "2026", "2027", "2028"),
        # plain outline rows
        ("3.1", "Servicelevel SOC"),
        # vulnerability identifiers are never position codes
        ("CVE-2026-1234", "Bekannte Schwachstelle im Portal", "1", "2"),
    ],
)
def test_non_position_rows_are_not_priced_positions(cells: tuple[str, ...]) -> None:
    detection = classify_row(cells)
    assert detection is None or detection.family is not RuleFamily.PRICED_POSITION


# ---------------------------------------------------------------------------
# Family I continued (v0.3): position codes inside flattened block text —
# PDF-rendered catalogue tables become paragraph lines, not rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        (
            "2.2.6 Preismodell Objekt-ID Service Objekt Verrechnung "
            "SO-ITSec-001 Security Operations Center M SO-ITSec-002 Standard Paket Forensik E"
        ),
        "SO-ITSec-010 SIEM Anbindung Microsoft 365 M SO-ITSec-011 SIEM Anbindung Entra M",
    ],
)
def test_flattened_position_code_blocks_are_detected(text: str) -> None:
    detection = classify_block(text)
    assert detection is not None
    assert detection.family is RuleFamily.PRICED_POSITION
    assert detection.modality is RequirementModality.UNKNOWN


@pytest.mark.parametrize(
    "text",
    [
        # hyphenated German compounds are never position codes
        "Der Wechsel auf die Blau-Grün-Deployment-Strategie ist geplant.",
        # norm references are standards, not catalogue positions
        "Die Zertifizierung nach ISO-27001 ist nachzuweisen.",
        # vulnerability identifiers stay excluded
        "CVE-2026-1234 wurde bereits behoben.",
    ],
)
def test_compounds_and_norm_references_are_not_priced_positions(text: str) -> None:
    detection = classify_block(text)
    assert detection is None or detection.family is not RuleFamily.PRICED_POSITION


# ---------------------------------------------------------------------------
# Family J - EXCLUSION_CONDITION (v0.3): binding invalidity/exclusion
# formalities of the tender procedure, phrased negatively
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Die Übermittlung des Angebots auf anderem Weg ist nicht zulässig.",
        "Verspätet eingehende Angebote werden nicht berücksichtigt.",
        "Allgemeine Geschäftsbedingungen des Bieters finden keine Anwendung.",
        "Eine Berufung auf eigene Allgemeine Geschäftsbedingungen führt zum Ausschluss.",
        "Nebenangebote sind nicht zugelassen.",
    ],
)
def test_exclusion_conditions_are_detected(text: str) -> None:
    detection = classify_block(text)
    assert detection is not None
    assert detection.family is RuleFamily.EXCLUSION_CONDITION
    assert detection.modality is RequirementModality.UNKNOWN


@pytest.mark.parametrize(
    "text",
    [
        "Der Anhang findet auf alle Bestellungen Anwendung.",
        "Die entstandenen Kosten werden im Preisblatt berücksichtigt.",
        "Zulässig sind alle marktüblichen Verfahren.",
    ],
)
def test_positive_procedure_prose_is_not_an_exclusion_condition(text: str) -> None:
    detection = classify_block(text)
    assert detection is None or detection.family is not RuleFamily.EXCLUSION_CONDITION


# ---------------------------------------------------------------------------
# Block assembly (v0.3): line-wrapped PDF clauses without punctuation must
# survive as one block instead of being truncated mid-sentence
# ---------------------------------------------------------------------------


def _line_unit(text: str, index: int) -> TextUnit:
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


def test_wrapped_clause_of_ten_lines_stays_one_block() -> None:
    lines = [
        f"Fortsetzung {index} des umgebrochenen Vertragssatzes ohne Satzzeichen"
        for index in range(9)
    ]
    lines.append("und ist quartalsweise zu aktualisieren.")
    blocks = assemble_blocks(tuple(_line_unit(text, index) for index, text in enumerate(lines)))
    assert len(blocks) == 1
    assert len(blocks[0].units) == 10


def test_tender_reference_codes_in_titles_are_not_priced_positions() -> None:
    detection = classify_block(
        "Synthetic RFP BF-2026-DEMO - Invitation to Tender Customer: Example Testing Corp"
    )
    assert detection is None or detection.family is not RuleFamily.PRICED_POSITION


# ---------------------------------------------------------------------------
# Family K - PROCEDURE_STATEMENT (v0.3): binding procedure/legal statements
# of the award process and contract mechanics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # awarding-entity future commitment
        "Der Auftraggeber wird die Punktzahl anhand der niedrigsten Angebotssumme berechnen.",
        # reservation clause, independent of the reserving subject
        "Grundsätzlich behält sich die Vergabestelle ein generelles Auditrecht vor.",
        # numbered passive procedure statement
        (
            "15. Umgang mit Daten Die mitgeteilten personenbezogenen Daten werden "
            "für das Vergabeverfahren verarbeitet und gespeichert."
        ),
        # numbered constraint participle
        (
            "9.2 Die Summe aller Vertragsstrafen ist auf fünf Prozent der "
            "Jahresbruttoauftragssumme beschränkt."
        ),
    ],
)
def test_procedure_statements_are_detected(text: str) -> None:
    detection = classify_block(text)
    assert detection is not None
    assert detection.family is RuleFamily.PROCEDURE_STATEMENT
    assert detection.modality is RequirementModality.UNKNOWN


@pytest.mark.parametrize(
    "text",
    [
        # present-tense customer background stays out
        "Der Auftraggeber betreibt eine primär Windows-basierte IT-Infrastruktur.",
        # unanchored passive background without an identifier stays out
        "Die bestehende Umgebung wird derzeit von zwei Dienstleistern betreut.",
        # numbered sizing facts stay facts
        "2.1 Die Umgebung umfasst 1.500 Arbeitsplaetze an 12 Standorten.",
    ],
)
def test_background_prose_is_not_a_procedure_statement(text: str) -> None:
    detection = classify_block(text)
    assert detection is None or detection.family is not RuleFamily.PROCEDURE_STATEMENT
