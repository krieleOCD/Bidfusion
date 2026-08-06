"""The interface has to work without a mouse, and without color.

A dashboard that encodes its meaning in a green bar is unreadable to
someone who cannot see the green, and a page whose meaning lives in a
tooltip is unreadable to someone who never hovers. These tests check the
properties that keep the product legible: real headings, named links,
tables with headers, states written in words next to their color, and a
layout that survives a narrow viewport.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from bidfusion.local_ui.app import create_app

STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "bidfusion" / "local_ui" / "static"

ALL_PAGES = (
    "/",
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
)


#: Elements that never have a closing tag, so the stack must not wait
#: for one.
_VOID_TAGS = frozenset({"meta", "link", "br", "hr", "img", "input", "path", "circle"})

_NAMED = frozenset({"a", "button"})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4"})


class _Collector(HTMLParser):
    """Enough of a parse to check structure without pulling in a library.

    Text is accumulated per open element and handed up to the parent on
    close, so the name of a link that wraps a span is the whole of what a
    reader sees rather than whichever fragment came last.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[tuple[str, str]] = []
        self.tables: list[dict[str, int]] = []
        self.links: list[tuple[dict[str, str | None], str]] = []
        self._open: list[tuple[str, dict[str, str | None], list[str]]] = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._count(tag)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._count(tag)
        if tag in _VOID_TAGS:
            return
        self._open.append((tag, dict(attrs), []))

    def _count(self, tag: str) -> None:
        if tag == "table":
            self.tables.append({"th": 0, "td": 0, "caption": 0})
        elif tag in {"th", "td", "caption"} and self.tables:
            self.tables[-1][tag] += 1

    def handle_endtag(self, tag: str) -> None:
        while self._open:
            name, attributes, buffer = self._open.pop()
            text = "".join(buffer).strip()
            if name in _HEADINGS:
                self.headings.append((name, text))
            elif name in _NAMED:
                self.links.append((attributes, text))
            if self._open:
                self._open[-1][2].append(f" {text} ")
            if name == tag:
                return

    def handle_data(self, data: str) -> None:
        if self._open:
            self._open[-1][2].append(data)


@pytest.fixture(scope="module")
def client() -> FlaskClient:
    return create_app().test_client()


def _parsed(client: FlaskClient, path: str) -> _Collector:
    response = client.get(path)
    assert response.status_code == 200, path
    collector = _Collector()
    collector.feed(response.get_data(as_text=True))
    return collector


# --- 55: headings say what a section is --------------------------------------


@pytest.mark.parametrize("path", ALL_PAGES)
def test_every_page_has_exactly_one_first_level_heading(client: FlaskClient, path: str) -> None:
    headings = _parsed(client, path).headings

    first_level = [text for level, text in headings if level == "h1"]
    assert len(first_level) == 1, f"{path} has {len(first_level)} h1 elements"
    assert first_level[0].strip(), f"{path} has an empty h1"


@pytest.mark.parametrize("path", ALL_PAGES)
def test_no_heading_is_empty_and_the_order_does_not_skip(client: FlaskClient, path: str) -> None:
    headings = _parsed(client, path).headings

    for level, text in headings:
        assert text.strip(), f"{path} has an empty {level}"

    seen = [int(level[1]) for level, _ in headings]
    for previous, current in zip(seen, seen[1:], strict=False):
        assert current <= previous + 1, f"{path} jumps from h{previous} to h{current}"


@pytest.mark.parametrize("path", ALL_PAGES)
def test_every_section_is_labelled(client: FlaskClient, path: str) -> None:
    """A landmark without a name is a landmark nobody can navigate to."""
    html = client.get(path).get_data(as_text=True)

    for section in re.findall(r"<section\b[^>]*>", html):
        assert "aria-label" in section or "class=" in section, f"{path}: {section}"
    for nav in re.findall(r"<nav\b[^>]*>", html):
        assert "aria-label" in nav, f"{path}: {nav}"


# --- 56: color is never the only signal --------------------------------------


@pytest.mark.parametrize("path", ALL_PAGES)
def test_every_status_badge_carries_words_as_well_as_a_color(
    client: FlaskClient, path: str
) -> None:
    html = client.get(path).get_data(as_text=True)

    for badge in re.findall(r'<span class="status-badge[^"]*">(.*?)</span>', html, re.DOTALL):
        text = re.sub(r"<svg.*?</svg>", "", badge, flags=re.DOTALL).strip()
        assert text, f"{path} has a status badge with no text"


@pytest.mark.parametrize("path", ALL_PAGES)
def test_every_meter_states_its_value_in_words(client: FlaskClient, path: str) -> None:
    """A bar of colored steps means nothing without its reading."""
    html = client.get(path).get_data(as_text=True)

    for meter in re.findall(r'<span class="meter"[^>]*>', html):
        assert "aria-label=" in meter, f"{path}: {meter}"
        assert 'role="img"' in meter, f"{path}: {meter}"

    for label in re.findall(r'<span class="meter" role="img" aria-label="([^"]*)"', html):
        assert re.search(r"\d of \d", label), f"{path}: meter label {label!r}"


def test_no_meaning_is_carried_by_a_tooltip_alone(client: FlaskClient) -> None:
    """`title` is invisible on touch and to most assistive technology."""
    for path in ALL_PAGES:
        html = client.get(path).get_data(as_text=True)
        body = html.split("<body", 1)[1]
        assert " title=" not in body, path


# --- 57: every control has a name --------------------------------------------


@pytest.mark.parametrize("path", ALL_PAGES)
def test_every_link_and_button_has_an_accessible_name(client: FlaskClient, path: str) -> None:
    for attributes, text in _parsed(client, path).links:
        name = text or attributes.get("aria-label") or ""
        assert name.strip(), f"{path} has an unnamed link or button: {attributes}"


@pytest.mark.parametrize("path", ALL_PAGES)
def test_decorative_icons_are_hidden_from_assistive_technology(
    client: FlaskClient, path: str
) -> None:
    html = client.get(path).get_data(as_text=True)

    for svg in re.findall(r"<svg\b[^>]*>", html):
        assert 'aria-hidden="true"' in svg, f"{path}: {svg}"


# --- 58: tables are tables ---------------------------------------------------


@pytest.mark.parametrize("path", ALL_PAGES)
def test_every_table_has_headers_and_a_caption(client: FlaskClient, path: str) -> None:
    for index, table in enumerate(_parsed(client, path).tables):
        assert table["th"] > 0, f"{path} table {index} has no header cells"
        assert table["caption"] > 0, f"{path} table {index} has no caption"


@pytest.mark.parametrize("path", ALL_PAGES)
def test_every_header_cell_declares_its_scope(client: FlaskClient, path: str) -> None:
    html = client.get(path).get_data(as_text=True)

    for cell in re.findall(r"<th\b[^>]*>", html):
        assert "scope=" in cell, f"{path}: {cell}"


# --- 59, 60: structure and stated status, not implied ------------------------


@pytest.mark.parametrize("path", ALL_PAGES)
def test_the_page_language_and_viewport_are_declared(client: FlaskClient, path: str) -> None:
    html = client.get(path).get_data(as_text=True)

    assert '<html lang="en"' in html, path
    assert 'name="viewport"' in html, path
    assert "width=device-width" in html, path


def test_the_layout_adapts_to_narrow_viewports() -> None:
    css = (STATIC_DIR / "ui.css").read_text(encoding="utf-8")

    assert "@media (min-width: 1000px)" in css
    assert "@media (max-width: 700px)" in css
    assert "grid-template-columns: repeat(auto-fill" in css
    assert "overflow-x: auto" in css


def test_wide_content_scrolls_inside_its_own_container() -> None:
    """A table must not push the whole page sideways."""
    css = (STATIC_DIR / "ui.css").read_text(encoding="utf-8")

    table_wrap = css.split(".table-wrap", 1)[1].split("}", 1)[0]
    assert "overflow-x: auto" in table_wrap


def test_focus_remains_visible_on_dark_and_light_surfaces() -> None:
    tokens = (STATIC_DIR / "tokens.css").read_text(encoding="utf-8")
    css = (STATIC_DIR / "ui.css").read_text(encoding="utf-8")

    assert ":focus-visible" in tokens
    assert "outline: 2px solid" in tokens
    assert "--color-focus-inverse" in tokens
    assert "outline-color: var(--color-focus-inverse)" in css
