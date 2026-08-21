"""Architecture guards for the Golden Dataset domain (ADR-0009).

The golden path must stay separated from the bid/RFP path and must stay
offline: no BidRun, no upload flow, no UI dependency, no LLM gateway,
no network client, no subprocess. AST-based import scanning keeps these
checks robust against comments and docstrings that merely *mention* a
forbidden concept.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "src" / "bidfusion" / "golden_dataset"

_GOLDEN_MODULES = sorted(GOLDEN.glob("*.py"))

#: bidfusion packages the golden domain must never import.
_FORBIDDEN_BIDFUSION_PACKAGES = frozenset(
    {
        "bidfusion.bidrun",
        "bidfusion.local_ui",
        "bidfusion.llm_gateway",
        "bidfusion.intake",
        "bidfusion.orchestration",
        "bidfusion.working_package",
    }
)

#: stdlib/third-party roots that would mean network, shell, or subprocess.
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
        "os",  # os.system/exec*; golden code uses pathlib and secure_io only
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


def test_golden_dataset_package_has_the_expected_modules() -> None:
    names = {path.name for path in _GOLDEN_MODULES}
    assert {
        "__init__.py",
        "contracts.py",
        "classification.py",
        "inventory.py",
        "ingestion.py",
        "claims.py",
        "matching.py",
        "store.py",
    } <= names


@pytest.mark.parametrize("path", _GOLDEN_MODULES, ids=lambda p: p.name)
def test_golden_dataset_never_imports_the_bid_or_ui_path(path: Path) -> None:
    _, full = _imports(path)
    offending = {
        name
        for name in full
        if any(name == pkg or name.startswith(f"{pkg}.") for pkg in _FORBIDDEN_BIDFUSION_PACKAGES)
    }
    assert not offending, f"{path.name} imports forbidden packages: {offending}"


@pytest.mark.parametrize("path", _GOLDEN_MODULES, ids=lambda p: p.name)
def test_golden_dataset_stays_offline_and_shell_free(path: Path) -> None:
    roots, _ = _imports(path)
    offending = roots & _FORBIDDEN_RUNTIME_ROOTS
    assert not offending, f"{path.name} imports forbidden runtime roots: {offending}"


def _other_golden_tests() -> list[Path]:
    """Every golden test module except this guard file itself."""
    return [
        path
        for path in sorted((ROOT / "tests").rglob("test_golden_*.py"))
        if path.name != Path(__file__).name
    ]


def test_golden_tests_never_read_the_real_source_directory() -> None:
    """No test may reference the local real-dataset location."""
    forbidden = ("Managed Threat Detection Service", "/Context/")
    for path in _other_golden_tests():
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{path.name} references the real dataset location"


def test_golden_tests_do_not_depend_on_committed_demo_fixtures() -> None:
    forbidden = ("fixtures/", "product_demo")
    for path in _other_golden_tests():
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{path.name} depends on committed demo fixtures"
