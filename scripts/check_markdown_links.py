"""Fail if any relative Markdown link in the repository points nowhere.

Checks all ``*.md`` files (excluding tooling directories) and validates
that relative link targets exist on disk. URL fragments (``#anchor``) are
stripped, external links are ignored.

Usage: ``python scripts/check_markdown_links.py``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def iter_markdown_files(root: Path) -> list[Path]:
    """Collect all Markdown files below root, skipping tooling directories."""
    return [
        path
        for path in sorted(root.rglob("*.md"))
        if not any(part in SKIP_DIRS for part in path.parts)
    ]


def find_broken_links(markdown_file: Path) -> list[str]:
    """Return all relative link targets of a file that do not exist."""
    broken: list[str] = []
    content = markdown_file.read_text(encoding="utf-8")
    for raw_target in LINK_PATTERN.findall(content):
        target = raw_target.strip("<>").split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        if not (markdown_file.parent / target).resolve().exists():
            broken.append(raw_target)
    return broken


def main() -> int:
    """Entry point; returns 1 if any broken link was found."""
    failures: list[str] = []
    files = iter_markdown_files(ROOT)
    for md_file in files:
        for target in find_broken_links(md_file):
            failures.append(f"{md_file.relative_to(ROOT)} -> {target}")
    if failures:
        print("Broken Markdown links found:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"OK: all relative links in {len(files)} Markdown files resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
