"""Append-only local persistence for requirement assessment reviews.

Reviews are bid/run-side artifacts. They are stored under one private
root *beside* the pipeline run directory — never inside it, because the
run's integrity manifest is sealed at pipeline time and must keep
verifying; and never under ``runtime/golden_dataset/``, because reviews
are not golden knowledge.

Layout under the root::

    <assessment_id>/review-v0001.json
    <assessment_id>/review-v0002.json
    ...

Every file name is derived from validated contract fields only — the
assessment identifier is checked against its strict pattern before any
path is built, so no request-controlled value can shape a path. Writes
are atomic and private via :mod:`bidfusion.shared.secure_io` and an
existing version file is never overwritten. Loading fails closed: a
file that does not validate, or whose name disagrees with its content,
refuses the whole load rather than silently dropping records.
"""

from __future__ import annotations

import re
from pathlib import Path

from bidfusion.bid_intelligence.review.contracts import RequirementAssessmentReview
from bidfusion.shared.secure_io import ensure_private_directory, write_private_text

_ASSESSMENT_DIR = re.compile(r"^RKA-[0-9a-f]{12}$")
_REVIEW_FILE = re.compile(r"^review-v(\d{4})\.json$")

#: Static, content-free failure texts. Never interpolate review content,
#: identifiers, or paths into them.
_CONFLICT_MESSAGE = "a review with this version already exists and is never overwritten"
_INTEGRITY_MESSAGE = "the stored review records could not be validated"


class ReviewStoreConflictError(RuntimeError):
    """An existing review version would have been overwritten."""


class ReviewStoreIntegrityError(RuntimeError):
    """Stored review records are inconsistent; the load is refused."""


class RunReviewStore:
    """Read/append review records below one private local root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def append_review(self, review: RequirementAssessmentReview) -> None:
        """Persist one new review version atomically; never overwrite."""
        directory = self._root / review.assessment_id
        ensure_private_directory(self._root)
        ensure_private_directory(directory, root=self._root)
        path = directory / f"review-v{review.review_version:04d}.json"
        if path.exists():
            raise ReviewStoreConflictError(_CONFLICT_MESSAGE)
        write_private_text(path, review.model_dump_json(indent=2), root=self._root)

    def read_reviews(self) -> tuple[RequirementAssessmentReview, ...]:
        """Every stored review, validated, in (assessment, version) order.

        An absent root is an empty store. Any unparseable record, or a
        record whose file location disagrees with its own content,
        fails the whole load closed.
        """
        if not self._root.is_dir():
            return ()
        reviews: list[RequirementAssessmentReview] = []
        for directory in sorted(self._root.iterdir()):
            if not directory.is_dir() or not _ASSESSMENT_DIR.match(directory.name):
                raise ReviewStoreIntegrityError(_INTEGRITY_MESSAGE)
            for path in sorted(directory.iterdir()):
                match = _REVIEW_FILE.match(path.name)
                if not path.is_file() or match is None:
                    raise ReviewStoreIntegrityError(_INTEGRITY_MESSAGE)
                try:
                    review = RequirementAssessmentReview.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
                except ValueError as failure:
                    raise ReviewStoreIntegrityError(_INTEGRITY_MESSAGE) from failure
                if review.assessment_id != directory.name or review.review_version != int(
                    match.group(1)
                ):
                    raise ReviewStoreIntegrityError(_INTEGRITY_MESSAGE)
                reviews.append(review)
        return tuple(reviews)
