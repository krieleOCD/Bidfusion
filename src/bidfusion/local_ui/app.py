"""Flask application factory of the local BidFusion demonstration UI.

A thin presentation layer: routes delegate to the application service
and render templates. No security-, gate-, or quality logic lives
here, and every response carries a strict Content-Security-Policy that
forbids scripts and every remote resource. The server binds to
127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from flask import (
    Flask,
    Response,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.exceptions import HTTPException
from werkzeug.wrappers.response import Response as WerkzeugResponse

from bidfusion.bidrun.quarantine import QuarantineError, UploadedFileInput
from bidfusion.golden_dataset.store import GoldenKnowledgeStore
from bidfusion.local_ui import (
    artifacts,
    feature_registry,
    golden_service,
    knowledge_assessment_service,
    knowledge_review_service,
    preview_service,
    product_shell,
    reviewed_package_service,
    scenario_registry,
    service,
    upload_service,
    upload_viewmodels,
)
from bidfusion.local_ui.icons import icon
from bidfusion.local_ui.registry import RunRecord, RunRegistry
from bidfusion.local_ui.upload_registry import UploadRegistry
from bidfusion.local_ui.viewmodels import (
    build_review_package_view,
    build_run_view,
    build_working_package_view,
)

_DEFAULT_QUARANTINE_DIRNAME = "bidfusion-uploads"

_VIEW_MODES = ("structured", "json", "md")

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; img-src 'self'; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def create_app(
    *,
    registry: RunRegistry | None = None,
    output_base: Path | None = None,
    upload_registry: UploadRegistry | None = None,
    quarantine_root: Path | None = None,
    golden_store_root: Path | None = None,
) -> Flask:
    """Build the UI application.

    ``output_base`` optionally fixes the directory below which run
    output roots are created (tests use ``tmp_path``); by default every
    run gets a fresh private temporary directory outside any repository
    checkout. ``quarantine_root`` optionally fixes the root below which
    free uploads are quarantined (tests use ``tmp_path``); by default it
    is a stable, private directory below the system temporary directory
    that persists across process restarts (Level 1A — authorized
    non-production test uploads only, see
    docs/architecture/level-1-target.md).
    """
    app = Flask(__name__)
    app.config["RUN_REGISTRY"] = registry if registry is not None else RunRegistry()
    app.config["OUTPUT_BASE"] = output_base
    app.config["UPLOAD_REGISTRY"] = (
        upload_registry if upload_registry is not None else UploadRegistry()
    )
    app.config["QUARANTINE_ROOT"] = (
        quarantine_root
        if quarantine_root is not None
        else Path(tempfile.gettempdir()) / _DEFAULT_QUARANTINE_DIRNAME
    )
    app.config["MAX_CONTENT_LENGTH"] = upload_service.MAX_CONTENT_LENGTH
    app.config["GOLDEN_STORE_ROOT"] = (
        golden_store_root if golden_store_root is not None else GoldenKnowledgeStore.default_root()
    )
    app.jinja_env.globals["icon"] = icon

    @app.after_request
    def _apply_security_headers(response: Response) -> Response:
        response.headers.update(_SECURITY_HEADERS)
        return response

    @app.context_processor
    def _shell_context() -> dict[str, product_shell.ShellContext]:
        """Give every template the shared navigation and status context.

        Built from the endpoint alone, so error pages and pages that were
        written before the product shell existed still render complete
        navigation instead of losing it exactly when something went wrong.
        """
        return {"shell": product_shell.build_shell_context(request.endpoint)}

    @app.errorhandler(service.PipelineExecutionError)
    def _pipeline_error(failure: service.PipelineExecutionError) -> tuple[str, int]:
        return (
            render_template(
                "error.html",
                status_code=500,
                title="Run not available.",
                message=str(failure),
            ),
            500,
        )

    @app.errorhandler(upload_service.UploadValidationError)
    def _upload_validation_error(failure: upload_service.UploadValidationError) -> tuple[str, int]:
        return (
            render_template(
                "error.html",
                status_code=400,
                title="Upload not accepted.",
                message=str(failure),
            ),
            400,
        )

    @app.errorhandler(scenario_registry.ScenarioError)
    def _scenario_error(failure: scenario_registry.ScenarioError) -> tuple[str, int]:
        return (
            render_template(
                "error.html",
                status_code=500,
                title="Preview data not available.",
                message=str(failure),
            ),
            500,
        )

    @app.errorhandler(QuarantineError)
    def _quarantine_integrity_error(failure: QuarantineError) -> tuple[str, int]:
        return (
            render_template(
                "error.html",
                status_code=409,
                title="Package not available.",
                message=str(failure),
            ),
            409,
        )

    @app.errorhandler(HTTPException)
    def _http_error(failure: HTTPException) -> tuple[str, int]:
        status_code = failure.code if failure.code is not None else 500
        return (
            render_template(
                "error.html",
                status_code=status_code,
                title=f"{failure.name}.",
                message=failure.description,
            ),
            status_code,
        )

    @app.get("/overview")
    def overview() -> str:
        return render_template(
            "overview.html",
            groups=product_shell.module_groups(),
            status_legend=product_shell.status_legend(),
            data_mode_legend=product_shell.data_mode_legend(),
        )

    @app.get("/architecture-roadmap")
    def architecture_roadmap() -> str:
        features = feature_registry.all_features()
        return render_template(
            "architecture_roadmap.html",
            phases=product_shell.phase_views(feature_registry.all_phases(), features),
            details=tuple(product_shell.feature_detail_view(item) for item in features),
        )

    @app.get("/features/<feature_key>")
    def feature_detail(feature_key: str) -> str:
        item = feature_registry.feature(feature_key)
        if item is None:
            abort(404)
        return render_template(
            "feature_detail.html",
            detail=product_shell.feature_detail_view(item),
        )

    _register_preview_pages(app)

    @app.get("/golden-knowledge")
    def golden_knowledge() -> str:
        return render_template(
            "golden_knowledge.html",
            view=golden_service.load_inventory_view(_golden_store_root(app)),
        )

    @app.get("/golden-knowledge/matching")
    def golden_matching() -> str:
        return render_template(
            "golden_matching.html",
            view=golden_service.load_matching_view(_golden_store_root(app)),
        )

    @app.get("/")
    @app.get("/rfp-intelligence")
    def index() -> str:
        upload_next = feature_registry.feature("upload_security_review")
        return render_template(
            "start.html",
            packages=service.list_packages(),
            runs=_registry(app).all(),
            uploads=_upload_registry(app).all(),
            upload_policy=upload_viewmodels.upload_policy_view(),
            authorization_statement=upload_service.AUTHORIZATION_STATEMENT,
            upload_next_phase=upload_next.target_phase
            if upload_next is not None
            else "a later phase",
            lifecycle=product_shell.capability_rows(product_shell.RFP_LIFECYCLE_FEATURES),
        )

    @app.post("/uploads")
    def submit_upload() -> WerkzeugResponse:
        confirmed = request.form.get("authorization_confirmed") == "on"
        uploads = tuple(
            UploadedFileInput(
                filename=storage.filename or "",
                stream=storage.stream,
                browser_content_type=storage.content_type,
            )
            for storage in request.files.getlist("files")
            if storage.filename
        )
        result = upload_service.submit_upload(
            files=uploads,
            authorization_confirmed=confirmed,
            quarantine_root=_quarantine_root(app),
        )
        record = _upload_registry(app).add(package_directory=result.package_directory)
        return redirect(url_for("show_upload", upload_key=record.key), code=303)

    @app.get("/uploads/<upload_key>")
    def show_upload(upload_key: str) -> str:
        record = _upload_registry(app).get(upload_key)
        if record is None:
            abort(404)
        view = upload_viewmodels.build_upload_result_view(record.key, record.package_directory)
        return render_template("upload_result.html", view=view)

    @app.post("/runs")
    def start_run() -> WerkzeugResponse:
        package_name = request.form.get("package", "")
        try:
            summary, output_root = service.start_run(
                package_name, process=False, output_base=_output_base(app)
            )
        except service.UnknownPackageError:
            abort(404)
        record = _registry(app).add(
            package_name=package_name,
            requested_processing=False,
            summary=summary,
            output_root=output_root,
        )
        return redirect(url_for("show_run", run_key=record.key), code=303)

    @app.get("/runs/<run_key>")
    def show_run(run_key: str) -> str:
        record = _registry(app).get(run_key)
        if record is None:
            abort(404)
        return render_template("run.html", view=build_run_view(record))

    @app.post("/runs/<run_key>/process")
    def process_run(run_key: str) -> WerkzeugResponse:
        record = _registry(app).get(run_key)
        if record is None:
            abort(404)
        if not build_run_view(record).offer_full_analysis:
            abort(409)
        summary, output_root = service.start_run(
            record.package_name, process=True, output_base=_output_base(app)
        )
        new_record = _registry(app).add(
            package_name=record.package_name,
            requested_processing=True,
            summary=summary,
            output_root=output_root,
        )
        return redirect(url_for("show_run", run_key=new_record.key), code=303)

    @app.get("/runs/<run_key>/working-package")
    def show_working_package(run_key: str) -> str:
        record = _require_record(app, run_key)
        view_mode = _view_mode()
        try:
            package_view = build_working_package_view(record)
            if package_view is None:
                abort(404)
            raw_text = _raw_text(record, view_mode, "working-package")
            review_summary = knowledge_assessment_service.build_review_summary(
                record, _golden_store_root(app)
            )
            reviewed_package = reviewed_package_service.build_reviewed_package_section(
                record, _golden_store_root(app)
            )
        except artifacts.ArtifactAccessError as refused:
            abort(409, description=str(refused))
        return render_template(
            "working_package.html",
            run=build_run_view(record),
            package=package_view,
            view_mode=view_mode,
            raw_text=raw_text,
            review_summary=review_summary,
            reviewed_package=reviewed_package,
        )

    @app.post("/runs/<run_key>/reviewed-working-package")
    def generate_reviewed_package(run_key: str) -> WerkzeugResponse:
        record = _require_record(app, run_key)
        try:
            package = reviewed_package_service.generate_reviewed_package(
                record, _golden_store_root(app)
            )
        except reviewed_package_service.PackageGenerationError as refused:
            abort(409, description=str(refused))
        except artifacts.ArtifactAccessError as refused:
            abort(409, description=str(refused))
        if package is None:
            abort(404)
        return redirect(url_for("show_working_package", run_key=record.key), code=303)

    @app.get("/runs/<run_key>/knowledge-assessment")
    def show_knowledge_assessment(run_key: str) -> str:
        record = _require_record(app, run_key)
        try:
            view = knowledge_assessment_service.build_knowledge_assessment_view(
                record, _golden_store_root(app)
            )
        except artifacts.ArtifactAccessError as refused:
            abort(409, description=str(refused))
        if view is None:
            abort(404)
        return render_template("knowledge_assessment.html", view=view)

    @app.post("/runs/<run_key>/knowledge-assessment/reviews")
    def submit_knowledge_review(run_key: str) -> WerkzeugResponse:
        record = _require_record(app, run_key)
        try:
            review = knowledge_review_service.submit_review(
                record, _golden_store_root(app), request.form
            )
        except knowledge_review_service.ReviewRequestError as refused:
            abort(400, description=str(refused))
        except knowledge_review_service.ReviewConflictError as refused:
            abort(409, description=str(refused))
        except artifacts.ArtifactAccessError as refused:
            abort(409, description=str(refused))
        if review is None:
            abort(404)
        return redirect(url_for("show_knowledge_assessment", run_key=record.key), code=303)

    @app.get("/runs/<run_key>/review-package")
    def show_review_package(run_key: str) -> str:
        record = _require_record(app, run_key)
        view_mode = _view_mode()
        try:
            package_view = build_review_package_view(record)
            if package_view is None:
                abort(404)
            raw_text = _raw_text(record, view_mode, "review-package")
        except artifacts.ArtifactAccessError as refused:
            abort(409, description=str(refused))
        return render_template(
            "review_package.html",
            run=build_run_view(record),
            package=package_view,
            view_mode=view_mode,
            raw_text=raw_text,
        )

    @app.get("/runs/<run_key>/artifacts/<artifact_name>")
    def download_artifact(run_key: str, artifact_name: str) -> Response:
        record = _require_record(app, run_key)
        if not _artifact_permitted(record, artifact_name):
            abort(404)
        try:
            located = artifacts.artifact_file(record.summary.run_directory, artifact_name)
        except artifacts.ArtifactAccessError as refused:
            abort(409, description=str(refused))
        if located is None:
            abort(404)
        path, mimetype = located
        return send_file(
            path,
            mimetype=mimetype,
            as_attachment=True,
            download_name=artifact_name,
        )

    return app


@dataclass(frozen=True, slots=True)
class _PreviewPage:
    """One module page whose content is not driven by a pipeline run."""

    rule: str
    endpoint: str
    feature_key: str
    template: str


#: The module pages of the product shell. Rule, endpoint, feature key,
#: and template are fixed here; none of them is ever derived from a
#: request, so a request can only reach the template its own entry names.
_PREVIEW_PAGES: tuple[_PreviewPage, ...] = (
    _PreviewPage(
        "/customer-intelligence",
        "customer_intelligence",
        "customer_intelligence",
        "preview/customer_intelligence.html",
    ),
    _PreviewPage("/qualification", "qualification", "qualification", "preview/qualification.html"),
    _PreviewPage("/compliance", "compliance", "compliance", "preview/compliance.html"),
    _PreviewPage(
        "/capability-fit", "capability_fit", "capability_fit", "preview/capability_fit.html"
    ),
    _PreviewPage(
        "/competitive-intelligence",
        "competitive_intelligence",
        "competitive_intelligence",
        "preview/competitive_intelligence.html",
    ),
    _PreviewPage("/win-strategy", "win_strategy", "win_strategy", "preview/win_strategy.html"),
    _PreviewPage(
        "/proposal-factory",
        "proposal_factory",
        "proposal_factory",
        "preview/proposal_factory.html",
    ),
    _PreviewPage(
        "/review-approval", "review_approval", "review_approval", "preview/review_approval.html"
    ),
)


def _register_preview_pages(app: Flask) -> None:
    """Register every module page from the static table above."""
    for page in _PREVIEW_PAGES:
        app.add_url_rule(
            page.rule,
            endpoint=page.endpoint,
            view_func=_preview_view(page),
            methods=["GET"],
        )


def _preview_view(page: _PreviewPage) -> Callable[[], str]:
    """A view that renders one fixed module page and nothing else.

    The scenario and the focused competitor come from the query string
    and are the only request-derived values on these pages. Both are
    resolved against a fixed set before use — neither can select a
    template, reach a path, or change what the page claims about itself.
    """

    def view() -> str:
        item = feature_registry.feature(page.feature_key)
        if item is None:  # pragma: no cover - the registry validates this at import
            abort(404)
        scenario_key = preview_service.resolve_scenario_key(request.args.get("scenario"))
        if scenario_key is None:
            abort(404)
        context, scenario = preview_service.load_page(item, scenario_key)
        return render_template(
            page.template,
            page=context,
            section=preview_service.section_for(
                page.feature_key, scenario, request.args.get("focus")
            ),
        )

    return view


def _require_record(app: Flask, run_key: str) -> RunRecord:
    record = _registry(app).get(run_key)
    if record is None:
        abort(404)
    return record


def _view_mode() -> str:
    view_mode = request.args.get("view", "structured")
    if view_mode not in _VIEW_MODES:
        abort(404)
    return view_mode


def _raw_text(record: RunRecord, view_mode: str, artifact_stem: str) -> str | None:
    if view_mode == "structured":
        return None
    suffix = "json" if view_mode == "json" else "md"
    return artifacts.read_text_artifact(record.summary.run_directory, f"{artifact_stem}.{suffix}")


def _artifact_permitted(record: RunRecord, artifact_name: str) -> bool:
    """Outcome gating on top of the static allowlist.

    Working-package artifacts are only served for completed runs and
    review-package artifacts only for quality-review runs; the gate and
    summary records are always permitted (their files exist exactly when
    the pipeline recorded them).
    """
    view = build_run_view(record)
    if artifact_name.startswith("working-package"):
        return view.is_completed
    if artifact_name.startswith("review-package"):
        return view.is_quality_review
    return True


def _registry(app: Flask) -> RunRegistry:
    return cast(RunRegistry, app.config["RUN_REGISTRY"])


def _golden_store_root(app: Flask) -> Path:
    return cast(Path, app.config["GOLDEN_STORE_ROOT"])


def _output_base(app: Flask) -> Path | None:
    return cast(Path | None, app.config["OUTPUT_BASE"])


def _upload_registry(app: Flask) -> UploadRegistry:
    return cast(UploadRegistry, app.config["UPLOAD_REGISTRY"])


def _quarantine_root(app: Flask) -> Path:
    return cast(Path, app.config["QUARANTINE_ROOT"])


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local development server (127.0.0.1 only)."""
    parser = argparse.ArgumentParser(
        prog="bidfusion-ui",
        description=(
            "Local synthetic demonstration UI for the BidFusion walking "
            "skeleton. Serves on 127.0.0.1 only and processes only the "
            "repository's own fixtures/synthetic/ packages."
        ),
    )
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args(argv)
    # load_dotenv=False keeps Flask from ever reading .env files, even if
    # python-dotenv gets installed later; secrets never enter this UI.
    create_app().run(host="127.0.0.1", port=arguments.port, debug=False, load_dotenv=False)
    return 0


def cli() -> None:
    """Installed console-script entry point."""
    raise SystemExit(main())
