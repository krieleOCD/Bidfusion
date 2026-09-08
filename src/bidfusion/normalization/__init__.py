"""Domain G - Normalization / fan-in.

Merges extraction results into the Normalized Bid Dataset:
deduplication, conflict detection, consistent IDs, cross references,
provenance and confidence handling."""

from bidfusion.normalization.merge import (
    MVP_EXPECTED_STREAMS,
    NORMALIZATION_COMPONENT_NAME,
    NORMALIZATION_COMPONENT_VERSION,
    merge_extractions,
)

__all__ = [
    "MVP_EXPECTED_STREAMS",
    "NORMALIZATION_COMPONENT_NAME",
    "NORMALIZATION_COMPONENT_VERSION",
    "merge_extractions",
]
