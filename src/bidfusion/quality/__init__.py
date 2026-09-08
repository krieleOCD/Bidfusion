"""Domain H - Quality assurance gate.

Checks parsing, OCR and extraction quality, coverage, conflicts and
confidence. Prefers UNKNOWN / UNCLEAR / REQUIRES_REVIEW over
invented information."""

from bidfusion.quality.coverage import ExtractionCoverage, compute_extraction_coverage
from bidfusion.quality.gate import (
    QUALITY_GATE_ID,
    QUALITY_GATE_NAME,
    QUALITY_GATE_VERSION,
    ParsedDocumentQuality,
    QualityGateReport,
    QualityGateStatus,
    QualitySignal,
    UnprocessedDocument,
    evaluate_quality,
    require_evaluated_artifacts,
)
from bidfusion.quality.review_package import (
    REVIEW_PACKAGE_NOTICE,
    REVIEW_PACKAGE_SCHEMA_VERSION,
    DetectedItem,
    ReviewPackage,
    build_review_package,
    render_review_markdown,
)

__all__ = [
    "QUALITY_GATE_ID",
    "QUALITY_GATE_NAME",
    "QUALITY_GATE_VERSION",
    "REVIEW_PACKAGE_NOTICE",
    "REVIEW_PACKAGE_SCHEMA_VERSION",
    "DetectedItem",
    "ExtractionCoverage",
    "ParsedDocumentQuality",
    "QualityGateReport",
    "QualityGateStatus",
    "QualitySignal",
    "ReviewPackage",
    "UnprocessedDocument",
    "build_review_package",
    "compute_extraction_coverage",
    "evaluate_quality",
    "render_review_markdown",
    "require_evaluated_artifacts",
]
