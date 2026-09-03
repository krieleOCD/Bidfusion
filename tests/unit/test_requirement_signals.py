"""Bounded deterministic requirement signals for extractor v0.2.

All example texts are invented synthetic German/English procurement
language. No real customer wording is used.
"""

from __future__ import annotations

import pytest

from bidfusion.extraction.requirements.signals import (
    NegationKind,
    modality_signal,
    negation_signal,
    structural_identifier,
)
from bidfusion.schemas import RequirementModality

# ---------------------------------------------------------------------------
# Structural identifiers (Rule Family B prerequisite)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "token"),
    [
        ("1. Die Plattform muss hochverfuegbar sein.", "1."),
        ("1.2 Der Dienst muss taeglich gesichert werden.", "1.2"),
        ("1.2.3 Die Daten sind zu verschluesseln.", "1.2.3"),
        ("1.2.3.4 Der Zugriff ist zu protokollieren.", "1.2.3.4"),
        ("§ 3 Der Betrieb ist sicherzustellen.", "§ 3"),
        ("§ 3.2 Die Meldung ist unverzueglich vorzunehmen.", "§ 3.2"),
        ("§3 Die Wartung ist einzuhalten.", "§3"),
        ("Abschnitt 4.2 Die Berichte sind vorzulegen.", "Abschnitt 4.2"),
        ("Ziffer 5.3 Die Zertifikate sind nachzuweisen.", "Ziffer 5.3"),
        ("Anforderung 7 Das Portal muss erreichbar sein.", "Anforderung 7"),
        ("Kriterium 12 Beschreiben Sie das Vorgehen.", "Kriterium 12"),
        ("A-12 Vorlage einer aktuellen Zertifizierung als Nachweis.", "A-12"),
        ("K-17 Beschreiben Sie Ihr Eskalationsverfahren?", "K-17"),
    ],
)
def test_structural_identifiers_are_recognized(text: str, token: str) -> None:
    identifier = structural_identifier(text)
    assert identifier is not None
    assert identifier.token == token
    assert identifier.remainder
    assert not identifier.remainder.startswith(token)


@pytest.mark.parametrize(
    "text",
    [
        # dates are never structural identifiers
        "24.08.2026 fand die Ortsbesichtigung statt.",
        "01.02.03 ist als Datum zu lesen.",
        # amounts / thousands separators
        "1.500 Euro betraegt die Gebuehr.",
        # IP addresses (four dotted parts with a part above 9)
        "10.1.2.3 ist die Adresse des Gateways.",
        # CVE identifiers
        "CVE-2026-1234 wurde bereits behoben.",
        # explicit REQ labels belong to rule family A, not B
        "REQ-77 bleibt dem expliziten Label-Extraktor vorbehalten.",
        # a number alone is never a requirement
        "4.2",
        # no identifier at all
        "Die Plattform muss hochverfuegbar sein.",
        # version references inside prose are not paragraph identifiers
        "Die Software nutzt Version 3.2.1 und wird regelmaessig aktualisiert.",
    ],
)
def test_structural_identifier_guards_reject_non_identifiers(text: str) -> None:
    assert structural_identifier(text) is None


# ---------------------------------------------------------------------------
# German + English modality signals (Phase 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Der Dienstleister muss ein Ticketsystem betreiben.",
        "Die Berichte müssen monatlich geliefert werden.",
        "Der Bieter hat ein Konzept zu erstellen.",
        "Die Parteien haben die Termine zu bestätigen.",
        "Ein Notfallplan ist zu erstellen.",
        "Die Protokolle sind zu archivieren.",
        "Die Verfügbarkeit ist sicherzustellen.",
        "Die Werkzeuge sind bereitzustellen.",
        "Ein Nachweis ist vorzulegen.",
        "Die Qualifikation ist nachzuweisen.",
        "Die Frist ist einzuhalten.",
        "Die Vertraulichkeit ist zu gewährleisten.",
        "The supplier must operate a service desk.",
        "The vendor shall provide weekly reports.",
    ],
)
def test_strong_obligation_signals_map_to_must(text: str) -> None:
    assert modality_signal(text) is RequirementModality.MUST


@pytest.mark.parametrize(
    "text",
    [
        "Der Dienstleister soll ein Kundenportal anbieten.",
        "Die Berichte sollen quartalsweise erscheinen.",
        "The service should include a monthly summary.",
    ],
)
def test_requested_signals_map_to_should(text: str) -> None:
    assert modality_signal(text) is RequirementModality.SHOULD


@pytest.mark.parametrize(
    "text",
    [
        "Der Bieter kann ein zusaetzliches Konzept einreichen.",
        "Die Anbieter können eine Teststellung anbieten.",
        "Ein Vor-Ort-Workshop ist optional.",
        "The supplier may offer a workshop.",
    ],
)
def test_optional_signals_map_to_may(text: str) -> None:
    assert modality_signal(text) is RequirementModality.MAY


@pytest.mark.parametrize(
    "text",
    [
        "Die Umgebung umfasst rund vierzig Standorte.",
        "Der Auftraggeber betreibt zwei Rechenzentren.",
        "Im Jahr 2025 gab es acht Vorfälle.",
    ],
)
def test_descriptive_text_has_no_modality_signal(text: str) -> None:
    assert modality_signal(text) is None


def test_hat_zu_signal_does_not_cross_sentence_boundaries() -> None:
    text = "Der Anbieter hat seinen Sitz in Berlin. Die Anfahrt ist zu planen."
    # the second sentence carries the signal, so the text still qualifies …
    assert modality_signal(text) is RequirementModality.MUST
    # … but a bare auxiliary without an infinitive never does
    assert modality_signal("Der Anbieter hat seinen Sitz in Berlin.") is None


# ---------------------------------------------------------------------------
# Negation / exclusion signals (Phase 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Ein eigenes Rechenzentrum muss nicht betrieben werden.",
        "Die Werkzeuge müssen nicht zertifiziert sein.",
        "Eine Vor-Ort-Praesenz ist nicht erforderlich.",
        "Eigene Lizenzen sind nicht erforderlich.",
        "Die Altsysteme sind nicht Bestandteil der Leistung.",
        "Der Endgeraeteschutz ist nicht Gegenstand dieser Ausschreibung.",
        "Schulungen liegen außerhalb des Leistungsumfangs.",
        "Die Migration ist nicht zu erbringen.",
    ],
)
def test_no_obligation_negations_are_detected(text: str) -> None:
    assert negation_signal(text) is NegationKind.NO_OBLIGATION


@pytest.mark.parametrize(
    "text",
    [
        "Der Dienstleister darf keine Subunternehmer ohne Zustimmung einsetzen.",
        "Der Auftragnehmer darf nicht von den Vorgaben abweichen.",
        "Die Daten dürfen nicht außerhalb der EU verarbeitet werden.",
    ],
)
def test_prohibitions_are_detected(text: str) -> None:
    assert negation_signal(text) is NegationKind.PROHIBITION


def test_positive_obligations_are_not_negations() -> None:
    assert negation_signal("Der Dienstleister muss ein Ticketsystem betreiben.") is None
    assert negation_signal("Die Frist ist einzuhalten.") is None
