"""Export the Pydantic domain schemas as JSON Schema files.

The Pydantic models in ``src/bidfusion/schemas`` are the single source of
truth (ADR-0005). This script derives JSON Schemas from them for consumers
outside the Python codebase. Generated files are derived artifacts - review
them in a diff, never edit them by hand.

Usage: ``python scripts/export_schemas.py [output_dir]``
Default output directory: ``schemas/`` in the repository root.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from bidfusion import schemas

EXPORTED_MODELS: list[type[BaseModel]] = [
    schemas.ArtifactReference,
    schemas.ArtifactEnvelope,
    schemas.Bid,
    schemas.Opportunity,
    schemas.BidDecision,
    schemas.Actor,
    schemas.Assignment,
    schemas.ProcessingRun,
    schemas.Document,
    schemas.DocumentInventoryEntry,
    schemas.SecurityResult,
    schemas.SecurityClearedArtifact,
    schemas.SourceReference,
    schemas.CanonicalDocument,
    schemas.Requirement,
    schemas.Deadline,
    schemas.Entity,
    schemas.Formality,
    schemas.Scope,
    schemas.CommercialFinding,
    schemas.ExtractedSecurityFinding,
    schemas.ComplianceFinding,
    schemas.ExtractionResult,
    schemas.RequirementExtractionResult,
    schemas.DeadlineExtractionResult,
    schemas.EntityExtractionResult,
    schemas.FormalityExtractionResult,
    schemas.ScopeExtractionResult,
    schemas.CommercialExtractionResult,
    schemas.SecurityExtractionResult,
    schemas.ComplianceExtractionResult,
    schemas.NormalizedBidDataset,
    schemas.QualityFinding,
    schemas.HumanReview,
    schemas.WorkingPackage,
    schemas.ComplianceMatrix,
    schemas.BusinessReview,
    schemas.Approval,
    schemas.KnowledgeItem,
    schemas.ModelRequirements,
    schemas.LLMRequest,
    schemas.LLMResponse,
    schemas.OCRRequest,
    schemas.OCRResult,
    schemas.ProviderConfig,
    # Bid Intelligence contracts (prepared, not implemented)
    schemas.Capability,
    schemas.CapabilityMatch,
    schemas.CoverageResult,
    schemas.Gap,
]


def main() -> int:
    """Write one JSON Schema file per exported model."""
    default_out = Path(__file__).resolve().parent.parent / "schemas"
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else default_out
    out_dir.mkdir(parents=True, exist_ok=True)
    for model in EXPORTED_MODELS:
        path = out_dir / f"{model.__name__}.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
