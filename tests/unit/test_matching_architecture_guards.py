"""Architecture guards for the requirement-to-golden-knowledge bridge.

The bridge lives in the bid domain and depends on the golden domain —
never the other way around, and never on transports, models, or the UI.
AST-based import scanning keeps the checks robust against prose that
merely mentions a forbidden concept.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from bidfusion.bid_intelligence.matching.contracts import (
    KnowledgeAssessmentResult,
    RequirementKnowledgeAssessment,
)
from bidfusion.golden_dataset.contracts import MatchCandidate, RequirementCandidate

ROOT = Path(__file__).resolve().parents[2]
MATCHING = ROOT / "src" / "bidfusion" / "bid_intelligence" / "matching"
GOLDEN = ROOT / "src" / "bidfusion" / "golden_dataset"
LOCAL_UI = ROOT / "src" / "bidfusion" / "local_ui"

_MATCHING_MODULES = sorted(MATCHING.glob("*.py"))

#: bidfusion packages the bridge must never import: no UI, no upload or
#: run lifecycle, no LLM gateway, no pipeline orchestration.
_FORBIDDEN_BIDFUSION_PACKAGES = frozenset(
    {
        "bidfusion.bidrun",
        "bidfusion.local_ui",
        "bidfusion.llm_gateway",
        "bidfusion.intake",
        "bidfusion.orchestration",
        "bidfusion.working_package",
        "bidfusion.document_understanding",
        "bidfusion.security",
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


@pytest.mark.parametrize("path", _MATCHING_MODULES, ids=lambda p: p.name)
def test_the_bridge_never_imports_ui_transport_or_lifecycle_code(path: Path) -> None:
    _, full = _imports(path)
    offending = {
        name
        for name in full
        if any(name == pkg or name.startswith(f"{pkg}.") for pkg in _FORBIDDEN_BIDFUSION_PACKAGES)
    }
    assert not offending, f"{path.name} imports forbidden packages: {offending}"


@pytest.mark.parametrize("path", _MATCHING_MODULES, ids=lambda p: p.name)
def test_the_bridge_stays_offline_and_shell_free(path: Path) -> None:
    roots, _ = _imports(path)
    offending = roots & _FORBIDDEN_RUNTIME_ROOTS
    assert not offending, f"{path.name} imports forbidden runtime roots: {offending}"


@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.py")), ids=lambda p: p.name)
def test_the_golden_domain_still_never_imports_the_bid_domain(path: Path) -> None:
    """The bridge points from bid into golden; golden stays independent."""
    _, full = _imports(path)
    offending = {
        name
        for name in full
        if name == "bidfusion.bid_intelligence" or name.startswith("bidfusion.bid_intelligence.")
    }
    assert not offending, f"{path.name} imports the bid domain: {offending}"


def test_no_bid_identifier_was_added_to_the_golden_matching_contracts() -> None:
    """Golden matching inputs and verdicts stay free of bid-path fields."""
    for model in (RequirementCandidate, MatchCandidate):
        assert "bid_id" not in model.model_fields, model.__name__
        assert "run_id" not in model.model_fields, model.__name__


def test_the_assessment_contracts_carry_both_provenances_unmerged() -> None:
    fields = RequirementKnowledgeAssessment.model_fields
    assert "requirement_source" in fields
    assert "evidence_refs" in fields
    assert "store_state" in KnowledgeAssessmentResult.model_fields


def test_the_ui_assessment_service_contains_no_matching_logic() -> None:
    """The UI projects assessments; it never matches or scans store files."""
    path = LOCAL_UI / "knowledge_assessment_service.py"
    _, full = _imports(path)

    assert "bidfusion.golden_dataset.matching" not in full
    assert "bidfusion.golden_dataset.store" not in full
    source = path.read_text(encoding="utf-8")
    assert "match_requirement" not in source
    assert "re.compile" not in source


def test_the_bridge_introduces_no_circular_dependency() -> None:
    """Follow every import out of the bridge; none lands back in bid_intelligence
    via the golden domain, and none reaches the UI or the gateway."""
    src = ROOT / "src"
    seen: set[str] = set()
    pending = ["bidfusion.bid_intelligence.matching.assessment"]
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = src / Path(*module.split(".")).with_suffix(".py")
        if not path.is_file():
            path = src / Path(*module.split(".")) / "__init__.py"
        if not path.is_file():
            continue
        _, full = _imports(path)
        pending.extend(name for name in full if name.startswith("bidfusion."))

    golden_modules = {name for name in seen if name.startswith("bidfusion.golden_dataset")}
    assert golden_modules, "the bridge should reach the golden domain"
    for module in golden_modules:
        path = src / Path(*module.split(".")).with_suffix(".py")
        if not path.is_file():
            path = src / Path(*module.split(".")) / "__init__.py"
        _, full = _imports(path)
        assert not any(name.startswith("bidfusion.bid_intelligence") for name in full), module

    assert not any(name.startswith("bidfusion.local_ui") for name in seen)
    assert not any(name.startswith("bidfusion.llm_gateway") for name in seen)
