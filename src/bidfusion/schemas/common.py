"""Shared base types and enums for the BidFusion domain contracts.

All contracts between modules are Pydantic models (schema first, ADR-0005).
The models in this package are the single source of truth; JSON Schemas can
be generated from them on demand (see ``scripts/export_schemas.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

_KeyT = TypeVar("_KeyT")
_ValueT = TypeVar("_ValueT")


class FrozenDict(dict[_KeyT, _ValueT]):
    """Serializable mapping that rejects ordinary in-place mutation."""

    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("frozen mapping does not support mutation")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable  # type: ignore[assignment]
    popitem = _immutable  # type: ignore[assignment]
    setdefault = _immutable  # type: ignore[assignment]
    update = _immutable
    __ior__ = _immutable  # type: ignore[assignment]


def _freeze_mapping[KeyT, ValueT](value: Mapping[KeyT, ValueT]) -> FrozenDict[KeyT, ValueT]:
    return FrozenDict(value)


FrozenMapping = Annotated[
    dict[_KeyT, _ValueT],
    AfterValidator(_freeze_mapping),
]

#: Confidence score, always normalized to [0.0, 1.0].
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]

#: SHA-256 content digest. Hashes bind contracts to exact immutable bytes.
Sha256Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

#: Semantic schema or producer version.
SemanticVersion = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]


class BidfusionModel(BaseModel):
    """Base class for all BidFusion contracts.

    ``extra="forbid"`` makes every contract strict: a producer cannot smuggle
    undeclared fields past a consumer. Contract changes are explicit and
    versioned, never accidental. ``frozen=True`` prevents field reassignment;
    invariant-bearing collections use immutable tuple or mapping types.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Severity(StrEnum):
    """Generic severity scale used by findings and risks."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityVerdict(StrEnum):
    """Verdict of the security gate for a single document.

    MANUAL_REVIEW is pending until an audited release or rejection exists.
    BLOCK and QUARANTINE never enter the normal pipeline.
    """

    ALLOW = "ALLOW"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    QUARANTINE = "QUARANTINE"
    BLOCK = "BLOCK"


class ProcessingStatus(StrEnum):
    """Processing status of a document or a pipeline step."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


class DataClassification(StrEnum):
    """Data classification, drives handling and data-policy decisions.

    ``ANONYMIZED_INTERNAL_PILOT`` labels anonymized real RFP content the
    operator has explicitly cleared for the Orange LLM pilot. It is an
    operator assertion, never an automated claim that anonymization is
    complete or perfect.
    """

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"
    ANONYMIZED_INTERNAL_PILOT = "ANONYMIZED_INTERNAL_PILOT"


class RequirementModality(StrEnum):
    """Strength of the obligation expressed by a requirement."""

    MUST = "MUST"
    SHOULD = "SHOULD"
    MAY = "MAY"
    INFORMATIONAL = "INFORMATIONAL"
    UNKNOWN = "UNKNOWN"


class RequirementCategory(StrEnum):
    """Business domain to which a requirement belongs."""

    TECHNICAL = "TECHNICAL"
    SERVICE = "SERVICE"
    SECURITY = "SECURITY"
    COMPLIANCE = "COMPLIANCE"
    COMMERCIAL = "COMMERCIAL"
    CONTRACTUAL = "CONTRACTUAL"
    SLA = "SLA"
    SUBMISSION = "SUBMISSION"
    OTHER = "OTHER"


class MatchStatus(StrEnum):
    """Result of matching a requirement against the Golden Dataset."""

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    UNKNOWN = "UNKNOWN"
