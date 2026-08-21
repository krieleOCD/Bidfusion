"""Architecture guards specific to the Reviewed Working Package slice.

The general review-domain guards (no golden store import, no claim
promotion, offline and shell-free, golden imports no bid code) already
cover the new package modules through the shared review-domain glob in
``test_review_architecture_guards``. This file pins the additional
boundaries of this slice: the package modules never couple to the
Domain-J working-package builder, the persisted artifact lives beside
the run (never inside the sealed run directory), and the package UI
never introduces compliance wording.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "src" / "bidfusion" / "bid_intelligence" / "review"
LOCAL_UI = ROOT / "src" / "bidfusion" / "local_ui"

_PACKAGE_MODULES = (
    REVIEW / "package.py",
    REVIEW / "package_builder.py",
    REVIEW / "package_store.py",
    LOCAL_UI / "reviewed_package_service.py",
)


def _full_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    full: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            full.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            full.add(node.module)
    return full


@pytest.mark.parametrize("path", _PACKAGE_MODULES, ids=lambda p: p.name)
def test_package_code_never_imports_the_working_package_domain(path: Path) -> None:
    """The reviewed package layers on review data; it never becomes a
    second, competing working-package builder."""
    offending = {
        name
        for name in _full_imports(path)
        if name == "bidfusion.working_package" or name.startswith("bidfusion.working_package.")
    }
    assert not offending, f"{path.name} imports {offending}"


@pytest.mark.parametrize("path", _PACKAGE_MODULES, ids=lambda p: p.name)
def test_package_code_never_references_the_run_manifest(path: Path) -> None:
    """Reviewed packages live beside the run; nothing here touches the
    sealed run directory's integrity manifest."""
    source = path.read_text(encoding="utf-8")
    assert "integrity-manifest" not in source, path.name
    assert "run_directory /" not in source, path.name


def test_the_package_section_template_claims_no_compliance() -> None:
    template = (LOCAL_UI / "templates" / "working_package.html").read_text(encoding="utf-8")
    start = template.index("reviewed-package-heading")
    section = template[start : template.index("</section>", start)].lower()
    for forbidden in ("compliant", "fulfilled", "guaranteed", "approved"):
        assert forbidden not in section, forbidden


def test_the_generation_route_accepts_no_client_fields() -> None:
    """The POST handler never reads the request body or query string: the
    server recomputes every authoritative value."""
    source = (LOCAL_UI / "reviewed_package_service.py").read_text(encoding="utf-8")
    for marker in ("request.", "form", "Mapping[str, str]"):
        assert marker not in source, marker


def test_review_states_stay_a_closed_coverage_vocabulary() -> None:
    """The package-level state enum only ever describes review coverage."""
    source = (REVIEW / "package.py").read_text(encoding="utf-8")
    match = re.search(
        r"class PackageReviewState\(StrEnum\):(.*?)(?:\nclass |\ndef )", source, re.DOTALL
    )
    assert match is not None
    members = set(re.findall(r'= "([A-Z_]+)"', match.group(1)))
    assert members == {"REVIEW_COMPLETE", "REVIEW_INCOMPLETE"}
