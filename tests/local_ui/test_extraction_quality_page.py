"""The extraction-quality page presents frozen Evaluation #3 honestly.

The page is a presentation of a hand-transcribed frozen evaluation
record. These tests lock the record's internal consistency, the page's
key statements, and the honesty rules: unmapped candidates are never
called proven false requirements, and no wording claims completeness
or production readiness.
"""

from __future__ import annotations

import pytest
from flask import Flask
from flask.testing import FlaskClient

from bidfusion.local_ui.app import create_app
from bidfusion.local_ui.extraction_evaluation import EVALUATION, build_page_view


@pytest.fixture
def app() -> Flask:
    return create_app()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def _html(client: FlaskClient) -> str:
    response = client.get("/extraction-quality")
    assert response.status_code == 200
    return response.get_data(as_text=True)


# --- the frozen record is internally consistent ------------------------------


def test_matches_and_misses_add_up_to_the_ground_truth() -> None:
    matches = EVALUATION.matches
    total = matches.exact + matches.partial + matches.ambiguous + matches.missed
    assert total == EVALUATION.ground_truth_count == 364


def test_document_coverage_adds_up_to_the_ground_truth() -> None:
    assert sum(item.ground_truth for item in EVALUATION.documents) == 364
    assert sum(item.missed for item in EVALUATION.documents) == EVALUATION.matches.missed


def test_gap_taxonomy_covers_every_missed_requirement() -> None:
    assert sum(item.count for item in EVALUATION.gaps) == EVALUATION.matches.missed


def test_the_record_declares_itself_frozen() -> None:
    assert EVALUATION.evaluation_status == "FROZEN"
    assert EVALUATION.extractor_version == "0.3.0"
    assert "Evaluation #3" in EVALUATION.source_label


def test_the_history_ends_at_the_frozen_result() -> None:
    last = EVALUATION.history[-1]
    assert last.candidates == EVALUATION.candidate_count
    assert last.inclusive_percent == EVALUATION.recall.inclusive_percent
    assert EVALUATION.history[0].candidates == 0


# --- the page states the headline result -------------------------------------


def test_the_page_shows_the_headline_metrics(client: FlaskClient) -> None:
    html = _html(client)
    assert "75.8%" in html
    assert "67.3%" in html
    assert "364" in html
    assert "230" in html
    assert "Inclusive recall" in html
    assert "Strict recall" in html


def test_the_page_shows_milestones_and_pilot_readiness(client: FlaskClient) -> None:
    html = _html(client)
    assert "Milestone A" in html
    assert "Reached" in html
    assert "Not yet" in html
    assert "Ready with conditions" in html
    assert "Controlled Real RFP Pilot #2" in html


def test_the_page_shows_the_progression_and_both_frozen_anchors(client: FlaskClient) -> None:
    html = _html(client)
    for version in ("v0.1", "v0.2", "v0.3h"):
        assert version in html
    assert "18.4%" in html


def test_the_page_shows_coverage_gaps_and_next_step(client: FlaskClient) -> None:
    html = _html(client)
    assert "Coverage by RFP Document" in html
    assert "Remaining Extraction Gaps" in html
    assert "Atomic Requirement Splitting" in html
    assert "Leistungsbeschreibung" in html
    assert "Formulare" in html


def test_the_page_explains_strict_and_inclusive_recall(client: FlaskClient) -> None:
    html = _html(client)
    assert "atomic" in html.lower()
    assert "broader candidate block" in html


# --- honesty rules -----------------------------------------------------------


def test_unmapped_candidates_are_not_called_proven_false(client: FlaskClient) -> None:
    html = _html(client)
    assert "unmapped candidates" in html.lower()
    assert "outside the curated Ground Truth" in html
    assert "false positive" not in html.lower()


def test_the_page_never_overclaims(client: FlaskClient) -> None:
    html = _html(client)
    lowered = html.lower()
    assert "production-ready" not in lowered
    assert "production ready" not in lowered
    assert "100%" not in html


# --- the shell knows the page ------------------------------------------------


def test_the_page_is_reachable_from_the_product_status_navigation(client: FlaskClient) -> None:
    html = _html(client)
    assert 'aria-current="page"' in html


def test_the_overview_carries_the_summary_card(client: FlaskClient) -> None:
    html = client.get("/overview").get_data(as_text=True)
    assert "75.8%" in html
    assert "/extraction-quality" in html


# --- the view model precomputes what the template may not --------------------


def test_the_page_view_scales_bars_to_whole_percent() -> None:
    view = build_page_view()
    assert view.history_rows[-1].inclusive_bar_percent == 76
    assert view.history_rows[0].inclusive_bar_percent == 0
    for row in view.document_rows:
        assert 0 <= row.coverage_percent <= 100
