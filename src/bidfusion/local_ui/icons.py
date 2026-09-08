"""Local inline SVG icons in the design system's geometric 2px-stroke style.

The Orange Cyberdefense design system ships no icon font and links a
stroke icon set from a CDN; this UI must not load remote assets, so the
handful of needed glyphs are embedded here as static, local SVG markup
(24x24 viewBox, 2px stroke, ``currentColor``). Icons are decorative:
they always accompany visible text and are hidden from assistive
technology.
"""

from __future__ import annotations

from markupsafe import Markup

_ICON_PATHS: dict[str, str] = {
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "alert": (
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 '
        '1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>'
    ),
    "shield": (
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 '
        "1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 "
        '1 0 0 1 1 1z"/>'
    ),
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "file": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "download": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>'
    ),
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "minus": '<path d="M5 12h14"/>',
    "unlink": (
        '<path d="m8.5 8.5-2 2a4.95 4.95 0 0 0 7 7l2-2"/>'
        '<path d="m15.5 15.5 2-2a4.95 4.95 0 0 0-7-7l-2 2"/><path d="m2 2 20 20"/>'
    ),
    "target": (
        '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/>'
        '<circle cx="12" cy="12" r="2"/>'
    ),
    "layers": ('<path d="m12 2 9 5-9 5-9-5z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>'),
    "users": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
        '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "list": (
        '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/>'
        '<path d="M3 12h.01"/><path d="M3 18h.01"/>'
    ),
    "map": ('<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15"/><path d="M15 6v15"/>'),
    "octagon-x": (
        '<path d="M7.86 2h8.28L22 7.86v8.28L16.14 22H7.86L2 16.14V7.86z"/>'
        '<path d="m15 9-6 6"/><path d="m9 9 6 6"/>'
    ),
}


def icon(name: str) -> Markup:
    """Render one known icon as decorative inline SVG markup.

    Unknown names fail loudly at render time; every icon name used in a
    template is exercised by the test suite.
    """
    paths = _ICON_PATHS[name]
    return Markup(
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true" focusable="false">{paths}</svg>'
    )


def known_icons() -> tuple[str, ...]:
    """All available icon names (for tests)."""
    return tuple(sorted(_ICON_PATHS))
