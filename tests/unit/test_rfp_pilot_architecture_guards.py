"""Architecture guards for the RFP API pilot package.

Structural rules enforced by AST inspection:

- the pilot talks to models ONLY through the provider-neutral gateway
  port (no provider SDKs, no network/process modules, no direct
  Anthropic adapter, no transport construction of its own);
- the golden domain and the deterministic bridge stay independent of the
  pilot (and the golden domain of the gateway);
- the existing pipeline packages never import the pilot — the
  deterministic path is unchanged;
- the pilot store cannot persist prompts (it never sees them).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "bidfusion"
PILOT = SRC / "rfp_api_pilot"

_EXPECTED_PILOT_MODULES = {
    "__init__.py",
    "comparison.py",
    "contracts.py",
    "evaluation.py",
    "golden_paths.py",
    "metrics.py",
    "pilot_run.py",
    "presend_check.py",
    "prompt.py",
    "service.py",
    "store.py",
}

_FORBIDDEN_PROVIDER_SDK_ROOTS = frozenset(
    {
        "openai",
        "anthropic",
        "vertexai",
        "google",
        "cohere",
        "mistralai",
        "boto3",
        "langchain",
        "llama_index",
        "semantic_kernel",
    }
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
        "pty",
        "ftplib",
        "smtplib",
    }
)

#: Packages whose behavior must stay byte-identical without the pilot.
_PIPELINE_DIRS = [
    SRC / "security",
    SRC / "bidrun",
    SRC / "orchestration",
    SRC / "extraction",
    SRC / "document_understanding",
    SRC / "intake",
    SRC / "normalization",
    SRC / "working_package",
    SRC / "golden_dataset",
    SRC / "bid_intelligence",
    SRC / "local_ui",
]


def _python_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*.py") if "__pycache__" not in path.parts)


def _imported_module_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _imported_full_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_pilot_module_list_is_pinned() -> None:
    found = {path.name for path in _python_files(PILOT)}
    assert found == _EXPECTED_PILOT_MODULES


def test_pilot_never_imports_provider_sdks_or_network_modules() -> None:
    for path in _python_files(PILOT):
        roots = _imported_module_roots(path)
        assert not roots & _FORBIDDEN_PROVIDER_SDK_ROOTS, path
        assert not roots & _FORBIDDEN_RUNTIME_ROOTS, path


def test_pilot_never_uses_the_direct_anthropic_adapter_or_the_old_port() -> None:
    for path in _python_files(PILOT):
        names = _imported_full_module_names(path)
        assert "bidfusion.llm_gateway.anthropic" not in names, path
        assert "bidfusion.ports" not in names, path
        assert "bidfusion.llm_gateway.fake" not in names, path


def test_pilot_never_constructs_the_real_transport_itself() -> None:
    for path in _python_files(PILOT):
        assert "UrllibOrangeProxyTransport(" not in path.read_text(encoding="utf-8"), path


def test_golden_domain_stays_free_of_pilot_and_gateway() -> None:
    for path in _python_files(SRC / "golden_dataset"):
        names = {
            name.split(".")[1]
            for name in _imported_full_module_names(path)
            if name.startswith("bidfusion.")
        }
        assert "rfp_api_pilot" not in names, path
        assert "llm_gateway" not in names, path


def test_existing_pipeline_packages_never_import_the_pilot() -> None:
    for directory in _PIPELINE_DIRS:
        for path in _python_files(directory):
            names = _imported_full_module_names(path)
            pilot_imports = {name for name in names if "rfp_api_pilot" in name}
            assert not pilot_imports, path


def test_pilot_store_cannot_see_the_prompt() -> None:
    names = _imported_full_module_names(PILOT / "store.py")
    assert "bidfusion.rfp_api_pilot.prompt" not in names


def test_pilot_llm_egress_is_the_gateway_port_only() -> None:
    """Only the workflow entry constructs the adapter; everything else is injected."""
    for path in _python_files(PILOT):
        if path.name == "pilot_run.py":
            continue
        assert "OrangeProxyAdapter" not in path.read_text(encoding="utf-8"), path
