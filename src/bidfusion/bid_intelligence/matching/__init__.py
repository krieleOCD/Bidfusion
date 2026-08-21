"""Capability matching between extracted RFP requirements and knowledge.

First delivered slice: the deterministic bridge from extracted RFP
requirements to the Golden Knowledge MTD pilot — adapter, read-only
claims snapshot, and assessment service. Every result is a candidate
that requires human review; no evidence means no positive capability
claim. Embeddings may one day support retrieval; they are not the
matching engine, and nothing in this package calls a model.
"""

from bidfusion.bid_intelligence.matching.adapter import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    AdaptedRequirement,
    adapt_requirement,
)
from bidfusion.bid_intelligence.matching.assessment import assess_requirements
from bidfusion.bid_intelligence.matching.claims_access import (
    ClaimsSnapshot,
    load_claims_snapshot,
)
from bidfusion.bid_intelligence.matching.contracts import (
    ASSESSMENT_VERSION,
    KnowledgeAssessmentResult,
    KnowledgeStoreState,
    RequirementKnowledgeAssessment,
    RequirementLanguage,
)

__all__ = [
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "ASSESSMENT_VERSION",
    "AdaptedRequirement",
    "ClaimsSnapshot",
    "KnowledgeAssessmentResult",
    "KnowledgeStoreState",
    "RequirementKnowledgeAssessment",
    "RequirementLanguage",
    "adapt_requirement",
    "assess_requirements",
    "load_claims_snapshot",
]
