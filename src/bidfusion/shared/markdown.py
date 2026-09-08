"""Sanitization of untrusted, document-derived text for Markdown output.

Everything extracted from customer documents — texts, quotes,
descriptions, filenames, sheet and cell labels — is untrusted. Rendered
Markdown must stay readable but must not be able to load external
resources, execute HTML, or fake its own document structure in a viewer.

The sanitizer therefore:

- decodes HTML entities exactly once (``html.unescape``), so
  entity-encoded characters — ``&lrm;``, ``&rlm;``, ``&ZeroWidthSpace;``,
  numeric forms like ``&#8203;``/``&#x202E;`` — become real characters
  *before* the invisibility filters run and can never smuggle bidi or
  zero-width controls past them;
- drops embedded control characters (C0/C1, DEL, Unicode line separators);
- drops every Unicode format character (category ``Cf``), which covers
  bidirectional controls (RLO/LRO/isolates), zero-width characters, and
  other invisible structure- or direction-changing characters;
- collapses newlines and tabs into single spaces, so untrusted text can
  never start a new line and thus never inject headings, lists,
  blockquotes, code fences, or table rows;
- backslash-escapes every Markdown/HTML-significant punctuation character
  (```` \\ ` * _ { } [ ] ( ) < > # | @ & ````), which neutralizes HTML
  tags, links, images (an image requires ``[``), autolinks, email
  autolinks (which require ``@``), *re-formed* HTML entities (which
  require ``&``), emphasis, inline code, and table cells while staying
  invisible in rendered output;
- breaks ``scheme://`` sequences (``http\\://``) so GFM-style bare
  autolinks cannot form; and
- breaks ``www.`` prefixes (``www\\.``) so GFM extended www-autolinks
  cannot form.

Characters that the single decode pass materializes (for example ``<``
from ``&#60;``) fall through the same escaping as directly supplied ones,
so decoding can never create new Markdown or HTML structure.
"""

from __future__ import annotations

import html
import re
import unicodedata

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u2028\u2029]")
_WHITESPACE = re.compile(r"[\r\n\t\f\v]+")
_MULTI_SPACE = re.compile(r" {2,}")
_ESCAPE = re.compile(r"([\\`*_{}\[\]()<>#|@&])")
_SCHEME_SEPARATOR = re.compile(r"://")
_WWW_PREFIX = re.compile(r"\b(www)\.", re.IGNORECASE)


def sanitize_markdown_text(text: str) -> str:
    """Return one safe, single-line Markdown text fragment."""
    cleaned = html.unescape(text)
    cleaned = _CONTROL_CHARS.sub("", cleaned)
    cleaned = "".join(char for char in cleaned if unicodedata.category(char) != "Cf")
    cleaned = _WHITESPACE.sub(" ", cleaned)
    cleaned = _ESCAPE.sub(r"\\\1", cleaned)
    cleaned = _SCHEME_SEPARATOR.sub("\\://", cleaned)
    cleaned = _WWW_PREFIX.sub(r"\1\\.", cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned).strip()
    return cleaned
