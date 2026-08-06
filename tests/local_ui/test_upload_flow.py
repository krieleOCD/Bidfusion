"""Free-upload UI flow: authorization, quarantine, and integrity-gated display.

Numbered comments correspond to the governing instructions' test list.
"""

from __future__ import annotations

import io
import os
import stat
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from openpyxl import Workbook
from werkzeug.test import TestResponse

from bidfusion.local_ui.app import create_app

AUTHORIZATION_STATEMENT = (
    "I confirm that these files are authorized for non-production testing "
    "and contain no prohibited production customer data."
)


def pdf_bytes() -> bytes:
    return b"%PDF-1.4\n%synthetic\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"


def xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["A1"] = "Requirement"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def txt_bytes() -> bytes:
    return b"Synthetic RFP notes.\n"


def docx_like_bytes() -> bytes:
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", b"<document/>")
    return buffer.getvalue()


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return create_app(output_base=tmp_path / "ui-runs", quarantine_root=tmp_path / "quarantine")


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def _upload(
    client: FlaskClient,
    files: list[tuple[str, bytes]],
    *,
    confirmed: bool = True,
) -> TestResponse:
    data: dict[str, object] = {
        "files": [(io.BytesIO(content), name) for name, content in files],
    }
    if confirmed:
        data["authorization_confirmed"] = "on"
    return client.post("/uploads", data=data, content_type="multipart/form-data")


def _quarantine_root(app: Flask) -> Path:
    from bidfusion.local_ui.app import _quarantine_root as get_root

    return get_root(app)


def _only_package_dir(root: Path) -> Path:
    entries = [entry for entry in root.iterdir() if entry.name != ".staging"]
    assert len(entries) == 1
    return entries[0]


# --- 1-3: start page -------------------------------------------------------


def test_1_start_page_shows_both_separated_areas(client: FlaskClient) -> None:
    html = client.get("/").get_data(as_text=True)
    assert "Synthetic demo packages" in html
    assert "Upload authorized test RFP" in html


def test_2_upload_hint_text_is_present_verbatim(client: FlaskClient) -> None:
    html = client.get("/").get_data(as_text=True)
    assert (
        "Authorized non-production test files can be uploaded into quarantine. "
        "Uploaded files are not security-cleared or processed automatically."
        in " ".join(html.split())
    )
    assert "Non-production authorized test files only." in html
    assert AUTHORIZATION_STATEMENT in html


def test_3_authorization_checkbox_is_never_preselected(client: FlaskClient) -> None:
    html = client.get("/").get_data(as_text=True)
    field = html.split('name="authorization_confirmed"')[1].split(">")[0]
    assert "checked" not in field


# --- 4-5: acceptance ---------------------------------------------------


def test_4_valid_pdf_redirects_to_quarantined_page(client: FlaskClient) -> None:
    response = _upload(client, [("invitation.pdf", pdf_bytes())])
    assert response.status_code == 303
    location = response.headers["Location"]
    result = client.get(location)
    assert result.status_code == 200
    html = result.get_data(as_text=True)
    assert "QUARANTINED" in html
    assert "invitation.pdf" in html


def test_5_valid_mixed_package(client: FlaskClient) -> None:
    response = _upload(
        client,
        [
            ("invitation.pdf", pdf_bytes()),
            ("matrix.xlsx", xlsx_bytes()),
            ("notes.txt", txt_bytes()),
        ],
    )
    location = response.headers["Location"]
    html = client.get(location).get_data(as_text=True)
    assert html.count("<tr>") - 1 >= 3 or "invitation.pdf" in html  # rendered file rows
    assert "matrix.xlsx" in html
    assert "notes.txt" in html


# --- 6-7: authorization / empty package -------------------------------------


def test_6_missing_authorization_writes_nothing(client: FlaskClient, app: Flask) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes())], confirmed=False)
    assert response.status_code == 400
    root = _quarantine_root(app)
    assert not root.exists() or list(root.iterdir()) == []


def test_7_no_files_is_a_safe_validation_response(client: FlaskClient) -> None:
    response = client.post(
        "/uploads",
        data={"authorization_confirmed": "on"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert "Traceback" not in html


# --- 8-15: hardening (thin pass-through to the quarantine service) ---------


def test_8_traversal_filename_is_rejected(client: FlaskClient) -> None:
    response = _upload(client, [("../escape.pdf", pdf_bytes())])
    assert response.status_code == 400


def test_9_windows_path_filename_is_rejected(client: FlaskClient) -> None:
    response = _upload(client, [("C:\\evil.pdf", pdf_bytes())])
    assert response.status_code == 400


def test_10_duplicate_normalized_names_are_rejected(client: FlaskClient) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes()), ("a.pdf", pdf_bytes())])
    assert response.status_code == 400


def test_11_extension_magic_mismatch_is_rejected(client: FlaskClient) -> None:
    response = _upload(client, [("fake.xlsx", docx_like_bytes())])
    assert response.status_code == 400


def test_12_docx_xlsm_zip_are_rejected(client: FlaskClient) -> None:
    for filename in ("proposal.docx", "macro.xlsm", "archive.zip"):
        response = _upload(client, [(filename, docx_like_bytes())])
        assert response.status_code == 400, filename


def test_13_file_too_large_is_rejected(client: FlaskClient) -> None:
    from bidfusion.bidrun.policy import DEFAULT_UPLOAD_POLICY

    oversized = b"a" * (DEFAULT_UPLOAD_POLICY.max_file_size_bytes + 1)
    response = _upload(client, [("big.txt", oversized)])
    assert response.status_code == 400


def test_14_package_too_large_is_rejected(app: Flask) -> None:
    # Use a fresh client with a lower content-length cap awareness isn't
    # needed here: three files within the per-file limit but over the
    # package limit exercise the *service's* package-size check.
    from bidfusion.bidrun.policy import DEFAULT_UPLOAD_POLICY

    client = app.test_client()
    chunk = b"a" * (DEFAULT_UPLOAD_POLICY.max_file_size_bytes)
    # 5 * 25MB = 125MB > 100MB package limit, each file individually legal.
    files = [(f"f{i}.txt", chunk) for i in range(5)]
    response = _upload(client, files)
    assert response.status_code in (400, 413)


def test_15_too_many_files_is_rejected(client: FlaskClient) -> None:
    files = [(f"f{i}.txt", txt_bytes()) for i in range(21)]
    response = _upload(client, files)
    assert response.status_code == 400


# --- 16-17: POST/Redirect/GET ------------------------------------------


def test_16_post_redirect_get_prevents_resubmission(client: FlaskClient, app: Flask) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes())])
    assert response.status_code == 303
    root = _quarantine_root(app)
    package_before = _only_package_dir(root)

    # Simulate the browser refreshing the *result page*, not re-POSTing.
    location = response.headers["Location"]
    client.get(location)
    client.get(location)
    package_after = _only_package_dir(root)
    assert package_before == package_after


def test_17_refresh_of_the_upload_page_creates_no_new_package(
    client: FlaskClient, app: Flask
) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes())])
    location = response.headers["Location"]
    root = _quarantine_root(app)
    before = sorted(p.name for p in root.iterdir())
    client.get(location)
    client.get(location)
    after = sorted(p.name for p in root.iterdir())
    assert before == after


# --- 18: unknown opaque id --------------------------------------------------


def test_18_unknown_upload_id_is_404(client: FlaskClient) -> None:
    assert client.get("/uploads/upload-999").status_code == 404


# --- 19-22: tampered persistence -> 409 -------------------------------------


def _tamper(path: Path, transform: bytes) -> None:
    original_mode = stat.S_IMODE(path.stat().st_mode)
    os.chmod(path, 0o600)
    path.write_bytes(transform)
    os.chmod(path, original_mode)


def test_19_tampered_manifest_yields_409(client: FlaskClient, app: Flask) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes())])
    location = response.headers["Location"]
    package = _only_package_dir(_quarantine_root(app))
    manifest_path = package / "manifest" / "upload-manifest.audit.json"
    _tamper(manifest_path, manifest_path.read_bytes().replace(b"pdf", b"xyz"))

    result = client.get(location)
    assert result.status_code == 409
    assert "Traceback" not in result.get_data(as_text=True)


def test_20_tampered_file_yields_409(client: FlaskClient, app: Flask) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes())])
    location = response.headers["Location"]
    package = _only_package_dir(_quarantine_root(app))
    files_dir = package / "files"
    raw_file = next(files_dir.iterdir())
    _tamper(raw_file, b"tampered bytes")

    result = client.get(location)
    assert result.status_code == 409


def test_21_tampered_bidrun_payload_yields_409(client: FlaskClient, app: Flask) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes())])
    location = response.headers["Location"]
    package = _only_package_dir(_quarantine_root(app))
    record_path = package / "bidrun" / "bidrun-record.audit.json"
    _tamper(record_path, record_path.read_bytes().replace(b"QUARANTINED", b"CLEARED"))

    result = client.get(location)
    assert result.status_code == 409


def test_22_wrong_lineage_yields_409(client: FlaskClient, app: Flask) -> None:
    import json
    from hashlib import sha256

    response = _upload(client, [("a.pdf", pdf_bytes())])
    location = response.headers["Location"]
    package = _only_package_dir(_quarantine_root(app))
    record_path = package / "bidrun" / "bidrun-record.audit.json"
    manifest_path = package / "manifest" / "upload-manifest.audit.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hash = manifest["artifact"]["content_hash"]
    forged = "f" * 64 if manifest_hash != "f" * 64 else "e" * 64

    original = record_path.read_bytes()
    tampered = original.replace(manifest_hash.encode(), forged.encode())
    assert tampered != original
    _tamper(record_path, tampered)

    integrity_path = package / "integrity-manifest.json"
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    integrity["files"]["bidrun/bidrun-record.audit.json"] = sha256(tampered).hexdigest()
    _tamper(integrity_path, (json.dumps(integrity, indent=2, sort_keys=True) + "\n").encode())

    result = client.get(location)
    assert result.status_code == 409


# --- 23-25: safe response bodies --------------------------------------------


def test_23_response_never_contains_an_absolute_path(client: FlaskClient, app: Flask) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes())])
    location = response.headers["Location"]
    html = client.get(location).get_data(as_text=True)
    assert str(_quarantine_root(app)) not in html


def test_24_response_never_contains_internal_filenames(client: FlaskClient, app: Flask) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes())])
    location = response.headers["Location"]
    package = _only_package_dir(_quarantine_root(app))
    internal_name = next((package / "files").iterdir()).name
    html = client.get(location).get_data(as_text=True)
    assert internal_name not in html


def test_25_error_responses_never_contain_raw_exceptions(client: FlaskClient, app: Flask) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes())])
    location = response.headers["Location"]
    package = _only_package_dir(_quarantine_root(app))
    manifest_path = package / "manifest" / "upload-manifest.audit.json"
    _tamper(manifest_path, b"not even json")

    result = client.get(location)
    html = result.get_data(as_text=True)
    assert "Traceback" not in html
    assert "JSONDecodeError" not in html
    assert str(package) not in html


# --- 26: no processing affordances ------------------------------------------


def test_26_quarantine_page_has_no_processing_buttons(client: FlaskClient) -> None:
    response = _upload(client, [("a.pdf", pdf_bytes())])
    html = client.get(response.headers["Location"]).get_data(as_text=True)
    for forbidden in (
        "Analyze",
        "Security clearance",
        "Continue processing",
        "Run full analysis",
        "Download",
    ):
        assert forbidden not in html
    assert "CLEARED" not in html
    assert "status-badge--success" not in html


# --- 27-30: no downstream processing ----------------------------------------


def test_27_run_package_is_never_called(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bidfusion.orchestration as orchestration

    def exploding(**_kwargs: object) -> None:
        raise AssertionError("run_package must never be called from the upload UI flow")

    monkeypatch.setattr(orchestration, "run_package", exploding)
    response = _upload(client, [("a.pdf", pdf_bytes())])
    assert response.status_code == 303


def test_28_29_30_no_parser_extractor_or_security_module_is_imported() -> None:
    import ast

    import bidfusion.local_ui.upload_service as upload_service_module
    import bidfusion.local_ui.upload_viewmodels as upload_viewmodels_module

    forbidden_prefixes = (
        "bidfusion.document_understanding",
        "bidfusion.extraction",
        "bidfusion.normalization",
        "bidfusion.quality",
        "bidfusion.working_package",
        "bidfusion.security",
    )
    for module in (upload_service_module, upload_viewmodels_module):
        assert module.__file__ is not None
        with open(module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for name in imported:
            for prefix in forbidden_prefixes:
                assert not name.startswith(prefix), (module.__name__, name)


# --- 31: synthetic flow untouched (see tests/local_ui/test_start_page.py etc.) ---
# --- 32: CSP / security headers -------------------------------------------


def test_32_upload_responses_keep_the_existing_security_headers(client: FlaskClient) -> None:
    response = client.get("/")
    assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert response.headers["X-Content-Type-Options"] == "nosniff"

    upload_response = _upload(client, [("a.pdf", pdf_bytes())])
    result = client.get(upload_response.headers["Location"])
    assert result.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert result.headers["X-Content-Type-Options"] == "nosniff"


# --- 33: 413 handled safely -------------------------------------------------


def test_33_oversized_request_body_yields_a_safe_413(client: FlaskClient, app: Flask) -> None:
    huge = b"a" * (app.config["MAX_CONTENT_LENGTH"] + 1)
    response = client.post(
        "/uploads",
        data={"files": (io.BytesIO(huge), "huge.txt"), "authorization_confirmed": "on"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413
    html = response.get_data(as_text=True)
    assert "Traceback" not in html
    assert "werkzeug" not in html.lower()
