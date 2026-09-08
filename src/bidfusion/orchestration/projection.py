"""Run-independent semantic projection of one pipeline run directory (Z6).

Documented reporting contract: two runs over identical inputs and
configuration — but different real clock values — must agree on this
projection. It is production code, not a test helper, so operators and
regression tooling share one authoritative definition of "semantically
identical runs".

The projection normalizes **only known run-scoped fields**, addressed by
their JSON keys — never by globally pattern-matching values:

- run identifiers (``run_id``, ``processing_run_id``),
- run-scoped lifecycle timestamps (``created_at``, ``updated_at``,
  ``generated_at``, ``completed_at``, ``started_at``, ``finished_at``,
  ``evaluated_at``, ``assessed_at``, ``decided_at``),
- run-scoped artifact identifiers (``artifact_id``,
  ``canonical_artifact_id``; the run-independent sequence number is kept),
- content hashes of *sealed* (non-raw) artifacts, whose canonical payloads
  embed run timestamps by design. The payload files themselves are part of
  the projection and are compared field by field, so masking these hashes
  cannot hide a semantic difference.

Everything else — business deadlines, source quotes, extracted texts,
counts, warnings, decisions, and all other authoritative payload content —
is preserved verbatim. Both the authoritative ``*.payload.json`` files and
the derived views are projected; only the integrity manifest (whole-file
digests, run-dependent by definition) is excluded.

Markdown outputs are normalized only on **known, renderer-controlled
metadata lines** (``- Generated:``, ``- Run:``, ``- Source dataset:``) —
each anchored to the start of a line the renderers themselves emit. There
is no global replacement of ``RUN-``/``ART-``-shaped tokens: free document
text, business timestamps (deadline tables, detected deadlines), quotes,
and counts pass through unchanged. The JSON payload projection remains the
authoritative semantic comparison; the Markdown projection is a derived
view of controlled metadata plus verbatim content.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MANIFEST_FILENAME = "integrity-manifest.json"

RUN_ID_KEYS = frozenset({"run_id", "processing_run_id"})
RUN_SCOPED_TIMESTAMP_KEYS = frozenset(
    {
        "created_at",
        "updated_at",
        "generated_at",
        "completed_at",
        "started_at",
        "finished_at",
        "evaluated_at",
        "assessed_at",
        "decided_at",
    }
)
ARTIFACT_ID_KEYS = frozenset({"artifact_id", "canonical_artifact_id", "dataset_artifact_id"})

_ARTIFACT_ID = re.compile(r"^ART-\d{8}-\d{12}(\d{6})$")
#: Renderer-controlled Markdown metadata lines (and nothing else).
_MARKDOWN_GENERATED_LINE = re.compile(r"^- Generated: .+$", re.MULTILINE)
_MARKDOWN_RUN_LINE = re.compile(r"^- Run: .+$", re.MULTILINE)
_MARKDOWN_SOURCE_DATASET_LINE = re.compile(r"^- Source dataset: .+$", re.MULTILINE)

RUN_ID_PLACEHOLDER = "RUN-NORM"
TIMESTAMP_PLACEHOLDER = "TS-NORM"
SEALED_HASH_PLACEHOLDER = "SEALED-HASH"


def run_independent_projection(run_directory: Path) -> dict[str, Any]:
    """Project one run directory onto its run-independent semantic content."""
    projection: dict[str, Any] = {}
    for path in sorted(run_directory.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(run_directory).as_posix()
        if relative == MANIFEST_FILENAME:
            continue
        if relative.endswith(".json"):
            projection[relative] = _normalize_json(json.loads(path.read_text()))
        elif relative.endswith(".md"):
            projection[relative] = _normalize_markdown(path.read_text())
        else:
            projection[relative] = path.read_bytes().hex()
    return projection


def _normalize_json(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        normalized = {
            item_key: _normalize_json(item, key=item_key) for item_key, item in value.items()
        }
        if (
            "artifact_type" in normalized
            and "content_hash" in normalized
            and normalized.get("artifact_type") != "raw_document"
        ):
            # Sealed payloads embed run timestamps, so their hashes are
            # run-dependent by design; raw-document hashes must stay equal.
            # The sealed payload files themselves are compared field-wise.
            normalized["content_hash"] = SEALED_HASH_PLACEHOLDER
        return normalized
    if isinstance(value, list):
        return [_normalize_json(item, key=key) for item in value]
    if isinstance(value, str) and key is not None:
        if key in RUN_ID_KEYS:
            return RUN_ID_PLACEHOLDER
        if key in RUN_SCOPED_TIMESTAMP_KEYS:
            return TIMESTAMP_PLACEHOLDER
        if key in ARTIFACT_ID_KEYS:
            return _normalize_artifact_id(value)
    return value


def _normalize_artifact_id(value: str) -> str:
    match = _ARTIFACT_ID.fullmatch(value)
    if match is None:
        return value
    return f"ART-NORM-{match.group(1)}"


def _normalize_markdown(text: str) -> str:
    text = _MARKDOWN_GENERATED_LINE.sub(f"- Generated: {TIMESTAMP_PLACEHOLDER}", text)
    text = _MARKDOWN_RUN_LINE.sub(f"- Run: {RUN_ID_PLACEHOLDER}", text)
    return _MARKDOWN_SOURCE_DATASET_LINE.sub("- Source dataset: ART-NORM", text)
