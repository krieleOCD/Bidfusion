"""Pre-send check tests: obvious identifiers block external send by default.

The check is deliberately lightweight and deterministic. It is advisory
operator support, NEVER proof of anonymization — a clean result must not
be presented as an anonymity guarantee, and a warning must never carry
the matched text itself (only its kind and count).
"""

from __future__ import annotations

from bidfusion.rfp_api_pilot.presend_check import (
    PRESEND_CHECK_DISCLAIMER,
    PresendWarning,
    PresendWarningKind,
    check_requirement_text,
)


def kinds(text: str) -> set[PresendWarningKind]:
    return {warning.kind for warning in check_requirement_text(text)}


def test_clean_synthetic_requirement_raises_no_warning() -> None:
    assert (
        check_requirement_text(
            "The service shall support Microsoft Sentinel monitoring on a 24/7 basis "
            "according to ISO 27001 controls."
        )
        == ()
    )


def test_email_addresses_are_flagged_with_a_count() -> None:
    warnings = check_requirement_text(
        "Send questions to procurement@example-corp.com or cto@example-corp.com."
    )
    assert warnings == (PresendWarning(kind=PresendWarningKind.EMAIL_ADDRESS, occurrences=2),)


def test_international_phone_numbers_are_flagged() -> None:
    assert kinds("Call our SOC hotline +49 30 1234 5678 for escalation.") == {
        PresendWarningKind.PHONE_NUMBER
    }
    assert kinds("Reach us via 0049 30 12345678 during transition.") == {
        PresendWarningKind.PHONE_NUMBER
    }


def test_ratios_and_standards_are_not_phone_numbers() -> None:
    assert kinds("24/7 monitoring per ISO 27001 and TLS 1.3 is required.") == set()


def test_customer_identifier_phrases_are_flagged_in_english_and_german() -> None:
    assert kinds("Reference your customer number in every report.") == {
        PresendWarningKind.CUSTOMER_IDENTIFIER
    }
    assert kinds("Die Kundennummer ist in jedem Bericht anzugeben.") == {
        PresendWarningKind.CUSTOMER_IDENTIFIER
    }


def test_warnings_never_carry_the_matched_text() -> None:
    warnings = check_requirement_text("Contact person: jane.doe@example.com")
    assert warnings
    fields = set(PresendWarning.model_fields)
    assert fields == {"kind", "occurrences"}
    dumped = warnings[0].model_dump_json()
    assert "jane" not in dumped
    assert "example.com" not in dumped


def test_disclaimer_says_this_is_not_proof_of_anonymization() -> None:
    lowered = PRESEND_CHECK_DISCLAIMER.lower()
    assert "not proof" in lowered
    assert "anonymi" in lowered
