"""No page may claim more than the build actually does.

The interface shows finished work and unfinished work side by side, which
only stays safe as long as the difference is stated on the page itself.
These tests read the rendered HTML and fail on any wording that would let
a reader mistake a preview for a working integration, curated data for a
real customer, or a system assessment for a human decision.
"""

from __future__ import annotations

import io

import pytest
from flask import Flask
from flask.testing import FlaskClient

from bidfusion.local_ui.app import create_app
from bidfusion.local_ui.feature_registry import all_features
from bidfusion.local_ui.upload_service import AUTHORIZATION_STATEMENT

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

ALL_PAGES = ("/", "/overview", "/architecture-roadmap", *PREVIEW_PAGES)

#: Wording that would assert a working connection to a system this build
#: does not talk to. Matched case-insensitively against every page.
_CONNECTION_CLAIMS = (
    "connected to salesforce",
    "connected to teams",
    "connected to sharepoint",
    "connected to outlook",
    "live crm",
    "live scan",
    "live data",
    "syncing",
    "synced",
    "last scan:",
    "emails found",
    "meetings analysed",
    "meetings analyzed",
    "documents retrieved",
    "opportunity linked",
)

#: Wording that would assert autonomous behaviour. The product may model
#: workflow stages; it may not suggest something is running on its own.
_AUTONOMY_CLAIMS = (
    "agents active",
    "agent is running",
    "agents are running",
    "autonomously",
    "runs automatically",
    "automatic submission",
    "submitted automatically",
    "ai decision",
    "let ai do",
)


@pytest.fixture(scope="module")
def app() -> Flask:
    return create_app()


@pytest.fixture(scope="module")
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def _html(client: FlaskClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, path
    return response.get_data(as_text=True)


def _fact_block(html: str, title: str) -> str:
    """The markup of one titled fact block, so a claim can be located."""
    marker = f"<h3>{title}</h3>"
    assert marker in html, f"no fact block titled {title}"
    return html.split(marker, 1)[1].split("</div>", 1)[0]


# --- 17-20: each module states its own status ---------------------------------


def test_customer_intelligence_declares_planned_and_curated_demo(client: FlaskClient) -> None:
    html = _html(client, "/customer-intelligence")

    assert "PLANNED" in html
    assert "CURATED DEMO" in html


def test_competitive_intelligence_declares_demo(client: FlaskClient) -> None:
    html = _html(client, "/competitive-intelligence")

    assert "DEMO" in html
    assert "CURATED DEMO" in html


def test_proposal_factory_declares_planned_and_static_preview(client: FlaskClient) -> None:
    html = _html(client, "/proposal-factory")

    assert "PLANNED" in html
    assert "STATIC PREVIEW" in html


def test_the_intake_page_declares_live_and_verified_artifacts(client: FlaskClient) -> None:
    html = _html(client, "/")

    assert "LIVE" in html
    assert "VERIFIED ARTIFACTS" in html


@pytest.mark.parametrize("path", PREVIEW_PAGES)
def test_every_preview_page_states_its_status_outside_a_tooltip(
    client: FlaskClient, path: str
) -> None:
    html = _html(client, path)

    assert 'class="feature-strip"' in html
    assert "Target phase" in html
    assert "Current source" in html
    assert "title=" not in html.split('class="feature-strip"')[1].split("</section>")[0]


# --- 21: a free upload can only ever be quarantined ---------------------------


def test_a_free_upload_reports_quarantined_and_nothing_better(client: FlaskClient) -> None:
    response = client.post(
        "/uploads",
        data={
            "authorization_confirmed": "on",
            "files": (io.BytesIO(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer\n"), "probe.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 303
    html = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "QUARANTINED" in html
    for forbidden in ("CLEARED", "ALLOW", "Requirements", "Working package"):
        assert forbidden not in html


# --- 22-25: no page claims a connection or an autonomous run ------------------


@pytest.mark.parametrize("path", ALL_PAGES)
def test_no_page_claims_a_live_external_connection(client: FlaskClient, path: str) -> None:
    lowered = _html(client, path).lower()

    for claim in _CONNECTION_CLAIMS:
        assert claim not in lowered, f"{path} claims: {claim}"


@pytest.mark.parametrize("path", ALL_PAGES)
def test_no_page_claims_autonomous_behaviour(client: FlaskClient, path: str) -> None:
    lowered = _html(client, path).lower()

    for claim in _AUTONOMY_CLAIMS:
        assert claim not in lowered, f"{path} claims: {claim}"


def test_no_external_system_is_listed_as_a_connected_source(client: FlaskClient) -> None:
    """A system may be named as intended; it may never be named as connected."""
    external = ("crm", "salesforce", "teams", "outlook", "sharepoint", "archive", "public source")
    for path in PREVIEW_PAGES:
        html = _html(client, path)
        assert "Intended sources" in html, path
        connected = _fact_block(html, "Connected today").lower()
        for system in external:
            assert system not in connected, f"{path} lists {system} as connected"


# --- 26-27: the system assesses, a human decides ------------------------------


def test_qualification_never_presents_itself_as_the_decision(client: FlaskClient) -> None:
    html = _html(client, "/qualification")
    lowered = html.lower()

    assert "decides" in lowered or "decision" in lowered
    for forbidden in ("ai decision", "final decision by bidfusion", "automated go decision"):
        assert forbidden not in lowered


@pytest.mark.parametrize("path", PREVIEW_PAGES)
def test_every_preview_page_carries_a_human_review_note(client: FlaskClient, path: str) -> None:
    html = _html(client, path)

    assert 'class="feature-strip__note"' in html
    assert "review" in html.lower()


def test_every_registry_limitation_reaches_its_page(client: FlaskClient) -> None:
    """A recorded limitation that no page shows would be a hidden caveat."""
    by_key = {item.key: item for item in all_features()}
    for path, key in (
        ("/customer-intelligence", "customer_intelligence"),
        ("/competitive-intelligence", "competitive_intelligence"),
        ("/proposal-factory", "proposal_factory"),
        ("/review-approval", "review_approval"),
    ):
        html = _html(client, path)
        for limitation in by_key[key].limitations:
            assert limitation in html, f"{path} hides: {limitation}"


# --- the upload surface says exactly what it accepts --------------------------


def test_the_upload_surface_names_exactly_the_accepted_types(client: FlaskClient) -> None:
    html = _html(client, "/")

    assert "PDF, XLSX, TXT" in html
    # The fixture-package listing legitimately names the synthetic DOCX
    # file processed by the *run* lane; the upload policy itself must
    # still never claim Word or docx support.
    without_fixture_listing = html.replace("mtd-requirements.docx", "")
    for forbidden in ("Word", ".docx", "all formats", "All formats", "any format"):
        assert forbidden not in without_fixture_listing


def test_the_upload_surface_promises_no_automatic_analysis(client: FlaskClient) -> None:
    html = _html(client, "/")
    lowered = html.lower()

    assert "let ai do the analysis" not in lowered
    assert "turn it into actionable bid intelligence" in lowered
    assert "not security-cleared or processed automatically" in " ".join(html.split()).lower()
    assert AUTHORIZATION_STATEMENT in html


def test_the_upload_surface_names_the_phase_that_would_change_this(client: FlaskClient) -> None:
    html = _html(client, "/")

    assert "L1A-S2" in html


# --- 28-37: the existing lanes are unchanged ----------------------------------


def test_the_synthetic_lane_is_still_reachable_and_separate(client: FlaskClient) -> None:
    html = _html(client, "/")

    assert "Synthetic demo packages" in html
    assert "Upload authorized test RFP" in html
    assert 'action="/runs"' in html
    assert 'action="/uploads"' in html


def test_an_upload_without_confirmation_is_still_refused(client: FlaskClient) -> None:
    response = client.post(
        "/uploads",
        data={"files": (io.BytesIO(b"%PDF-1.4\ntrailer\n"), "probe.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "authorization" in response.get_data(as_text=True).lower()


def test_the_upload_lane_still_uses_post_redirect_get(client: FlaskClient) -> None:
    response = client.post(
        "/uploads",
        data={
            "authorization_confirmed": "on",
            "files": (io.BytesIO(b"%PDF-1.4\ntrailer\n"), "prg.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 303
    assert response.headers["Location"].startswith("/uploads/")


def test_the_model_gateway_is_recorded_as_built_but_disconnected(client: FlaskClient) -> None:
    """A gateway mention on the roadmap must not read as a gateway call."""
    assert "Governed Model Egress" in _html(client, "/architecture-roadmap")

    record = _html(client, "/features/governed_llm_egress")
    assert "REVIEW REQUIRED" in record
    assert "NOT CONNECTED" in record
    assert "Not connected to the pipeline" in record
    assert "No model call is made anywhere in this surface." in record
