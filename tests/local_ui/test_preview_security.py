"""The security boundaries hold across the new surfaces too.

Adding eleven pages to an application is the moment its guarantees
quietly stop applying to some of them. These tests check the boundaries
on every product page rather than on a sample: the same headers, the
same policy, no remote resource, no network, no model gateway, no
connector, no environment value, and no reach into anything a run or an
upload owns.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from bidfusion.local_ui.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "src" / "bidfusion" / "local_ui" / "static"

EXPECTED_CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)

ALL_PAGES = (
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
    "/features/customer_intelligence",
    "/features/rfp_intake",
)


@pytest.fixture(scope="module")
def app() -> Flask:
    return create_app()


@pytest.fixture(scope="module")
def client(app: Flask) -> FlaskClient:
    return app.test_client()


# --- 45, 46: the same headers and the same policy, everywhere ----------------


@pytest.mark.parametrize("path", ALL_PAGES)
def test_every_page_carries_the_security_headers(client: FlaskClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200, path
    assert response.headers["Content-Security-Policy"] == EXPECTED_CSP
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"


def test_the_policy_forbids_script_and_every_remote_origin() -> None:
    assert "default-src 'none'" in EXPECTED_CSP
    assert "script-src" not in EXPECTED_CSP
    assert "unsafe-inline" not in EXPECTED_CSP
    assert "unsafe-eval" not in EXPECTED_CSP
    assert "*" not in EXPECTED_CSP


def test_error_responses_keep_the_headers_too(client: FlaskClient) -> None:
    for path in ("/definitely-not-a-route", "/features/nope", "/compliance?scenario=nope"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.headers["Content-Security-Policy"] == EXPECTED_CSP


# --- 47: no remote asset, and no inline style the policy would block ---------


@pytest.mark.parametrize("path", ALL_PAGES)
def test_no_page_references_a_remote_resource(client: FlaskClient, path: str) -> None:
    html = client.get(path).get_data(as_text=True)

    for marker in ("https://", "http://", "//cdn", "@import", "data:"):
        assert marker not in html, f"{path} references {marker}"


@pytest.mark.parametrize("path", ALL_PAGES)
def test_no_page_uses_an_inline_style_attribute(client: FlaskClient, path: str) -> None:
    """`style-src 'self'` blocks inline styles, so meters use fixed classes."""
    html = client.get(path).get_data(as_text=True)

    assert "style=" not in html, path
    assert "<style" not in html, path


def test_the_stylesheets_load_nothing_from_anywhere() -> None:
    for name in ("tokens.css", "ui.css"):
        css = (STATIC_DIR / name).read_text(encoding="utf-8")
        assert "@import" not in css
        assert "url(" not in css
        assert "http" not in css


# --- 48, 49, 50: no network, no model gateway, no connector ------------------


def test_rendering_every_page_opens_no_socket(client: FlaskClient) -> None:
    """The session-wide guard makes an accidental call fail loudly."""
    for path in ALL_PAGES:
        assert client.get(path).status_code == 200, path

    with pytest.raises(RuntimeError, match="network access is disabled"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_no_preview_module_can_construct_a_transport_or_a_client() -> None:
    from bidfusion.local_ui import preview_service, preview_viewmodels, scenario_registry

    for module in (preview_service, preview_viewmodels, scenario_registry):
        for forbidden in ("urllib", "httpx", "requests", "socket", "subprocess"):
            assert not hasattr(module, forbidden), (module.__name__, forbidden)


# --- 51, 52: no environment value and no secret reaches a response -----------


@pytest.mark.parametrize("path", ALL_PAGES)
def test_no_environment_value_appears_in_a_response(
    client: FlaskClient, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIDFUSION_PROBE_VALUE", "MUST-NOT-LEAK-0BADC0DE")

    html = client.get(path).get_data(as_text=True)

    assert "MUST-NOT-LEAK-0BADC0DE" not in html
    assert "BIDFUSION_" not in html
    for name in ("HOME", "PATH", "USER"):
        value = os.environ.get(name)
        if value and len(value) > 8:
            assert value not in html, f"{path} leaks ${name}"


@pytest.mark.parametrize("path", ALL_PAGES)
def test_no_page_shows_a_filesystem_path_of_this_machine(client: FlaskClient, path: str) -> None:
    html = client.get(path).get_data(as_text=True)

    assert str(REPO_ROOT) not in html
    assert "/Users/" not in html
    assert "/tmp/" not in html


# --- 53: no raw exception ever reaches a reader ------------------------------


def test_a_broken_scenario_file_produces_a_static_message(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bidfusion.local_ui import scenario_registry

    def exploding(_key: str) -> object:
        raise scenario_registry.ScenarioError(scenario_registry.OPERATOR_SAFE_SCENARIO_MESSAGE)

    monkeypatch.setattr(scenario_registry, "load_scenario", exploding)

    response = client.get("/customer-intelligence")

    assert response.status_code == 500
    html = response.get_data(as_text=True)
    assert scenario_registry.OPERATOR_SAFE_SCENARIO_MESSAGE in html
    assert "Traceback" not in html
    assert "ValidationError" not in html
    assert "JSONDecodeError" not in html


def test_no_page_ever_shows_a_traceback(client: FlaskClient) -> None:
    for path in (*ALL_PAGES, "/features/nope", "/compliance?scenario=nope"):
        html = client.get(path).get_data(as_text=True)
        assert "Traceback" not in html, path
        assert 'File "' not in html, path


# --- 54: preview routes read nothing a run or an upload owns -----------------


def test_preview_routes_read_no_run_and_no_quarantine_directory(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any attempt to open a file outside the demonstration data fails."""
    opened: list[str] = []
    real_open = Path.read_text

    def watched(self: Path, *args: object, **kwargs: object) -> str:
        opened.append(str(self))
        return real_open(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", watched)

    for path in (
        "/customer-intelligence",
        "/competitive-intelligence",
        "/review-approval",
        "/proposal-factory",
    ):
        assert client.get(path).status_code == 200, path

    demo_root = str(REPO_ROOT / "fixtures" / "product_demo")
    for touched in opened:
        assert touched.startswith(demo_root), f"a preview page read {touched}"


def test_preview_pages_offer_no_artifact_download(client: FlaskClient) -> None:
    for path in ALL_PAGES:
        html = client.get(path).get_data(as_text=True)
        assert "/artifacts/" not in html, path
        assert "working-package.json" not in html, path


def test_the_quarantine_lane_is_untouched_by_the_preview_lane(client: FlaskClient) -> None:
    """A preview page cannot start, clear, or read an upload."""
    for path in ALL_PAGES:
        html = client.get(path).get_data(as_text=True)
        assert "/uploads/" not in html, path
