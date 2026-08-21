"""Deterministic filename classification for golden knowledge sources.

Classification never opens a file: everything here derives from the
filename alone, through fixed, documented tables. Where a name does not
match a table entry the result is ``unknown`` — no semantic guessing, no
content inspection, no model calls. The full mapping is documented in
``docs/development/golden-dataset-mtd-pilot.md`` and must be changed in
both places or not at all.

Ordering matters and is deliberate:

- technology tokens are checked most-specific-first, so "Microsoft
  Sentinel" wins over the bare "Microsoft" fallback and "XSIAM" wins
  over "Cortex" (a Cortex-to-XSIAM migration document is classified by
  its target platform);
- "Managed Threat Response" is both a service family and, for this
  pilot, its own technology bucket — isolation documents carry
  ``[isolation]`` in their names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

from bidfusion.golden_dataset.contracts import DocumentType, ServiceFamily, Technology

#: Filename prefix (before the first dash) to document family. ``SR`` is
#: deliberately absent: it is not an agreed family, so it stays unknown.
PREFIX_DOCUMENT_TYPES: dict[str, DocumentType] = {
    "SD": DocumentType.SERVICE_DESCRIPTION,
    "QA": DocumentType.QA_TECHNOLOGY_GUIDANCE,
    "SAP": DocumentType.SERVICE_ACTIVATION_PROCEDURE,
    "SI": DocumentType.SERVICE_INSTRUCTION,
    "CL": DocumentType.CHECKLIST,
    "CP": DocumentType.CUSTOMER_PRESENTATION,
    "DS": DocumentType.DATASHEET,
    "OV": DocumentType.OVERVIEW,
    "PO": DocumentType.PRICING_COMMERCIAL,
    "OE": DocumentType.OFFERING_ESTIMATE,
    "OH": DocumentType.OPERATIONAL_HANDBOOK,
    "SC": DocumentType.SERVICE_CATALOGUE,
    "SOW": DocumentType.STATEMENT_OF_WORK,
}

#: Ordered (token, technology) table; first casefolded substring match
#: wins. "microsoft 365 defender" is the historical name of Defender XDR.
_TECHNOLOGY_TOKENS: tuple[tuple[str, Technology], ...] = (
    ("microsoft defender xdr", Technology.MICROSOFT_DEFENDER_XDR),
    ("microsoft 365 defender", Technology.MICROSOFT_DEFENDER_XDR),
    ("defender xdr", Technology.MICROSOFT_DEFENDER_XDR),
    ("microsoft sentinel", Technology.MICROSOFT_SENTINEL),
    ("sentinel", Technology.MICROSOFT_SENTINEL),
    ("xsiam", Technology.PALO_ALTO_XSIAM),
    ("cortex", Technology.PALO_ALTO_CORTEX_XDR),
    ("palo alto", Technology.PALO_ALTO_CORTEX_XDR),
    ("paloaltonetworks", Technology.PALO_ALTO_CORTEX_XDR),
    ("splunk", Technology.SPLUNK),
    ("vectra", Technology.VECTRA),
    ("ebonding", Technology.ITSM_EBONDING),
    ("[isolation]", Technology.MANAGED_THREAT_RESPONSE),
    ("threat response", Technology.MANAGED_THREAT_RESPONSE),
    ("microsoft", Technology.MICROSOFT_GENERIC),
    ("managed threat detection", Technology.GENERIC_MTD),
    ("mtd", Technology.GENERIC_MTD),
)

#: Ordered (token, family) table; first casefolded substring match wins.
_SERVICE_FAMILY_TOKENS: tuple[tuple[str, ServiceFamily], ...] = (
    ("threat response", ServiceFamily.MANAGED_THREAT_RESPONSE),
    ("[isolation]", ServiceFamily.MANAGED_THREAT_RESPONSE),
    ("ebonding", ServiceFamily.EBONDING_ITSM),
    ("managed threat detection", ServiceFamily.MANAGED_THREAT_DETECTION),
    ("mtd", ServiceFamily.MANAGED_THREAT_DETECTION),
)

#: Version markers observed in the naming scheme: ``v2026.2.1``,
#: ``v.2.1``, ``v0.x``, and a bare trailing ``3.1``. The ``x`` literal is
#: kept as written; nothing is normalized into an invented number.
_MARKED_VERSION = re.compile(r"\bv\.?\s*(\d+(?:\.(?:\d+|x))+)\b", re.IGNORECASE)
_TRAILING_VERSION = re.compile(r"(?:^|\s)(\d+(?:\.\d+)+)\s*$")

_PREFIX = re.compile(r"^([A-Za-z]{2,4})\s*-")


@dataclass(frozen=True, slots=True)
class FilenameClassification:
    """Deterministic classification of one source filename."""

    service_family: ServiceFamily
    technology: Technology
    document_type: DocumentType
    version: str | None


def classify_filename(filename: str) -> FilenameClassification:
    """Classify one filename through the fixed tables above."""
    stem = PurePath(filename).stem
    folded = stem.casefold()
    return FilenameClassification(
        service_family=_first_match(folded, _SERVICE_FAMILY_TOKENS, ServiceFamily.UNKNOWN),
        technology=_first_match(folded, _TECHNOLOGY_TOKENS, Technology.UNKNOWN),
        document_type=_document_type(stem, folded),
        version=_version(stem),
    )


def _document_type(stem: str, folded: str) -> DocumentType:
    prefix = _PREFIX.match(stem)
    if prefix is not None:
        return PREFIX_DOCUMENT_TYPES.get(prefix.group(1).upper(), DocumentType.UNKNOWN)
    if "statement of work" in folded:
        return DocumentType.STATEMENT_OF_WORK
    return DocumentType.UNKNOWN


def _first_match[EnumT](
    folded: str,
    table: tuple[tuple[str, EnumT], ...],
    fallback: EnumT,
) -> EnumT:
    for token, value in table:
        if token in folded:
            return value
    return fallback


def _version(stem: str) -> str | None:
    marked = _MARKED_VERSION.search(stem)
    if marked is not None:
        return marked.group(1)
    trailing = _TRAILING_VERSION.search(stem)
    if trailing is not None:
        return trailing.group(1)
    return None
