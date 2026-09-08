"""The demonstration data has to be as disciplined as real data would be.

Preview pages are safe to build only because what they render is
invented and stays invented. These tests hold that line: every scenario
file validates against the schema, carries no real organization, no
person, no filesystem path, and no markup, and every one of them says on
the page that it is made up.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from flask.testing import FlaskClient
from pydantic import ValidationError

from bidfusion.local_ui.app import create_app
from bidfusion.local_ui.preview_schemas import (
    SCENARIO_SCHEMA_VERSION,
    ConnectionState,
    Scenario,
)
from bidfusion.local_ui.scenario_registry import (
    DEFAULT_SCENARIO_KEY,
    OPERATOR_SAFE_SCENARIO_MESSAGE,
    SCENARIO_KEYS,
    ScenarioError,
    all_scenarios,
    available_keys,
    load_response_lifecycle,
    load_scenario,
)

DEMO_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product_demo"

PREVIEW_PAGES = (
    "/customer-intelligence",
    "/qualification",
    "/compliance",
    "/capability-fit",
    "/competitive-intelligence",
    "/win-strategy",
    "/proposal-factory",
    "/review-approval",
)

#: Real organizations that must never appear in demonstration data. The
#: list is not exhaustive and cannot be — the rule is that every name is
#: invented, and this catches the most likely accidents.
_REAL_ORGANIZATIONS = (
    "orange cyberdefense",
    "t-systems",
    "telekom",
    "atos",
    "eviden",
    "axians",
    "computacenter",
    "accenture",
    "capgemini",
    "ibm",
    "microsoft",
    "salesforce",
    "sharepoint",
    "outlook",
    "gmail",
    "rag aktiengesellschaft",
)

#: Anything that would mean a machine path, a credential, or markup made
#: it into data that gets rendered into a page.
_FORBIDDEN = (
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"(?m)^/(usr|etc|home|var|tmp|Users)/"),
    re.compile(r"(?i)\b(api[_ -]?key|password|bearer token)\b"),
    re.compile(r"<[a-zA-Z/!]"),
    re.compile(r"&#\d"),
    re.compile(r"(?i)javascript:"),
)


@pytest.fixture(scope="module")
def client() -> FlaskClient:
    return create_app().test_client()


def _all_strings(value: object) -> list[str]:
    """Every string anywhere in a decoded scenario file."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for entry in value.values() for text in _all_strings(entry)] + [
            key for key in value if isinstance(key, str)
        ]
    if isinstance(value, list):
        return [text for entry in value for text in _all_strings(entry)]
    return []


def _raw_files() -> list[tuple[str, object]]:
    files: list[tuple[str, object]] = [
        ("response_lifecycle.json", json.loads((DEMO_ROOT / "response_lifecycle.json").read_text()))
    ]
    for key in SCENARIO_KEYS:
        path = DEMO_ROOT / "scenarios" / key / "scenario.json"
        files.append((key, json.loads(path.read_text(encoding="utf-8"))))
    return files


# --- 38: every file validates ------------------------------------------------


def test_every_offered_scenario_validates_against_the_schema() -> None:
    scenarios = all_scenarios()

    assert len(scenarios) == len(SCENARIO_KEYS)
    for scenario in scenarios:
        assert scenario.schema_version == SCENARIO_SCHEMA_VERSION
        assert scenario.key in SCENARIO_KEYS


def test_the_response_lifecycle_validates_against_the_schema() -> None:
    lifecycle = load_response_lifecycle()

    assert lifecycle.schema_version == SCENARIO_SCHEMA_VERSION
    assert lifecycle.stages


def test_a_file_that_does_not_satisfy_the_schema_is_refused() -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate({"key": "clean-opportunity"})


def test_the_three_documented_scenarios_are_the_offered_ones() -> None:
    assert available_keys() == (
        "clean-opportunity",
        "high-risk-opportunity",
        "competitive-opportunity",
    )
    assert DEFAULT_SCENARIO_KEY in available_keys()


# --- 39: no real organizations, no people ------------------------------------


def test_no_real_organization_appears_in_any_scenario() -> None:
    """Matched on word boundaries: "evidence" must not read as "Eviden"."""
    for name, payload in _raw_files():
        lowered = " ".join(_all_strings(payload)).lower()
        for organization in _REAL_ORGANIZATIONS:
            pattern = re.compile(rf"(?<![a-z]){re.escape(organization)}(?![a-z])")
            assert not pattern.search(lowered), f"{name} names {organization}"


def test_every_scenario_marks_its_invented_organizations() -> None:
    """A reader must not have to know the naming convention to be safe."""
    for scenario in all_scenarios():
        assert "invented" in scenario.synthetic_notice.lower(), scenario.key
        assert "invented" in scenario.opportunity.customer.lower(), scenario.key
        for competitor in scenario.competitive_intelligence.competitors:
            assert "invented" in competitor.name.lower(), competitor.key


def test_stakeholders_are_roles_and_never_people() -> None:
    """Roles carry no personal data; names, addresses, and quotes would."""
    for scenario in all_scenarios():
        for person in scenario.customer_intelligence.stakeholders:
            assert "@" not in person.role, scenario.key
            assert not re.search(r"\b(Herr|Frau|Mr\.|Ms\.|Dr\.)\b", person.role), scenario.key
        for reviewer in scenario.review_approval.items:
            assert "@" not in reviewer.reviewer_role, scenario.key


# --- 40, 41, 42: no paths, no markup, escaping active ------------------------


def test_no_scenario_carries_a_path_a_credential_or_markup() -> None:
    for name, payload in _raw_files():
        for text in _all_strings(payload):
            for pattern in _FORBIDDEN:
                assert not pattern.search(text), f"{name}: {text!r} matches {pattern.pattern}"


def test_scenario_text_is_escaped_rather_than_rendered(client: FlaskClient) -> None:
    """Jinja autoescaping is on: an angle bracket in data stays text."""
    from bidfusion.local_ui.app import create_app as build

    app = build()
    assert app.jinja_env.autoescape

    rendered = app.jinja_env.from_string("{{ value }}").render(value="<script>x</script>")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_no_preview_page_emits_a_script_tag(client: FlaskClient) -> None:
    for path in PREVIEW_PAGES:
        html = client.get(path).get_data(as_text=True)
        assert "<script" not in html, path
        assert "javascript:" not in html, path


# --- 43: pages receive view models, never raw scenario data ------------------


def test_no_scenario_model_or_dictionary_reaches_a_template() -> None:
    """A template gets display structures, so it cannot reach further."""
    from dataclasses import is_dataclass

    from bidfusion.local_ui.feature_registry import feature
    from bidfusion.local_ui.preview_service import load_page, section_for

    for key in ("customer_intelligence", "competitive_intelligence", "review_approval"):
        item = feature(key)
        assert item is not None
        page, scenario = load_page(item, DEFAULT_SCENARIO_KEY)
        section = section_for(key, scenario, None)

        assert is_dataclass(section), key
        assert not isinstance(section, dict), key
        assert is_dataclass(page.header)
        assert not hasattr(section, "model_dump"), f"{key} leaks a schema model"


def test_no_page_renders_a_raw_json_dump(client: FlaskClient) -> None:
    for path in PREVIEW_PAGES:
        html = client.get(path).get_data(as_text=True)
        assert "schema_version" not in html, path
        assert "'key':" not in html, path
        assert "{'" not in html, path


# --- 44: an unknown scenario is a plain 404 ----------------------------------


@pytest.mark.parametrize("path", PREVIEW_PAGES)
def test_an_unknown_scenario_is_a_safe_404(client: FlaskClient, path: str) -> None:
    response = client.get(f"{path}?scenario=does-not-exist")

    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert "Traceback" not in html
    assert "does-not-exist" not in html


@pytest.mark.parametrize("path", PREVIEW_PAGES)
def test_every_offered_scenario_renders_on_every_page(client: FlaskClient, path: str) -> None:
    for key in SCENARIO_KEYS:
        response = client.get(f"{path}?scenario={key}")
        assert response.status_code == 200, f"{path}?scenario={key}"


def test_a_scenario_key_cannot_reach_the_filesystem() -> None:
    """The key is checked against the offered set before any path exists."""
    for probe in ("../../etc/passwd", "..", ".", "clean-opportunity/../..", "%2e%2e", "~/.env"):
        with pytest.raises(ScenarioError) as raised:
            load_scenario(probe)
        assert str(raised.value) == OPERATOR_SAFE_SCENARIO_MESSAGE


def test_a_traversal_attempt_in_the_query_string_is_a_404(client: FlaskClient) -> None:
    for probe in ("../../etc/passwd", "..%2f..%2fetc", "/etc/passwd"):
        response = client.get("/compliance", query_string={"scenario": probe})
        assert response.status_code == 404
        assert "etc" not in response.get_data(as_text=True).replace("Cyberdefense", "")


# --- nothing claims to be connected ------------------------------------------


def test_no_source_in_any_scenario_claims_to_be_connected() -> None:
    for scenario in all_scenarios():
        for source in scenario.customer_intelligence.sources:
            assert source.connection is ConnectionState.NOT_CONNECTED, scenario.key


def test_every_competitor_signal_states_that_it_was_not_collected() -> None:
    for scenario in all_scenarios():
        for competitor in scenario.competitive_intelligence.competitors:
            for signal in competitor.signals:
                assert "no collection date" in signal.collected.lower(), competitor.key


def test_every_battle_card_states_that_it_is_not_approved() -> None:
    for scenario in all_scenarios():
        for card in scenario.competitive_intelligence.battle_cards:
            assert "not" in card.approval_state.lower(), scenario.key
            assert "approved" in card.approval_state.lower(), scenario.key


def test_the_scenario_notice_reaches_every_preview_page(client: FlaskClient) -> None:
    notice = load_scenario(DEFAULT_SCENARIO_KEY).synthetic_notice
    for path in PREVIEW_PAGES:
        html = client.get(path).get_data(as_text=True)
        assert notice in html, path
