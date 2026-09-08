"""The feature registry is the one place that may claim a status.

These tests pin what the registry is allowed to say: keys are unique,
statuses and data modes come from the closed vocabularies, every visible
feature is reachable through a real route, and a claim about a live
source is backed by an actual source. They also keep the registry free
of anything that has no business in configuration a template renders —
filesystem paths, credentials, environment values.
"""

from __future__ import annotations

import re
from dataclasses import fields

import pytest
from flask import Flask

from bidfusion.local_ui.app import create_app
from bidfusion.local_ui.feature_registry import (
    DataMode,
    Feature,
    FeatureStatus,
    Phase,
    PhaseDefinition,
    PhaseState,
    Visibility,
    all_features,
    all_phases,
    feature,
    feature_for_route,
    features_for_phase,
)
from bidfusion.local_ui.product_shell import NAV_WORLDS

MAX_DEPENDENCIES = 6
MAX_SHORT_DESCRIPTION = 240

#: Anything matching these must never appear in registry text: they
#: would mean a secret, a machine path, or an environment value had been
#: written into configuration that is rendered into HTML.
_FORBIDDEN_PATTERNS = (
    re.compile(r"(?i)\bapi[_ -]?key\b"),
    re.compile(r"(?i)\bsecret\b"),
    re.compile(r"(?i)\btoken\b"),
    re.compile(r"(?i)\bpassword\b"),
    re.compile(r"(?i)\bbearer\b"),
    re.compile(r"(?i)\bBIDFUSION_[A-Z_]+"),
    re.compile(r"^~"),
    re.compile(r"^/"),
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"\\\\"),
)


@pytest.fixture(scope="module")
def app() -> Flask:
    return create_app()


def _strings(item: Feature | Phase) -> tuple[str, ...]:
    collected: list[str] = []
    for field in fields(item):
        value = getattr(item, field.name)
        if isinstance(value, str):
            collected.append(value)
        elif isinstance(value, tuple):
            collected.extend(entry for entry in value if isinstance(entry, str))
    return tuple(collected)


# --- 1. keys and identity ----------------------------------------------------


def test_every_feature_key_is_unique() -> None:
    keys = [item.key for item in all_features()]

    assert len(keys) == len(set(keys))
    assert all(key == key.lower() for key in keys)


def test_every_phase_id_is_unique_and_lookup_finds_it() -> None:
    phase_ids = [item.phase_id for item in all_phases()]

    assert len(phase_ids) == len(set(phase_ids))
    for item in all_features():
        assert feature(item.key) is item


# --- 2. and 3. closed vocabularies -------------------------------------------


def test_statuses_and_data_modes_come_from_the_closed_vocabularies() -> None:
    for item in all_features():
        assert isinstance(item.status, FeatureStatus), item.key
        assert isinstance(item.data_mode, DataMode), item.key
        assert isinstance(item.visibility, Visibility), item.key


def test_phase_states_and_definitions_come_from_the_closed_vocabularies() -> None:
    for item in all_phases():
        assert isinstance(item.state, PhaseState), item.phase_id
        assert isinstance(item.definition, PhaseDefinition), item.phase_id


# --- 4. every visible feature is reachable -----------------------------------


def test_every_feature_route_exists_in_the_application(app: Flask) -> None:
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}

    for item in all_features():
        assert item.route_name in endpoints, item.key


def test_pages_of_their_own_are_linkable_without_extra_context(app: Flask) -> None:
    """A nav or module page must be reachable from a bare link."""
    arguments = {rule.endpoint: rule.arguments for rule in app.url_map.iter_rules()}

    for item in all_features():
        if item.visibility is Visibility.MODULE_SECTION:
            continue
        assert not arguments[item.route_name], item.key


def test_route_lookup_prefers_the_feature_that_owns_the_page() -> None:
    """Several features share the start page; the page is the intake page."""
    owner = feature_for_route("index")

    assert owner is not None
    assert owner.key == "rfp_intake"
    assert feature_for_route("no-such-endpoint") is None


# --- 5. every feature belongs to a known phase -------------------------------


def test_every_feature_targets_a_known_phase() -> None:
    known = {item.phase_id for item in all_phases()}

    for item in all_features():
        assert item.target_phase in known, item.key


def test_every_phase_is_reachable_from_its_features() -> None:
    for item in all_phases():
        for owned in features_for_phase(item.phase_id):
            assert owned.target_phase == item.phase_id


# --- 6., 7., 8. a status may not claim more than it has ----------------------


def test_live_features_name_a_real_current_source() -> None:
    for item in all_features():
        if item.status is not FeatureStatus.LIVE:
            continue
        assert item.current_sources, item.key
        assert item.data_mode is not DataMode.NOT_CONNECTED, item.key


def test_demo_features_render_curated_data_and_say_so() -> None:
    for item in all_features():
        if item.status is not FeatureStatus.DEMO:
            continue
        assert item.data_mode is DataMode.CURATED_DEMO, item.key
        assert any(
            "demonstration" in text.lower() or "invented" in text.lower()
            for text in (*item.limitations, *item.current_sources)
        ), item.key


def test_planned_and_blocked_features_claim_no_live_connection() -> None:
    for item in all_features():
        if item.status not in (FeatureStatus.PLANNED, FeatureStatus.BLOCKED):
            continue
        assert item.data_mode in (
            DataMode.CURATED_DEMO,
            DataMode.STATIC_PREVIEW,
            DataMode.NOT_CONNECTED,
        ), item.key
        assert item.limitations, item.key


def test_features_awaiting_review_are_not_connected() -> None:
    for item in all_features():
        if item.status is not FeatureStatus.REVIEW_REQUIRED:
            continue
        assert item.data_mode is DataMode.NOT_CONNECTED, item.key
        assert not item.current_sources, item.key


def test_the_expected_status_distribution_holds() -> None:
    """The statuses this build is allowed to advertise, pinned explicitly."""
    by_key = {item.key: item for item in all_features()}

    assert by_key["rfp_intake"].status is FeatureStatus.LIVE
    assert by_key["rfp_intake"].data_mode is DataMode.VERIFIED_ARTIFACTS
    assert by_key["synthetic_analysis"].status is FeatureStatus.LIVE
    assert by_key["synthetic_analysis"].data_mode is DataMode.SYNTHETIC_FIXTURE
    assert by_key["customer_intelligence"].status is FeatureStatus.PLANNED
    assert by_key["customer_intelligence"].data_mode is DataMode.CURATED_DEMO
    assert by_key["competitive_intelligence"].status is FeatureStatus.DEMO
    assert by_key["competitive_intelligence"].data_mode is DataMode.CURATED_DEMO
    assert by_key["proposal_factory"].status is FeatureStatus.PLANNED
    assert by_key["proposal_factory"].data_mode is DataMode.STATIC_PREVIEW
    assert by_key["production_data_operation"].status is FeatureStatus.BLOCKED


# --- 9. records stay bounded and complete ------------------------------------


def test_dependencies_stay_bounded_and_non_empty() -> None:
    for item in all_features():
        assert len(item.dependencies) <= MAX_DEPENDENCIES, item.key
        assert all(entry.strip() for entry in item.dependencies), item.key


def test_every_feature_record_is_complete() -> None:
    for item in all_features():
        assert item.title.strip(), item.key
        assert item.short_description.strip(), item.key
        assert len(item.short_description) <= MAX_SHORT_DESCRIPTION, item.key
        assert item.owner.strip(), item.key
        assert item.acceptance_criteria, item.key
        assert item.route_name.strip(), item.key


def test_every_phase_record_is_complete() -> None:
    for item in all_phases():
        assert item.phase_id.strip()
        assert item.title.strip()
        assert item.summary.strip()
        assert item.definition_reference.strip()


def test_proposed_phases_say_that_no_document_defines_them() -> None:
    for item in all_phases():
        if item.definition is PhaseDefinition.PROPOSED:
            assert "no architecture document" in item.definition_reference.lower(), item.phase_id
        else:
            assert item.definition_reference.startswith("docs/"), item.phase_id


# --- 10. nothing in the registry may leak an environment ---------------------


def test_the_registry_holds_no_paths_secrets_or_environment_values() -> None:
    records: tuple[Feature | Phase, ...] = (*all_features(), *all_phases())
    for item in records:
        for text in _strings(item):
            for pattern in _FORBIDDEN_PATTERNS:
                assert not pattern.search(text), f"{text!r} matches {pattern.pattern}"


def test_feature_text_carries_no_filesystem_paths_at_all() -> None:
    """Phases may cite a document; feature records have no reason to."""
    for item in all_features():
        for text in _strings(item):
            assert "/" not in text, f"{item.key}: {text!r}"


def test_navigation_only_references_registered_features() -> None:
    keys = {item.key for item in all_features()}

    for world in NAV_WORLDS:
        assert world.feature_key in keys, world.key
        for entry in world.items:
            assert entry.feature_key in keys, entry.key
