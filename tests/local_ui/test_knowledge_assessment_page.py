"""Knowledge assessment page: honest labels, safe states, no internals.

The page is driven by a real processed run of the committed ``rfp-mtd``
SYNTHETIC RFP FIXTURE and a synthetic golden store in ``tmp_path`` — no
real dataset, no real runtime store.
"""

from __future__ import annotations

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


def _completed_run_key(client: FlaskClient, package: str = "rfp-mtd") -> str:
    response = client.post("/runs", data={"package": package})
    assert response.status_code == 303
    security_key = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    processed = client.post(f"/runs/{security_key}/process")
    assert processed.status_code == 303
    return processed.headers["Location"].rstrip("/").rsplit("/", 1)[-1]


def _assessment_html(client: FlaskClient) -> str:
    run_key = _completed_run_key(client)
    page = client.get(f"/runs/{run_key}/knowledge-assessment")
    assert page.status_code == 200
    return page.get_data(as_text=True)


def test_completed_run_offers_and_renders_the_assessment_page(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    run_page = client.get(f"/runs/{run_key}").get_data(as_text=True)
    assert "Open knowledge assessment" in run_page

    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    assert "REQ-000001" in html
    assert "REQ-000008" in html


def test_requirement_source_locators_and_evidence_metadata_are_visible(
    client: FlaskClient,
) -> None:
    html = _assessment_html(client)

    assert "mtd-requirements.docx" in html
    assert "SD-Synthetic MTD v1.0.docx" in html
    assert "SEC-0002" in html
    assert "version 1.0" in html


def test_the_page_shows_honest_labels_and_the_review_requirement(
    client: FlaskClient,
) -> None:
    html = _assessment_html(client)

    assert "SYNTHETIC RFP INPUT" in html
    assert "INTERNAL KNOWLEDGE PILOT" in html
    assert "HUMAN REVIEW REQUIRED" in html
    assert "Candidate match — not a compliance decision" in html
    assert "EXTRACTED UNVERIFIED" in html


def test_matched_is_never_labeled_compliant_or_approved(client: FlaskClient) -> None:
    html = _assessment_html(client)

    assert "MATCHED" in html
    lowered = html.lower()
    assert "compliant" not in lowered
    assert "fulfilled" not in lowered
    assert "guaranteed" not in lowered
    # The shell states the build is "not approved for production customer
    # data"; no *other* wording may call anything approved.
    assert "approved" not in lowered.replace("not approved for production customer data", "")


def test_no_absolute_path_and_no_raw_exception_reach_the_page(
    client: FlaskClient, tmp_path: Path
) -> None:
    html = _assessment_html(client)

    assert str(tmp_path) not in html
    assert "/golden-store" not in html
    assert "Traceback" not in html


def test_no_golden_section_text_is_dumped_by_default(client: FlaskClient) -> None:
    html = _assessment_html(client)

    assert "Synthetic capability statement" not in html


def test_a_security_only_run_has_no_assessment_page(client: FlaskClient) -> None:
    response = client.post("/runs", data={"package": "rfp-mtd"})
    security_key = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

    assert client.get(f"/runs/{security_key}/knowledge-assessment").status_code == 404


def test_unknown_run_yields_404(client: FlaskClient) -> None:
    assert client.get("/runs/run-999/knowledge-assessment").status_code == 404


def test_missing_golden_store_renders_a_safe_not_evaluated_state(tmp_path: Path) -> None:
    app = create_app(
        output_base=tmp_path / "ui-runs",
        golden_store_root=tmp_path / "absent-golden-store",
    )
    client = app.test_client()
    html = _assessment_html(client)

    assert "not a capability gap" in html
    assert "NOT EVALUATED" in html
    assert "GAP" not in html.replace("not a capability gap", "")
    assert "Traceback" not in html


def test_corrupt_golden_store_renders_a_safe_state(tmp_path: Path, golden_root: Path) -> None:
    (golden_root / "claims.json").write_text("{ broken", encoding="utf-8")
    app = create_app(output_base=tmp_path / "ui-runs", golden_store_root=golden_root)
    client = app.test_client()
    html = _assessment_html(client)

    assert "could not be read" in html
    assert "NOT EVALUATED" in html
    assert "Traceback" not in html
