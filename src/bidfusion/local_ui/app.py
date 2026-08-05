"""Flask application factory of the local BidFusion demonstration UI.

A thin presentation layer: routes delegate to the application service
and render templates. No security-, gate-, or quality logic lives
here, and every response carries a strict Content-Security-Policy that
forbids scripts and every remote resource. The server binds to
127.0.0.1 only.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
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

from bidfusion.local_ui import artifacts, service
from bidfusion.local_ui.icons import icon
from bidfusion.local_ui.registry import RunRecord, RunRegistry
from bidfusion.local_ui.viewmodels import (
    build_review_package_view,
    build_run_view,
    build_working_package_view,
)

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
) -> Flask:
    """Build the UI application.

    ``output_base`` optionally fixes the directory below which run
    output roots are created (tests use ``tmp_path``); by default every
    run gets a fresh private temporary directory outside any repository
    checkout.
    """
    app = Flask(__name__)
    app.config["RUN_REGISTRY"] = registry if registry is not None else RunRegistry()
    app.config["OUTPUT_BASE"] = output_base
    app.jinja_env.globals["icon"] = icon

    @app.after_request
    def _apply_security_headers(response: Response) -> Response:
        response.headers.update(_SECURITY_HEADERS)
        return response

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

    @app.get("/")
    def index() -> str:
        return render_template(
            "start.html",
            packages=service.list_packages(),
            runs=_registry(app).all(),
        )

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
        except artifacts.ArtifactAccessError as refused:
            abort(409, description=str(refused))
        return render_template(
            "working_package.html",
            run=build_run_view(record),
            package=package_view,
            view_mode=view_mode,
            raw_text=raw_text,
        )

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


def _output_base(app: Flask) -> Path | None:
    return cast(Path | None, app.config["OUTPUT_BASE"])


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
