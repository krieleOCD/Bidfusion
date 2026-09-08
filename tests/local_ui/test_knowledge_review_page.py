"""Review mutation on the knowledge-assessment page: safety and honesty.

Every run here processes the committed SYNTHETIC RFP FIXTURE against a
synthetic golden store in ``tmp_path``. No real dataset, no real
runtime store, and — asserted explicitly — no golden state change from
any review action.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import populate_synthetic_golden_store
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from bidfusion.golden_dataset.store import GoldenKnowledgeStore
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


def _completed_run_key(client: FlaskClient) -> str:
    response = client.post("/runs", data={"package": "rfp-mtd"})
    security_key = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    processed = client.post(f"/runs/{security_key}/process")
    return processed.headers["Location"].rstrip("/").rsplit("/", 1)[-1]


def _forms(client: FlaskClient, run_key: str) -> tuple[list[str], list[str]]:
    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    ids = re.findall(r'name="assessment_id" value="(RKA-[0-9a-f]{12})"', html)
    digests = re.findall(r'name="assessment_digest" value="([0-9a-f]{64})"', html)
    return ids, digests


def _post(
    client: FlaskClient,
    run_key: str,
    assessment_id: str,
    digest: str,
    decision: str,
    reviewer: str = "Alex Reviewer",
    rationale: str = "",
) -> TestResponse:
    return client.post(
        f"/runs/{run_key}/knowledge-assessment/reviews",
        data={
            "assessment_id": assessment_id,
            "assessment_digest": digest,
            "decision": decision,
            "reviewer": reviewer,
            "rationale": rationale,
        },
    )


def test_pending_reviews_and_disclaimers_are_shown_before_any_decision(
    client: FlaskClient,
) -> None:
    run_key = _completed_run_key(client)
    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)

    assert html.count("PENDING — no decision recorded") == 10
    assert "This decision applies to this bid assessment only." in html
    assert "It does not validate or modify the underlying Golden Knowledge claim." in html
    assert "Reviewed working package projection" in html


def test_each_decision_posts_redirects_and_renders_distinctly(
    client: FlaskClient, golden_root: Path
) -> None:
    run_key = _completed_run_key(client)
    ids, digests = _forms(client, run_key)
    claims_before = (golden_root / "claims.json").read_bytes()

    for index, decision in ((1, "CONFIRMED"), (3, "REJECTED"), (6, "NEEDS_CLARIFICATION")):
        response = _post(client, run_key, ids[index], digests[index], decision)
        assert response.status_code == 303
        location = response.headers["Location"]
        assert location.endswith(f"/runs/{run_key}/knowledge-assessment")

    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    assert "REVIEW CONFIRMED CANDIDATE" in html
    assert "REVIEW REJECTED CANDIDATE" in html
    assert "CLARIFICATION REQUIRED" in html
    assert "Alex Reviewer" in html
    # Golden claim state is untouched and still shown as unverified.
    assert (golden_root / "claims.json").read_bytes() == claims_before
    assert "EXTRACTED UNVERIFIED" in html
    statuses = {claim.status.value for claim in GoldenKnowledgeStore(golden_root).read_claims()}
    assert statuses == {"EXTRACTED_UNVERIFIED"}


def test_candidate_claim_and_review_are_three_distinct_concepts(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    ids, digests = _forms(client, run_key)
    _post(client, run_key, ids[1], digests[1], "CONFIRMED")

    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    assert "Candidate match" in html
    assert "Golden claim" in html
    assert "Bid review" in html
    assert "unchanged by any bid review" in html


def test_invalid_inputs_are_rejected_without_recording(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    ids, digests = _forms(client, run_key)

    assert _post(client, run_key, ids[0], digests[0], "APPROVED").status_code == 400
    assert _post(client, run_key, "RKA-ffffffffffff", digests[0], "CONFIRMED").status_code == 400
    assert _post(client, run_key, ids[0], digests[0], "CONFIRMED", reviewer="  ").status_code == 400
    assert (
        _post(client, run_key, ids[0], digests[0], "CONFIRMED", reviewer="R" * 121).status_code
        == 400
    )
    assert (
        _post(client, run_key, ids[0], digests[0], "CONFIRMED", rationale="r" * 2001).status_code
        == 400
    )

    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    assert html.count("PENDING — no decision recorded") == 10


def test_a_stale_assessment_digest_is_refused_not_applied(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    ids, _ = _forms(client, run_key)

    response = _post(client, run_key, ids[0], "0" * 64, "CONFIRMED")

    assert response.status_code == 409
    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    assert html.count("PENDING — no decision recorded") == 10


def test_a_snapshot_change_between_render_and_submit_stales_the_review(
    tmp_path: Path, golden_root: Path
) -> None:
    """Assessment v1 rendered, assessment changes, stale POST arrives."""
    app = create_app(output_base=tmp_path / "ui-runs", golden_store_root=golden_root)
    client = app.test_client()
    run_key = _completed_run_key(client)
    ids, digests = _forms(client, run_key)

    # The knowledge snapshot changes: remove all claims -> same assessment
    # id, different content, different digest.
    (golden_root / "claims.json").write_text("[]", encoding="utf-8")

    response = _post(client, run_key, ids[1], digests[1], "CONFIRMED")
    assert response.status_code == 409

    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    assert html.count("PENDING — no decision recorded") == 10


def test_rationale_is_escaped_in_the_rendered_page(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    ids, digests = _forms(client, run_key)
    hostile = '<script>alert("x")</script>'
    posted = _post(client, run_key, ids[1], digests[1], "CONFIRMED", rationale=hostile)
    assert posted.status_code == 303

    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_duplicate_posts_append_a_new_revision_without_corruption(
    client: FlaskClient,
) -> None:
    run_key = _completed_run_key(client)
    ids, digests = _forms(client, run_key)
    assert _post(client, run_key, ids[1], digests[1], "CONFIRMED").status_code == 303
    assert _post(client, run_key, ids[1], digests[1], "CONFIRMED").status_code == 303

    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    assert "revision 2" in html
    assert html.count("REVIEW CONFIRMED CANDIDATE") >= 1


def test_reviews_on_unpermitted_or_tampered_runs_are_refused(
    client: FlaskClient, app: Flask
) -> None:
    response = client.post("/runs", data={"package": "rfp-mtd"})
    security_key = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    assert _post(client, security_key, "RKA-aaaaaaaaaaaa", "0" * 64, "CONFIRMED").status_code == 404
    assert _post(client, "run-999", "RKA-aaaaaaaaaaaa", "0" * 64, "CONFIRMED").status_code == 404

    run_key = _completed_run_key(client)
    ids, digests = _forms(client, run_key)
    record = app.config["RUN_REGISTRY"].get(run_key)
    audit = record.summary.run_directory / "extraction" / "requirement-extraction.audit.json"
    original = audit.read_bytes()
    audit.write_bytes(original.replace(b"MUST", b"must", 1))
    try:
        assert _post(client, run_key, ids[0], digests[0], "CONFIRMED").status_code == 409
        assert client.get(f"/runs/{run_key}/knowledge-assessment").status_code == 409
    finally:
        audit.write_bytes(original)
    # No review was recorded during the tampered window.
    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    assert html.count("PENDING — no decision recorded") == 10


def test_the_working_package_page_shows_the_reviewed_projection(
    client: FlaskClient,
) -> None:
    run_key = _completed_run_key(client)
    ids, digests = _forms(client, run_key)
    _post(client, run_key, ids[1], digests[1], "CONFIRMED")

    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)
    assert "Reviewed knowledge assessment" in html
    assert "REVIEW CONFIRMED CANDIDATE" in html
    assert "This decision applies to this bid assessment only." in html
