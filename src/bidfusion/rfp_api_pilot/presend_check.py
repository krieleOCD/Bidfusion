"""Deterministic pre-send check for obvious identifiers in requirement text.

Advisory pilot safety only: a small set of conservative patterns flags
obvious e-mail addresses, internationally prefixed phone numbers, and
explicit customer/account identifier phrases before a requirement is
sent to the Orange Proxy. A triggered warning blocks the external send
unless the operator explicitly overrides per the labeled pilot policy.

This check is NOT an anonymizer and a clean result is NOT proof of
anonymization — anonymization remains an explicit operator assertion.
Warnings carry only a kind and a count, never the matched text.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import Field

from bidfusion.schemas.common import BidfusionModel

PRESEND_CHECK_DISCLAIMER = (
    "Deterministic pre-send check: advisory pattern scan for obvious "
    "identifiers only. A clean result is NOT proof of anonymization; the "
    "operator's explicit anonymization assertion remains authoritative."
)


class PresendWarningKind(StrEnum):
    """Closed vocabulary of detectable obvious identifiers."""

    EMAIL_ADDRESS = "email_address"
    PHONE_NUMBER = "phone_number"
    CUSTOMER_IDENTIFIER = "customer_identifier"


class PresendWarning(BidfusionModel):
    """One triggered identifier kind with its occurrence count.

    Deliberately content-free: the matched text never leaves the check,
    so warnings are safe to persist and print.
    """

    kind: PresendWarningKind
    occurrences: int = Field(ge=1)


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

#: Conservative: only internationally prefixed numbers (+ or 00) with at
#: least eight digits count, so ratios ("24/7"), standards ("ISO 27001"),
#: and version numbers are never flagged. Plain national numbers are a
#: known gap — under-flagging is acceptable for an advisory check that
#: must not create false confidence.
_PHONE = re.compile(r"(?<![\w+])(?:\+|00)\d(?:[\s\-/().]?\d){7,}(?!\w)")

_CUSTOMER_IDENTIFIER = re.compile(
    r"\b(?:customer|account|client)[\s-]?(?:id|number|no)\b|\bkunden-?nummer\b",
    re.IGNORECASE,
)

_PATTERNS: tuple[tuple[PresendWarningKind, re.Pattern[str]], ...] = (
    (PresendWarningKind.EMAIL_ADDRESS, _EMAIL),
    (PresendWarningKind.PHONE_NUMBER, _PHONE),
    (PresendWarningKind.CUSTOMER_IDENTIFIER, _CUSTOMER_IDENTIFIER),
)


def check_requirement_text(text: str) -> tuple[PresendWarning, ...]:
    """Scan one requirement text; return content-free warnings in kind order."""
    warnings: list[PresendWarning] = []
    for kind, pattern in _PATTERNS:
        occurrences = len(pattern.findall(text))
        if occurrences:
            warnings.append(PresendWarning(kind=kind, occurrences=occurrences))
    return tuple(warnings)
