"""Structural guards for the product shell.

The honesty of this interface rests on one arrangement: the registry
decides what a feature claims, the services decide what data exists, and
templates only render what they were handed. These guards keep that
arrangement from eroding — a status typed into a template, a connector
imported into a preview module, or a branch on one particular customer
would each break it quietly, so each fails a test instead.

Import boundaries are checked by parsing the syntax tree rather than by
grepping, so the checks survive reformatting and prose that merely
mentions a module name.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from bidfusion.local_ui.feature_registry import DataMode, FeatureStatus

ROOT = Path(__file__).resolve().parents[2]
LOCAL_UI = ROOT / "src" / "bidfusion" / "local_ui"
TEMPLATES = LOCAL_UI / "templates"

PREVIEW_MODULES = (
    LOCAL_UI / "preview_service.py",
    LOCAL_UI / "preview_viewmodels.py",
    LOCAL_UI / "preview_schemas.py",
    LOCAL_UI / "scenario_registry.py",
    LOCAL_UI / "feature_registry.py",
    LOCAL_UI / "product_shell.py",
)

#: Nothing in the preview lane may reach a network, a process, a model,
#: or any part of the pipeline that handles real bytes.
_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "urllib",
        "http",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "smtplib",
        "ftplib",
        "webbrowser",
        "openai",
        "anthropic",
        "langchain",
        "boto3",
        "google",
    }
)

_FORBIDDEN_BIDFUSION_MODULES = (
    "bidfusion.llm_gateway",
    "bidfusion.security",
    "bidfusion.bidrun",
    "bidfusion.orchestration",
    "bidfusion.document_understanding",
    "bidfusion.extraction",
)


def _imports(path: Path) -> tuple[set[str], set[str]]:
    """Root packages and full module names imported by one file."""
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


def _templates() -> tuple[Path, ...]:
    return tuple(sorted(TEMPLATES.rglob("*.html")))


def _code_without_docstrings(path: Path) -> str:
    """Source with every docstring removed.

    Prose is expected to name the things code must not reach — a module
    may explain that it reads demonstration data without that counting as
    reading it.
    """
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


# --- 61: no template states a status of its own ------------------------------


def test_no_template_hardcodes_a_feature_status_or_data_mode() -> None:
    """Status belongs to the registry; a template only renders what it got."""
    forbidden = tuple(member.value for member in FeatureStatus) + tuple(
        member.value for member in DataMode
    )
    offenders: list[str] = []
    for template in _templates():
        text = template.read_text(encoding="utf-8")
        for literal in forbidden:
            if literal in text:
                offenders.append(f"{template.relative_to(TEMPLATES)}: {literal}")
    assert not offenders, f"status hardcoded in templates: {offenders}"


def test_no_template_hardcodes_a_phase_identifier() -> None:
    """Phases move. A template that names one goes stale silently."""
    offenders: list[str] = []
    for template in _templates():
        text = template.read_text(encoding="utf-8")
        for literal in ("L1A-S", "L2-", "L0.4", "L1B"):
            if literal in text:
                offenders.append(f"{template.relative_to(TEMPLATES)}: {literal}")
    assert not offenders, f"phase identifiers hardcoded in templates: {offenders}"


# --- 62, 63: the preview lane reaches nothing --------------------------------


@pytest.mark.parametrize("path", PREVIEW_MODULES, ids=lambda p: p.name)
def test_no_preview_module_imports_a_transport_or_a_provider(path: Path) -> None:
    roots, _ = _imports(path)

    offending = roots & _FORBIDDEN_IMPORT_ROOTS
    assert not offending, f"{path.name} imports {offending}"


@pytest.mark.parametrize("path", PREVIEW_MODULES, ids=lambda p: p.name)
def test_no_preview_module_imports_a_pipeline_or_security_service(path: Path) -> None:
    _, full = _imports(path)

    for module in _FORBIDDEN_BIDFUSION_MODULES:
        offending = {name for name in full if name == module or name.startswith(f"{module}.")}
        assert not offending, f"{path.name} imports {offending}"


@pytest.mark.parametrize("path", PREVIEW_MODULES, ids=lambda p: p.name)
def test_no_preview_module_imports_flask(path: Path) -> None:
    """The preview lane is framework-free: it builds data, not responses."""
    roots, _ = _imports(path)

    assert "flask" not in roots, path.name
    assert "werkzeug" not in roots, path.name


@pytest.mark.parametrize("path", PREVIEW_MODULES, ids=lambda p: p.name)
def test_no_preview_module_reads_the_environment(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    for forbidden in ("os.environ", "getenv", "load_dotenv"):
        assert forbidden not in source, f"{path.name} touches {forbidden}"


def test_the_interface_cannot_reach_the_model_gateway_even_indirectly() -> None:
    """Follow every import out of the interface; none of them lands there.

    Checked statically rather than by inspecting loaded modules: another
    test importing the gateway would make a runtime check fail for a
    reason that has nothing to do with the interface.
    """
    src = ROOT / "src"
    seen: set[str] = set()
    pending = ["bidfusion.local_ui.app"]
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

    offending = {name for name in seen if name.startswith("bidfusion.llm_gateway")}
    assert not offending, f"the interface can reach {offending}"


# --- 64: only the scenario registry reads demonstration data -----------------


def test_only_the_scenario_registry_opens_a_demonstration_file() -> None:
    allowed = LOCAL_UI / "scenario_registry.py"
    offenders: list[str] = []
    for path in sorted(LOCAL_UI.glob("*.py")):
        if path == allowed:
            continue
        code = _code_without_docstrings(path)
        if "product_demo" in code or "scenario.json" in code:
            offenders.append(path.name)
    assert not offenders, f"demonstration files read outside the registry: {offenders}"


def test_the_scenario_registry_reads_only_below_the_demonstration_root() -> None:
    source = (LOCAL_UI / "scenario_registry.py").read_text(encoding="utf-8")

    assert source.count("read_text") == 1
    assert "product_demo" in source
    assert "open(" not in source


# --- 65: no route branches on one particular bid, customer, or competitor ----


def test_no_route_branches_on_a_customer_or_a_competitor_name() -> None:
    """Special cases belong in data. A branch on a name is a defect."""
    source = (LOCAL_UI / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for comparator in node.comparators:
            if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                assert comparator.value in {"", "on", "structured", "json", "md"}, (
                    f"app.py compares against the literal {comparator.value!r}"
                )


def test_no_template_name_is_ever_built_from_a_request() -> None:
    """Every rendered template is a literal, or the page's own fixed entry."""
    tree = ast.parse((LOCAL_UI / "app.py").read_text(encoding="utf-8"))
    rendered: list[ast.expr] = [
        node.args[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "render_template"
        and node.args
    ]

    assert rendered, "no render_template call found"
    for argument in rendered:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            assert argument.value.endswith(".html")
            continue
        assert isinstance(argument, ast.Attribute), ast.dump(argument)
        assert argument.attr == "template", ast.dump(argument)
        assert isinstance(argument.value, ast.Name), ast.dump(argument)
        assert argument.value.id == "page", ast.dump(argument)


# --- 66: the existing services stay where they were --------------------------


def test_the_existing_services_did_not_gain_a_preview_dependency() -> None:
    """The real lanes must not learn about the demonstration lane."""
    for name in ("service.py", "upload_service.py", "artifacts.py", "viewmodels.py"):
        _, full = _imports(LOCAL_UI / name)
        offending = {
            module
            for module in full
            if module.endswith(("preview_service", "preview_schemas", "scenario_registry"))
        }
        assert not offending, f"{name} imports {offending}"


def test_the_feature_registry_stays_pure_configuration() -> None:
    path = LOCAL_UI / "feature_registry.py"
    roots, full = _imports(path)

    assert roots <= {"__future__", "dataclasses", "enum"}, roots
    assert not any(name.startswith("bidfusion.") for name in full), full


def test_the_product_shell_knows_nothing_about_the_pipeline() -> None:
    _, full = _imports(LOCAL_UI / "product_shell.py")

    assert all(
        name.startswith(("bidfusion.local_ui", "dataclasses", "__future__")) for name in full
    ), full
