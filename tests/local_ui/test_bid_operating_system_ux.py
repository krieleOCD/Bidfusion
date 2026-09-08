"""Decision-first UX contracts for the BidFusion operating-system shell."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import populate_synthetic_golden_store
from flask import Flask
from flask.testing import FlaskClient

from bidfusion.local_ui.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> FlaskClient:
    golden_root = tmp_path / "golden-store"
    populate_synthetic_golden_store(golden_root)
    app: Flask = create_app(
        output_base=tmp_path / "ui-runs", golden_store_root=golden_root
    )
    return app.test_client()


def _completed_run_key(client: FlaskClient) -> str:
    started = client.post("/runs", data={"package": "rfp-mtd"})
    security_key = started.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    processed = client.post(f"/runs/{security_key}/process")
    return processed.headers["Location"].rstrip("/").rsplit("/", 1)[-1]


def test_shell_uses_four_product_level_destinations(client: FlaskClient) -> None:
    html = client.get("/overview").get_data(as_text=True)
    for label in ("Bids", "Knowledge", "Portfolio and Strategy", "Product Status"):
        assert label in html
    assert "Jump to anything" in html


def test_operating_model_names_the_bid_questions_and_lifecycle(client: FlaskClient) -> None:
    html = client.get("/overview").get_data(as_text=True)
    for question in ("Which bid?", "What state?", "What risk?", "What next?"):
        assert question in html
    for stage in ("Qualify", "Understand", "Strategize", "Design", "Respond", "Review", "Submit"):
        assert stage in html


def test_command_center_orders_attention_before_health(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    html = client.get(f"/runs/{run_key}").get_data(as_text=True)
    assert html.index("What needs attention next") < html.index("Where this bid stands")
    assert "Next best action" in html
    assert html.count('class="health-signal ') == 4


def test_requirement_workbench_renders_one_active_decision_form(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    assert html.count('class="review-form"') == 1
    assert html.count('class="requirement-queue__item') == 8
    assert html.index("Requirement queue") < html.index("Analysis &amp; evidence")
    assert html.index("Analysis &amp; evidence") < html.index(
        'id="decision-heading">Human decision'
    )


def test_requirement_filters_keep_a_focused_master_detail_surface(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    response = client.get(
        f"/runs/{run_key}/knowledge-assessment?filter=mandatory&focus=REQ-000003"
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'class="is-active"' in html
    assert "REQ-000003" in html
    assert html.count('class="review-form"') == 1
