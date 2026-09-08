"""The bid workspace: workflow stepper, counted facts, and trust layers.

The redesigned run page presents one bid as one workflow. These tests
pin the presentation to the recorded state — a step never claims more
than the run wrote down, machine and human states never share a visual
class, and the versioned package UX never presents regeneration as
overwriting.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import populate_synthetic_golden_store
from flask import Flask
from flask.testing import FlaskClient

from bidfusion.local_ui.app import create_app


@pytest.fixture
def golden_root(tmp_path: Path) -> Path:
    root = tmp_path / "golden-store"
    populate_synthetic_golden_store(root)
    return root


@pytest.fixture
def app(tmp_path: Path, golden_root: Path) -> Flask:
    return create_app(output_base=tmp_path / "ui-runs", golden_store_root=golden_root)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def _security_run_key(client: FlaskClient, package: str) -> str:
    response = client.post("/runs", data={"package": package})
    return response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]


def _completed_run_key(client: FlaskClient) -> str:
    security_key = _security_run_key(client, "rfp-mtd")
    processed = client.post(f"/runs/{security_key}/process")
    return processed.headers["Location"].rstrip("/").rsplit("/", 1)[-1]


def _review_forms(client: FlaskClient, run_key: str) -> tuple[list[str], list[str]]:
    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    ids = re.findall(r'name="assessment_id" value="(RKA-[0-9a-f]{12})"', html)
    digests = re.findall(r'name="assessment_digest" value="([0-9a-f]{64})"', html)
    return ids, digests


def _review_all(client: FlaskClient, run_key: str, decision: str = "CONFIRMED") -> None:
    ids, digests = _review_forms(client, run_key)
    for assessment_id, digest in zip(ids, digests, strict=True):
        client.post(
            f"/runs/{run_key}/knowledge-assessment/reviews",
            data={
                "assessment_id": assessment_id,
                "assessment_digest": digest,
                "decision": decision,
                "reviewer": "Alex Reviewer",
                "rationale": "",
            },
        )


# --- The workflow stepper never claims more than the run recorded ------------


def test_a_cleared_security_run_shows_the_workflow_with_analysis_active(
    client: FlaskClient,
) -> None:
    run_key = _security_run_key(client, "rfp-minimal")
    html = client.get(f"/runs/{run_key}").get_data(as_text=True)

    assert 'class="workflow"' in html
    assert "workflow__step--complete" in html  # intake cleared
    assert "workflow__step--active" in html  # requirements next
    assert "Run the full analysis" in html
    assert "workflow__step--attention" not in html


def test_a_blocked_run_marks_intake_as_attention_and_offers_no_analysis(
    client: FlaskClient,
) -> None:
    run_key = _security_run_key(client, "rfp-blocked")
    html = client.get(f"/runs/{run_key}").get_data(as_text=True)

    assert "workflow__step--attention" in html
    assert "Blocked by the security gate" in html
    assert "No further processing is possible" in html
    assert "Run full analysis" not in html


def test_a_completed_run_counts_requirements_and_pending_reviews(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    html = client.get(f"/runs/{run_key}").get_data(as_text=True)

    assert "Where this bid stands" in html
    assert "Requirements" in html
    assert "Candidate matches" in html
    assert "Needs review" in html
    assert "Evidence references" in html
    assert "await a human review decision" in html
    assert f"/runs/{run_key}/knowledge-assessment" in html
    # The stepper reports the pending count, from the recorded reviews.
    assert re.search(r"\d+ of \d+ pending", html)


def test_counts_are_never_shown_before_the_run_produced_them(client: FlaskClient) -> None:
    run_key = _security_run_key(client, "rfp-minimal")
    html = client.get(f"/runs/{run_key}").get_data(as_text=True)

    assert "Where this bid stands" not in html
    assert "Candidate matches" not in html


def test_full_review_moves_the_next_action_to_package_generation(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    _review_all(client, run_key)
    html = client.get(f"/runs/{run_key}").get_data(as_text=True)

    assert "Every assessment reviewed" in html
    assert "Generate the reviewed working package" in html


def test_a_generated_package_reports_its_version_on_the_run_page(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    client.post(f"/runs/{run_key}/reviewed-working-package")
    html = client.get(f"/runs/{run_key}").get_data(as_text=True)

    assert "v1" in html
    assert "REVIEW INCOMPLETE" in html


def test_a_current_fully_reviewed_package_reads_up_to_date(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    _review_all(client, run_key)
    client.post(f"/runs/{run_key}/reviewed-working-package")
    html = client.get(f"/runs/{run_key}").get_data(as_text=True)

    assert "up to date" in html
    assert "REVIEW COMPLETE" in html


# --- Trust layers never share a visual voice ---------------------------------


def test_machine_and_human_states_use_distinct_chip_classes(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    _review_all(client, run_key)
    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)

    assert "trust-chip--machine" in html
    assert "trust-chip--knowledge" in html
    assert "trust-chip--human-review-confirmed-candidate" in html
    # A machine MATCHED never renders inside a human decision chip.
    for chunk in re.findall(r'class="trust-chip trust-chip--human[^"]*">([^<]*)<', html):
        assert "MATCHED" not in chunk or "CONFIRMED" in chunk


def test_the_golden_claim_stays_visibly_unverified_after_a_confirmation(
    client: FlaskClient,
) -> None:
    run_key = _completed_run_key(client)
    _review_all(client, run_key)
    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)

    assert "EXTRACTED UNVERIFIED" in html
    assert "REVIEW CONFIRMED CANDIDATE" in html
    assert "unchanged by any bid review" in html


# --- Versioned package UX: regeneration is never overwriting -----------------


def test_a_current_package_says_so_and_a_stale_one_explains_versioning(
    client: FlaskClient,
) -> None:
    run_key = _completed_run_key(client)
    client.post(f"/runs/{run_key}/reviewed-working-package")
    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)
    assert "reflects the latest recorded review state" in html
    assert "package-banner--current" in html

    ids, digests = _review_forms(client, run_key)
    client.post(
        f"/runs/{run_key}/knowledge-assessment/reviews",
        data={
            "assessment_id": ids[0],
            "assessment_digest": digests[0],
            "decision": "CONFIRMED",
            "reviewer": "Alex Reviewer",
            "rationale": "",
        },
    )
    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)
    assert "package-banner--newer" in html
    assert "existing package\n       versions remain unchanged" in html or (
        "existing package" in html and "versions remain unchanged" in html
    )
    assert "version 2" in html  # the next version is named, not an overwrite


def test_the_working_package_lists_what_still_needs_attention(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    client.post(f"/runs/{run_key}/reviewed-working-package")
    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)

    assert "Attention required" in html
    assert "Awaiting a human review decision" in html
    assert "Review coverage" in html


# --- Shell: identity, honesty, and quiet internal areas ----------------------


def test_the_header_carries_the_official_logo_and_one_scope_statement(
    client: FlaskClient,
) -> None:
    html = client.get("/overview").get_data(as_text=True)

    assert 'class="brand-logo"' in html
    assert 'alt="Orange Cyberdefense"' in html
    assert "ocd-logo-master-white.png" in html
    assert "Not approved for production customer data" in html
    assert html.count("env-badge") <= 2  # one badge, not a badge wall


def test_internal_areas_are_marked_apart_from_the_workspace(client: FlaskClient) -> None:
    html = client.get("/overview").get_data(as_text=True)

    assert "product-nav__link--internal" in html
    assert "Product Preview" in html
    assert "Architecture and Roadmap" in html
    assert "Knowledge and Evidence" in html


def test_the_overview_shows_the_functional_loop_in_order(client: FlaskClient) -> None:
    html = client.get("/overview").get_data(as_text=True)

    band = re.search(r'<ol class="flow-band.*?</ol>', html, re.DOTALL)
    assert band is not None
    positions = [
        band.group(0).index(stage)
        for stage in ("RFP", "Requirements", "Knowledge", "Evidence", "Human Review")
    ]
    assert positions == sorted(positions)


def test_the_knowledge_inventory_leads_with_groups_not_files(client: FlaskClient) -> None:
    html = client.get("/golden-knowledge").get_data(as_text=True)

    assert "group-tile" in html
    assert "File inventory" in html
    assert "<details" in html


# --- Run pages stay accessible ----------------------------------------------


def test_the_run_page_keeps_one_h1_and_labelled_sections(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    html = client.get(f"/runs/{run_key}").get_data(as_text=True)

    assert html.count("<h1") == 1
    unlabelled = re.findall(r"<section(?![^>]*aria-label)", html)
    assert not unlabelled


def test_the_assessment_page_keeps_one_h1_and_labelled_sections(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)

    assert html.count("<h1") == 1
    unlabelled = re.findall(r"<section(?![^>]*aria-label)", html)
    assert not unlabelled


# --- The workspace module stays pure presentation ----------------------------


def test_the_workspace_module_reaches_no_pipeline_flask_or_network() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "src" / "bidfusion" / "local_ui" / "workspace.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "import flask",
        "from flask",
        "bidfusion.pipeline",
        "bidfusion.security",
        "bidfusion.llm",
        "import requests",
        "import httpx",
        "import socket",
        "import urllib",
    ):
        assert forbidden not in source, forbidden
