"""Architecture guards for the bid-side human review domain.

The review of a bid assessment must be unable to touch golden knowledge
state: no golden store import, no claim confirmation helpers, and the
golden domain still knows nothing about bid review code. The review
path also stays offline and shell-free like every other bid module.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "src" / "bidfusion" / "bid_intelligence" / "review"
GOLDEN = ROOT / "src" / "bidfusion" / "golden_dataset"
LOCAL_UI = ROOT / "src" / "bidfusion" / "local_ui"

_REVIEW_MODULES = sorted(REVIEW.glob("*.py"))
_UI_REVIEW_MODULES = (
    LOCAL_UI / "knowledge_assessment_service.py",
    LOCAL_UI / "knowledge_review_service.py",
    LOCAL_UI / "reviewed_package_service.py",
)

_FORBIDDEN_RUNTIME_ROOTS = frozenset(
    {
        "socket",
        "ssl",
        "urllib",
        "http",
        "httpx",
        "requests",
        "aiohttp",
        "websockets",
        "subprocess",
        "os",
        "pty",
        "ftplib",
        "smtplib",
    }
)


def _imports(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    full: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
                full.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
            full.add(node.module)
    return roots, full


@pytest.mark.parametrize("path", _REVIEW_MODULES, ids=lambda p: p.name)
def test_review_domain_never_imports_the_golden_store(path: Path) -> None:
    _, full = _imports(path)
    assert "bidfusion.golden_dataset.store" not in full, path.name


@pytest.mark.parametrize("path", (*_REVIEW_MODULES, *_UI_REVIEW_MODULES), ids=lambda p: p.name)
def test_no_review_code_can_promote_a_golden_claim(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    assert "confirm_claim" not in source, path.name
    assert "reject_claim" not in source, path.name
    assert "write_claims" not in source, path.name


@pytest.mark.parametrize("path", _REVIEW_MODULES, ids=lambda p: p.name)
def test_review_domain_stays_offline_and_shell_free(path: Path) -> None:
    roots, full = _imports(path)
    assert not roots & _FORBIDDEN_RUNTIME_ROOTS, path.name
    forbidden = ("bidfusion.local_ui", "bidfusion.llm_gateway", "bidfusion.bidrun")
    offending = {
        name for name in full if any(name == pkg or name.startswith(f"{pkg}.") for pkg in forbidden)
    }
    assert not offending, f"{path.name} imports {offending}"


@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.py")), ids=lambda p: p.name)
def test_the_golden_domain_still_never_imports_bid_review_code(path: Path) -> None:
    _, full = _imports(path)
    offending = {name for name in full if name.startswith("bidfusion.bid_intelligence")}
    assert not offending, f"{path.name} imports {offending}"


def _code_without_docstrings(path: Path) -> str:
    """Source with docstrings removed — prose may name what code must avoid."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    excluded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            first = body[0]
            excluded.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    lines = source.splitlines()
    return "\n".join(line for number, line in enumerate(lines, start=1) if number not in excluded)


def test_review_records_never_live_under_the_golden_runtime_store() -> None:
    """The store layout is bid-side; no code points at runtime golden data."""
    for path in (*_REVIEW_MODULES, *_UI_REVIEW_MODULES):
        code = _code_without_docstrings(path)
        assert "golden_dataset/" not in code.replace("bidfusion.golden_dataset", ""), path.name
        assert "runtime" not in code, path.name
