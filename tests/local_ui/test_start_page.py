"""Tests for the start screen: trusted packages only, clear MVP labeling.

The start page offers exactly the known synthetic fixture packages,
carries the mandatory scope and non-production notices, and references
no remote resource of any kind.
"""

from __future__ import annotations

from flask.testing import FlaskClient

from bidfusion.local_ui.app import create_app

KNOWN_PACKAGES = (
    "rfp-blocked",
    "rfp-german-procurement",
    "rfp-minimal",
    "rfp-mtd",
    "rfp-quality-review",
    "rfp-review",
    "rfp-unsupported",
)


def _client() -> FlaskClient:
    return create_app().test_client()


def _start_page() -> str:
    response = _client().get("/")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_start_page_offers_exactly_the_trusted_synthetic_packages() -> None:
    html = _start_page()

    assert html.count('name="package"') == len(KNOWN_PACKAGES)
    for name in KNOWN_PACKAGES:
        assert name in html


def test_start_page_shows_mvp_scope_and_non_production_notice() -> None:
    html = _start_page()

    assert "Local Synthetic MVP" in html
    assert "Not approved for production customer data" in html


def test_start_page_shows_package_file_metadata() -> None:
    html = _start_page()

    assert "rfp-invitation.pdf" in html
    assert "requirements-matrix.xlsx" in html
    assert "XLSX" in html
    assert "3 documents" in html


def test_start_page_offers_the_run_security_checks_action() -> None:
    html = _start_page()

    assert 'action="/runs"' in html
    assert 'method="post"' in html
    assert "Run security checks" in html


def test_start_page_uses_semantic_structure_for_accessibility() -> None:
    html = _start_page()

    assert '<html lang="en"' in html
    assert html.count("<h1") == 1
    assert "<fieldset" in html
    assert "<legend" in html
    assert "BidFusion" in html


def test_ui_references_no_remote_resources() -> None:
    client = _client()
    html = client.get("/").get_data(as_text=True)

    assert "https://" not in html
    assert "http://" not in html
    for stylesheet in ("tokens.css", "ui.css"):
        response = client.get(f"/static/{stylesheet}")
        assert response.status_code == 200
        css = response.get_data(as_text=True)
        assert "@import" not in css
        assert "https://" not in css
        assert "http://" not in css
        assert "url(" not in css
