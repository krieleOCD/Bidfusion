"""Reviewed Working Package on the working-package page: honest and safe.

Every run here processes the committed SYNTHETIC RFP FIXTURE against a
synthetic golden store in ``tmp_path``. Generation is server-side only:
the POST carries no authoritative data, tampered artifacts are never
rendered valid, and no golden state changes at any point.
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


def _review_forms(client: FlaskClient, run_key: str) -> tuple[list[str], list[str]]:
    html = client.get(f"/runs/{run_key}/knowledge-assessment").get_data(as_text=True)
    ids = re.findall(r'name="assessment_id" value="(RKA-[0-9a-f]{12})"', html)
    digests = re.findall(r'name="assessment_digest" value="([0-9a-f]{64})"', html)
    return ids, digests


def _post_review(
    client: FlaskClient, run_key: str, assessment_id: str, digest: str, decision: str
) -> TestResponse:
    return client.post(
        f"/runs/{run_key}/knowledge-assessment/reviews",
        data={
            "assessment_id": assessment_id,
            "assessment_digest": digest,
            "decision": decision,
            "reviewer": "Alex Reviewer",
            "rationale": "",
        },
    )


def _generate(client: FlaskClient, run_key: str, **data: str) -> TestResponse:
    return client.post(f"/runs/{run_key}/reviewed-working-package", data=data)


def _packages_root(app: Flask, run_key: str) -> Path:
    record = app.config["RUN_REGISTRY"].get(run_key)
    assert record is not None
    return Path(record.output_root) / "reviewed-packages"


def test_before_generation_the_page_offers_generation_only(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)

    assert "REVIEWED WORKING PACKAGE" in html
    assert "No reviewed working package has been generated" in html
    assert "Generate Reviewed Working Package" in html
    assert "REVIEW INCOMPLETE" not in html
    assert "REVIEW COMPLETE" not in html


def test_generation_posts_persists_and_renders_an_incomplete_package(
    client: FlaskClient, app: Flask
) -> None:
    run_key = _completed_run_key(client)

    response = _generate(client, run_key)
    assert response.status_code == 303
    assert response.headers["Location"].endswith(f"/runs/{run_key}/working-package")

    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)
    assert "REVIEWED WORKING PACKAGE" in html
    assert "REVIEW INCOMPLETE" in html
    assert "RWP-" in html
    assert "version 1" in html
    # All 10 fixture requirements are pending; nothing is claimed reviewed.
    assert ">10</dd>" in html
    files = sorted(path.name for path in _packages_root(app, run_key).iterdir())
    assert files == [
        "reviewed-working-package-v0001.audit.json",
        "reviewed-working-package-v0001.payload.json",
    ]


def test_the_client_cannot_smuggle_authoritative_package_data(
    client: FlaskClient, app: Flask
) -> None:
    run_key = _completed_run_key(client)

    response = _generate(
        client,
        run_key,
        package_version="99",
        decision="CONFIRMED",
        claim_status="HUMAN_CONFIRMED",
        requirement_text="fabricated",
    )

    assert response.status_code == 303
    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)
    assert "version 1" in html
    assert "REVIEW INCOMPLETE" in html
    assert "fabricated" not in html
    audit = (_packages_root(app, run_key) / "reviewed-working-package-v0001.audit.json").read_text(
        encoding="utf-8"
    )
    assert '"package_version": 1' in audit
    assert "HUMAN_CONFIRMED" not in audit


def test_up_to_date_packages_offer_no_regeneration(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    _generate(client, run_key)

    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)
    assert "A newer review state exists" not in html
    assert "Generate Reviewed Working Package" not in html


def test_new_reviews_surface_regeneration_and_a_next_version(
    client: FlaskClient, app: Flask
) -> None:
    run_key = _completed_run_key(client)
    _generate(client, run_key)
    v1_payload = (
        _packages_root(app, run_key) / "reviewed-working-package-v0001.payload.json"
    ).read_bytes()

    ids, digests = _review_forms(client, run_key)
    assert _post_review(client, run_key, ids[1], digests[1], "CONFIRMED").status_code == 303

    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)
    assert "A newer review state exists" in html
    assert "Generate Reviewed Working Package" in html

    assert _generate(client, run_key).status_code == 303
    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)
    assert "version 2" in html
    assert "REVIEW CONFIRMED CANDIDATE" in html
    assert "A newer review state exists" not in html
    # Version 1 stays byte-identical on disk.
    assert (
        _packages_root(app, run_key) / "reviewed-working-package-v0001.payload.json"
    ).read_bytes() == v1_payload


def test_a_fully_reviewed_run_renders_review_complete(client: FlaskClient) -> None:
    run_key = _completed_run_key(client)
    ids, digests = _review_forms(client, run_key)
    for assessment_id, digest in zip(ids, digests, strict=True):
        assert _post_review(client, run_key, assessment_id, digest, "CONFIRMED").status_code == 303

    assert _generate(client, run_key).status_code == 303
    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)
    assert "REVIEW COMPLETE" in html
    assert "REVIEW INCOMPLETE" not in html


def test_the_three_trust_layers_stay_visible_and_no_compliance_is_claimed(
    client: FlaskClient, golden_root: Path
) -> None:
    run_key = _completed_run_key(client)
    ids, digests = _review_forms(client, run_key)
    _post_review(client, run_key, ids[1], digests[1], "CONFIRMED")
    claims_before = (golden_root / "claims.json").read_bytes()

    _generate(client, run_key)
    html = client.get(f"/runs/{run_key}/working-package").get_data(as_text=True)

    assert "Candidate match" in html
    assert "Golden claim" in html
    assert "Bid review" in html
    assert "EXTRACTED UNVERIFIED" in html
    lowered = html.lower()
    assert "compliant" not in lowered
    assert "fulfilled" not in lowered
    assert "guaranteed" not in lowered
    # The package section itself never claims approval; the product shell's
    # honest "not approved for production customer data" disclaimer stays.
    section = html[html.index("reviewed-package-heading") :]
    section = section[: section.index("</section>")].lower()
    assert "approved" not in section
    # Golden state is untouched by generation.
    assert (golden_root / "claims.json").read_bytes() == claims_before
    statuses = {claim.status.value for claim in GoldenKnowledgeStore(golden_root).read_claims()}
    assert statuses == {"EXTRACTED_UNVERIFIED"}


def test_a_tampered_package_is_reported_never_rendered_valid(
    client: FlaskClient, app: Flask
) -> None:
    run_key = _completed_run_key(client)
    _generate(client, run_key)
    audit = _packages_root(app, run_key) / "reviewed-working-package-v0001.audit.json"
    tampered = re.sub(rb'"pending": \d+', b'"pending": 0', audit.read_bytes(), count=1)
    audit.write_bytes(tampered)

    response = client.get(f"/runs/{run_key}/working-package")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "could not be validated" in html
    assert "REVIEW COMPLETE" not in html
    assert "RWP-" not in html
    # No new version can be generated on top of an unverifiable store.
    assert _generate(client, run_key).status_code == 409


def test_generation_is_refused_for_unpermitted_or_tampered_runs(
    client: FlaskClient, app: Flask
) -> None:
    response = client.post("/runs", data={"package": "rfp-mtd"})
    security_key = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    assert _generate(client, security_key).status_code == 404
    assert _generate(client, "run-999").status_code == 404

    run_key = _completed_run_key(client)
    record = app.config["RUN_REGISTRY"].get(run_key)
    target = record.summary.run_directory / "extraction" / "requirement-extraction.audit.json"
    original = target.read_bytes()
    target.write_bytes(original.replace(b"MUST", b"must", 1))
    try:
        assert _generate(client, run_key).status_code == 409
    finally:
        target.write_bytes(original)
    assert not _packages_root(app, run_key).exists()
