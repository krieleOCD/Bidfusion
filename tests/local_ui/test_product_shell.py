"""The shared shell: one header, one navigation, no dead links.

Every product page carries the same product header, the same navigation,
and — where the page maps to a feature — a visible status context. The
crawl at the end of this module follows every link the interface renders
and fails on the first one that does not resolve.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from flask import Flask, url_for
from flask.testing import FlaskClient

from bidfusion.local_ui.app import create_app
from bidfusion.local_ui.feature_registry import Visibility, all_features
from bidfusion.local_ui.product_shell import (
    NAV_WORLDS,
    PREVIEW_LABEL,
    STAGE_LABEL,
    NavWorld,
    build_shell_context,
    world_for_endpoint,
)

STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "bidfusion" / "local_ui" / "static"

#: Every page a reader can reach without first starting a run.
PRODUCT_PAGES = (
    "/",
    "/rfp-intelligence",
    "/overview",
    "/architecture-roadmap",
    "/customer-intelligence",
    "/qualification",
    "/compliance",
    "/capability-fit",
    "/competitive-intelligence",
    "/win-strategy",
    "/proposal-factory",
    "/review-approval",
)

_HREF = re.compile(r'href="([^"]+)"')


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


# --- 11. one product header, everywhere --------------------------------------


@pytest.mark.parametrize("path", PRODUCT_PAGES)
def test_every_product_page_carries_the_product_header(client: FlaskClient, path: str) -> None:
    html = _html(client, path)

    assert "Orange Cyberdefense" in html
    assert "BidFusion" in html
    assert PREVIEW_LABEL in html
    assert STAGE_LABEL in html
    assert 'class="app-header"' in html


@pytest.mark.parametrize("path", PRODUCT_PAGES)
def test_every_product_page_carries_the_non_production_notice(
    client: FlaskClient, path: str
) -> None:
    html = _html(client, path)

    assert "Not approved for production customer data" in html


def test_the_header_never_claims_a_production_status(client: FlaskClient) -> None:
    for path in PRODUCT_PAGES:
        html = _html(client, path)
        for forbidden in ("Production ready", "Production release", "GA release"):
            assert forbidden not in html, path


def test_error_pages_keep_the_navigation(client: FlaskClient) -> None:
    response = client.get("/definitely-not-a-route")

    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert 'class="product-nav"' in html
    assert "Architecture and Roadmap" in html


# --- 12. every top-level area is clickable -----------------------------------


@pytest.mark.parametrize("world", NAV_WORLDS, ids=lambda world: world.key)
def test_every_navigation_world_is_reachable(
    app: Flask, client: FlaskClient, world: NavWorld
) -> None:
    with app.test_request_context():
        url = url_for(world.endpoint)

    assert client.get(url).status_code == 200


def test_every_module_page_is_reachable_from_the_overview(client: FlaskClient) -> None:
    html = _html(client, "/overview")

    for item in all_features():
        if item.visibility is Visibility.MODULE_SECTION:
            continue
        assert f'/features/{item.key}"' in html, item.key


def test_every_feature_record_is_linked_from_the_roadmap(client: FlaskClient) -> None:
    html = _html(client, "/architecture-roadmap")

    for item in all_features():
        assert f'/features/{item.key}"' in html, item.key


# --- 13. the active area is visible ------------------------------------------


def test_the_active_world_is_marked_for_sighted_and_assistive_readers(
    client: FlaskClient,
) -> None:
    html = _html(client, "/competitive-intelligence")

    assert "product-nav__link--active" in html
    assert 'aria-current="page"' in html


def test_the_shell_knows_which_world_a_page_belongs_to() -> None:
    assert world_for_endpoint("index") is not None
    assert world_for_endpoint("show_working_package") is not None
    assert world_for_endpoint("win_strategy") is not None
    assert world_for_endpoint("static") is None
    assert world_for_endpoint(None) is None


def test_an_unknown_endpoint_still_gets_a_complete_shell() -> None:
    shell = build_shell_context(None)

    assert shell.active_world_key is None
    assert shell.feature_status is None
    assert len(shell.worlds) == len(NAV_WORLDS)
    assert all(not world.is_active for world in shell.worlds)


def test_run_pages_stay_inside_the_rfp_intelligence_world(client: FlaskClient) -> None:
    started = client.post("/runs", data={"package": "rfp-minimal"})
    html = client.get(started.headers["Location"]).get_data(as_text=True)

    assert "Intake and Runs" in html
    assert 'class="module-nav"' in html


# --- 14. an unknown feature key is a plain 404 -------------------------------


def test_an_unknown_feature_key_is_a_safe_404(client: FlaskClient) -> None:
    response = client.get("/features/does-not-exist")

    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert "Traceback" not in html
    assert "does-not-exist" not in html


def test_a_feature_key_cannot_reach_outside_the_registry(client: FlaskClient) -> None:
    for probe in ("../start", "..%2fstart", "start.html", "%2e%2e"):
        assert client.get(f"/features/{probe}").status_code == 404


# --- 15. keyboard navigation stays visible -----------------------------------


def test_focus_is_visible_and_the_skip_link_exists(client: FlaskClient) -> None:
    html = _html(client, "/overview")

    assert 'class="skip-link"' in html
    assert 'href="#main"' in html
    assert 'id="main"' in html

    stylesheets = (STATIC_DIR / "tokens.css").read_text(encoding="utf-8") + (
        STATIC_DIR / "ui.css"
    ).read_text(encoding="utf-8")
    assert ":focus-visible" in stylesheets
    assert "outline" in stylesheets


def test_navigation_uses_ordinary_links_and_needs_no_script(client: FlaskClient) -> None:
    for path in PRODUCT_PAGES:
        html = _html(client, path)
        assert "<script" not in html
        assert "onclick=" not in html
        assert "javascript:" not in html


# --- 16. no dead and no empty links ------------------------------------------


def test_no_rendered_link_is_empty_or_broken(client: FlaskClient) -> None:
    """Follow every link the product pages render; all must resolve."""
    checked: set[str] = set()
    for path in PRODUCT_PAGES:
        for href in _HREF.findall(_html(client, path)):
            assert href.strip(), f"empty href on {path}"
            if href.startswith("#") or href in checked:
                continue
            checked.add(href)
            assert href.startswith("/"), f"non-local link {href} on {path}"
            assert client.get(href).status_code == 200, f"{href} (linked from {path})"

    assert len(checked) > len(PRODUCT_PAGES)


def test_product_pages_reference_no_remote_resource(client: FlaskClient) -> None:
    for path in PRODUCT_PAGES:
        html = _html(client, path)
        assert "https://" not in html, path
        assert "http://" not in html, path
        assert "//cdn" not in html, path
