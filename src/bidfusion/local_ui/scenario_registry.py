"""Loading the curated demonstration scenarios, strictly and once.

Scenario files are data, not code: swapping their content is an edit to
a JSON file, never a change to a template or a route. This module is the
only place that reads them, and it reads only from the one fixture
directory below the repository — a scenario key can never become a path.

Every file is validated against :mod:`bidfusion.local_ui.preview_schemas`
before it is cached, so a malformed scenario fails at load time rather
than half-rendering somewhere in a page.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ValidationError

from bidfusion.local_ui.preview_schemas import (
    SCENARIO_SCHEMA_VERSION,
    ResponseLifecycle,
    Scenario,
)

_SCENARIO_FILENAME = "scenario.json"
_LIFECYCLE_FILENAME = "response_lifecycle.json"

#: The demonstration scenarios, in the order the interface offers them.
#: Fixed here rather than discovered from the filesystem: a directory
#: appearing on disk must never silently become a product surface.
SCENARIO_KEYS: tuple[str, ...] = (
    "clean-opportunity",
    "high-risk-opportunity",
    "competitive-opportunity",
)

DEFAULT_SCENARIO_KEY = SCENARIO_KEYS[0]


class ScenarioError(RuntimeError):
    """A scenario could not be loaded. The message is static and safe."""


OPERATOR_SAFE_SCENARIO_MESSAGE = (
    "A demonstration scenario could not be loaded. No preview data is available for it."
)


def _demo_root() -> Path:
    """The one directory demonstration data may ever be read from."""
    return Path(__file__).resolve().parents[3] / "fixtures" / "product_demo"


def available_keys() -> tuple[str, ...]:
    """Every scenario key the interface offers, in display order."""
    return SCENARIO_KEYS


@cache
def load_scenario(key: str) -> Scenario:
    """The validated scenario stored under ``key``.

    Only the keys in :data:`SCENARIO_KEYS` are accepted; anything else
    raises :class:`ScenarioError` before any path is built from it, so a
    request parameter can never reach the filesystem. A file that is
    missing, unreadable, not valid JSON, or does not satisfy the schema
    raises the same error with the same static message.
    """
    if key not in SCENARIO_KEYS:
        raise ScenarioError(OPERATOR_SAFE_SCENARIO_MESSAGE)
    path = _demo_root() / "scenarios" / key / _SCENARIO_FILENAME
    scenario = _load(path, Scenario)
    if scenario.schema_version != SCENARIO_SCHEMA_VERSION or scenario.key != key:
        raise ScenarioError(OPERATOR_SAFE_SCENARIO_MESSAGE)
    return scenario


@cache
def load_response_lifecycle() -> ResponseLifecycle:
    """The validated response lifecycle shared by every scenario."""
    lifecycle = _load(_demo_root() / _LIFECYCLE_FILENAME, ResponseLifecycle)
    if lifecycle.schema_version != SCENARIO_SCHEMA_VERSION:
        raise ScenarioError(OPERATOR_SAFE_SCENARIO_MESSAGE)
    return lifecycle


def all_scenarios() -> tuple[Scenario, ...]:
    """Every offered scenario, validated, in display order."""
    return tuple(load_scenario(key) for key in SCENARIO_KEYS)


def _load[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    """Read, parse, and validate one demonstration file.

    Every failure mode collapses into the same static error: a missing
    file, unreadable bytes, broken JSON, and a schema violation are all
    "no preview data" as far as a reader is concerned, and none of them
    may put a parser message or a path into a response.
    """
    try:
        return model.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as failure:
        raise ScenarioError(OPERATOR_SAFE_SCENARIO_MESSAGE) from failure
