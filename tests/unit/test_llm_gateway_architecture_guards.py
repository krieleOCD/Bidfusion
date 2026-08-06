"""Architecture guards for the Orange LLM Proxy Gateway slice (ADR-0013).

AST-based import scanning is used instead of plain-text grep wherever
import boundaries are being enforced, so the checks survive reformatting,
comments, and string literals that merely mention a module name.
"""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from bidfusion.llm_gateway.errors import LlmGatewayErrorCode
from bidfusion.llm_gateway.orange_proxy import OrangeProxyAdapter
from bidfusion.llm_gateway.port import (
    LlmMessage,
    LlmMessageRole,
    ModelPolicyKey,
    StructuredLlmOperation,
    StructuredLlmRequest,
    SyntheticGatewayResult,
)
from bidfusion.llm_gateway.secrets import EnvironmentSecretResolver
from bidfusion.llm_gateway.settings import load_orange_proxy_settings
from bidfusion.schemas.common import DataClassification

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "bidfusion"
TESTS = ROOT / "tests"

_NEW_LLM_GATEWAY_MODULES = [
    SRC / "llm_gateway" / "port.py",
    SRC / "llm_gateway" / "policy.py",
    SRC / "llm_gateway" / "settings.py",
    SRC / "llm_gateway" / "errors.py",
    SRC / "llm_gateway" / "fake.py",
    SRC / "llm_gateway" / "orange_proxy.py",
]

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

_NO_LLM_GATEWAY_IMPORT_DIRS = [
    SRC / "security",
    SRC / "bidrun",
    SRC / "orchestration",
    SRC / "extraction",
    SRC / "document_understanding",
    SRC / "intake",
    SRC / "working_package",
    SRC / "local_ui",
]


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


def _source_without_docstrings(path: Path) -> str:
    """Source text with every module/class/function docstring line removed.

    Explanatory prose (e.g. "this module must not know about Orange") is
    expected to name the forbidden concepts; only actual code should not.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    doc_line_ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                doc_line_ranges.append((body[0].lineno, body[0].end_lineno or body[0].lineno))
    excluded = {line for start, end in doc_line_ranges for line in range(start, end + 1)}
    lines = source.splitlines()
    return "\n".join(line for i, line in enumerate(lines, start=1) if i not in excluded)


# --- no direct provider SDKs in new fach code --------------------------------


@pytest.mark.parametrize("path", _NEW_LLM_GATEWAY_MODULES, ids=lambda p: p.name)
def test_new_llm_gateway_modules_never_import_a_provider_sdk(path: Path) -> None:
    roots = _imported_module_roots(path)
    offending = roots & _FORBIDDEN_PROVIDER_SDK_ROOTS
    assert not offending, f"{path.name} imports forbidden provider SDK roots: {offending}"


def test_port_module_stays_completely_provider_neutral() -> None:
    path = SRC / "llm_gateway" / "port.py"
    roots = _imported_module_roots(path)

    assert "urllib" not in roots
    assert "requests" not in roots
    assert "httpx" not in roots

    lowered = _source_without_docstrings(path).lower()
    for forbidden_token in ("orange", "litellm", "chat/completions", "bearer"):
        assert forbidden_token not in lowered


# --- security gate, quarantine, and pipeline stay disconnected --------------


def _has_llm_gateway_import(path: Path) -> bool:
    full_names = _imported_full_module_names(path)
    return any(
        name == "bidfusion.llm_gateway" or name.startswith("bidfusion.llm_gateway.")
        for name in full_names
    )


@pytest.mark.parametrize("directory", _NO_LLM_GATEWAY_IMPORT_DIRS, ids=lambda p: p.name)
def test_security_quarantine_and_pipeline_never_import_llm_gateway(directory: Path) -> None:
    offenders = [
        path.relative_to(ROOT)
        for path in sorted(directory.rglob("*.py"))
        if _has_llm_gateway_import(path)
    ]
    assert not offenders, f"unexpected llm_gateway imports: {offenders}"


def test_local_pipeline_entry_point_never_imports_llm_gateway() -> None:
    # local_pipeline.py backs the "bidfusion-run" console entry point
    # (run_package) declared in pyproject.toml. It lives under
    # orchestration/, already covered by the parametrized scan above; this
    # test pins the specific file so the guarantee can't silently drift if
    # module layout changes.
    path = SRC / "orchestration" / "local_pipeline.py"
    assert path.is_file()
    assert not _has_llm_gateway_import(path)


def test_temporary_anthropic_connectivity_script_remains_an_allowed_consumer() -> None:
    path = ROOT / "scripts" / "check_anthropic_connection.py"
    assert _has_llm_gateway_import(path), (
        "the temporary Anthropic script should still use llm_gateway"
    )


def test_orange_proxy_connectivity_script_remains_an_allowed_consumer() -> None:
    path = ROOT / "scripts" / "check_orange_proxy_connection.py"
    assert _has_llm_gateway_import(path), "the Orange Proxy script should still use llm_gateway"


# --- no new observability integration: nothing is logged in this slice ------


@pytest.mark.parametrize("path", _NEW_LLM_GATEWAY_MODULES, ids=lambda p: p.name)
def test_new_llm_gateway_modules_do_not_use_logging(path: Path) -> None:
    roots = _imported_module_roots(path)
    assert "logging" not in roots


# --- offline guarantees -------------------------------------------------------


def test_normal_test_suite_cannot_open_a_real_socket() -> None:
    with pytest.raises(RuntimeError, match="network access is disabled"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_only_the_adapter_and_the_standalone_script_construct_the_real_transport() -> None:
    allowed = {
        SRC / "llm_gateway" / "orange_proxy.py",
        ROOT / "scripts" / "check_orange_proxy_connection.py",
    }
    offenders = []
    for path in sorted((*SRC.rglob("*.py"), *(ROOT / "scripts").glob("*.py"))):
        if path in allowed:
            continue
        if "UrllibOrangeProxyTransport(" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(ROOT))
    assert not offenders, f"unexpected real-transport construction outside the adapter: {offenders}"


def test_disabled_gateway_never_reaches_the_transport_layer() -> None:
    class ExplodingTransport:
        def post(self, **_kwargs: object) -> object:
            raise AssertionError("transport must never be called while disabled")

    settings = load_orange_proxy_settings({"BIDFUSION_LLM_ENABLED": "false"})
    adapter = OrangeProxyAdapter(
        settings=settings,
        secret_resolver=EnvironmentSecretResolver({}),
        transport=ExplodingTransport(),  # type: ignore[arg-type]
    )
    request = StructuredLlmRequest(
        operation=StructuredLlmOperation.SYNTHETIC_STRUCTURED_SMOKE,
        messages=(LlmMessage(role=LlmMessageRole.USER, content="hello"),),
        response_schema_name="synthetic_gateway_result",
        request_id="REQ-GUARD-001",
        data_classification=DataClassification.PUBLIC,
        model_policy_key=ModelPolicyKey.SYNTHETIC_STRUCTURED_SMOKE,
    )

    with pytest.raises(Exception) as raised:
        adapter.complete_structured(request=request, response_type=SyntheticGatewayResult)

    assert raised.value.code is LlmGatewayErrorCode.LLM_DISABLED  # type: ignore[attr-defined]
