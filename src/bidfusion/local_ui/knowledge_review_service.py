"""Submission path for human reviews of requirement assessments.

The only mutation in the knowledge-assessment experience, kept as
narrow as the pages around it: validate everything server-side, write
one immutable review record through the bid-side review store, and
touch nothing else. The golden store is read (to recompute the current
assessments deterministically) and never written; no golden claim
changes state here.

Every authoritative value is recomputed on the server from the run's
integrity-verified artifacts and the current knowledge snapshot. The
posted assessment digest is used only to detect staleness between
render and submit — a mismatch means the assessment changed underneath
the reviewer, and the submission is refused instead of silently applied
to different content.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from bidfusion.bid_intelligence.review import (
    MAX_RATIONALE_LENGTH,
    MAX_REVIEWER_LENGTH,
    RequirementAssessmentReview,
    ReviewDecision,
    ReviewStoreConflictError,
    RunReviewStore,
    assessment_digest,
    record_requirement_assessment_review,
)
from bidfusion.local_ui.knowledge_assessment_service import (
    compute_assessment_result,
    reviews_root_for,
)
from bidfusion.local_ui.registry import RunRecord


class ReviewRequestError(ValueError):
    """The submitted review input is invalid; the message is static."""


class ReviewConflictError(RuntimeError):
    """The review targets a stale or unavailable assessment state."""


_UNKNOWN_ASSESSMENT = "The submitted review does not match any assessment of this run."
_STALE_ASSESSMENT = (
    "The assessment changed since this page was loaded. Reload the page and "
    "review the current assessment; no decision was recorded."
)
_BAD_DECISION = "The submitted review decision is not one of the allowed values."
_BAD_REVIEWER = "A review requires a reviewer name within the allowed length."
_BAD_RATIONALE = "The review rationale exceeds the allowed length."
_REVIEWS_UNAVAILABLE = (
    "The stored review records for this run could not be read; no new review "
    "is accepted until they validate again."
)
_CONCURRENT_REVIEW = (
    "Another review for this assessment was recorded at the same moment. "
    "Reload the page to see the current review state."
)


def submit_review(
    record: RunRecord,
    store_root: Path,
    form: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> RequirementAssessmentReview | None:
    """Validate one posted review and append it to the run's review store.

    Returns ``None`` when the run does not permit assessment at all (the
    caller renders its usual not-found state). Raises
    :class:`ReviewRequestError` for invalid input and
    :class:`ReviewConflictError` for stale or unreadable state. May
    raise :class:`bidfusion.local_ui.artifacts.ArtifactAccessError` when
    the run's integrity re-check fails — no review is ever recorded for
    an integrity-invalid run.
    """
    result = compute_assessment_result(record, store_root)
    if result is None:
        return None

    posted_id = form.get("assessment_id", "")
    assessment = next(
        (item for item in result.assessments if item.assessment_id == posted_id), None
    )
    if assessment is None:
        raise ReviewRequestError(_UNKNOWN_ASSESSMENT)

    posted_digest = form.get("assessment_digest", "")
    if posted_digest != assessment_digest(assessment):
        raise ReviewConflictError(_STALE_ASSESSMENT)

    try:
        decision = ReviewDecision(form.get("decision", ""))
    except ValueError as failure:
        raise ReviewRequestError(_BAD_DECISION) from failure

    reviewer = form.get("reviewer", "").strip()
    if not reviewer or len(reviewer) > MAX_REVIEWER_LENGTH:
        raise ReviewRequestError(_BAD_REVIEWER)

    rationale = form.get("rationale", "").strip() or None
    if rationale is not None and len(rationale) > MAX_RATIONALE_LENGTH:
        raise ReviewRequestError(_BAD_RATIONALE)

    store = RunReviewStore(reviews_root_for(record))
    try:
        existing = store.read_reviews()
    except Exception as failure:  # noqa: BLE001 - unreadable store must refuse, not raise raw
        raise ReviewConflictError(_REVIEWS_UNAVAILABLE) from failure

    review = record_requirement_assessment_review(
        assessment,
        decision=decision,
        reviewer=reviewer,
        rationale=rationale,
        reviewed_at=now if now is not None else datetime.now(UTC),
        run_id=record.summary.run_id,
        existing=existing,
    )
    try:
        store.append_review(review)
    except ReviewStoreConflictError as failure:
        raise ReviewConflictError(_CONCURRENT_REVIEW) from failure
    return review
