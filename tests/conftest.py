"""Shared offline fixtures: the real gate-to-canonical chain over fixtures.

Also enforces Z5 technically for the whole test session. The guards are
installed once in :func:`pytest_configure` — before collection and before
any test body runs — so even import-time and fixture-time code is covered:

- **Network**: AF_INET/AF_INET6 sockets (TCP and UDP) cannot be created,
  and ``connect``/``connect_ex``/``sendto``/``sendmsg``/
  ``create_connection`` are blocked for INET sockets however they were
  created. Regular DNS resolver paths (``getaddrinfo``, ``gethostbyname``,
  ``gethostbyname_ex``, ``gethostbyaddr``, ``getnameinfo``) are blocked.
  Local IPC (``AF_UNIX``, ``socketpair``) stays available.
- **Subprocess**: ``subprocess.Popen`` (and thereby ``run``/``call``) plus
  the known ``os`` process surface (``system``, ``popen``,
  ``posix_spawn``/``posix_spawnp``, ``spawn*``, ``exec*``, ``fork``,
  ``forkpty``) are blocked unless a test is explicitly marked
  ``allow_subprocess``.
- **Protected paths**: the repository's own ``inbox/`` and ``results/``
  directories (including descendants, symlinked routes, and ``os.open``
  with ``dir_fd``-relative paths) can never be opened via
  ``builtins.open``/``io.open`` (which also backs ``Path.open``/
  ``read_text``/``read_bytes``) or ``os.open``. Identically named
  directories under ``tmp_path`` remain usable, as do pypdf and openpyxl
  over ``tmp_path`` files.

Scope statement: these guards prevent *accidental* network, process, and
protected-path access in regular tests. They are in-process Python-level
interception, not an OS sandbox, and make no security claim against
deliberately malicious test code.
"""

from __future__ import annotations

import builtins
import fcntl
import io
import os
import socket
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from bidfusion.document_understanding.canonical import build_canonical_document
from bidfusion.document_understanding.parsers import parser_for
from bidfusion.golden_dataset.contracts import (
    CapabilityCategory,
    CapabilityClaim,
    ConfidenceBand,
    DocumentType,
    EvidenceReference,
    ExtractionStatus,
    HumanReviewStatus,
    IngestionStatus,
    KnowledgeDocument,
    KnowledgeInventory,
    KnowledgeProvenance,
    KnowledgeSection,
    KnowledgeSource,
    KnowledgeSourceLocator,
    ParseStatus,
    ParseSupport,
    ProvenanceStatus,
    ServiceFamily,
    Technology,
)
from bidfusion.golden_dataset.store import GoldenKnowledgeStore
from bidfusion.schemas import (
    ArtifactReference,
    ArtifactType,
    CanonicalDocument,
    SecurityClearedArtifact,
    SecurityVerdict,
)
from bidfusion.security import DeterministicPreflightScanner, decide_document

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_FIXTURES = REPO_ROOT / "fixtures" / "synthetic"
RFP_MINIMAL = SYNTHETIC_FIXTURES / "rfp-minimal"
CHAIN_BID_ID = "BID-2026-000123"
CHAIN_RUN_ID = "RUN-20260804-0001"
CHAIN_NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
_CHAIN_FILENAMES = ("rfp-invitation.pdf", "requirements-matrix.xlsx", "notes.txt")

# The unguarded originals, captured at import time — before any fixture
# patches — so self-tests can exercise the method-level guards directly.
_REAL_SOCKET_CLASS = socket.socket
_REAL_IO_OPEN = io.open
_REAL_OS_OPEN = os.open

_PROTECTED_ROOTS = tuple((REPO_ROOT / name).resolve() for name in ("inbox", "results"))
_INET_FAMILIES = frozenset({socket.AF_INET, socket.AF_INET6})


def build_package_canonicals(
    package_dir: Path,
    filenames: tuple[str, ...],
) -> tuple[CanonicalDocument, ...]:
    """Run fixture files through the real preflight, gate policy, and parsers."""
    documents: list[CanonicalDocument] = []
    for index, filename in enumerate(filenames, start=1):
        content = (package_dir / filename).read_bytes()
        raw = ArtifactReference(
            artifact_id=f"ART-20260804-{index:06d}",
            bid_id=CHAIN_BID_ID,
            run_id=CHAIN_RUN_ID,
            artifact_type=ArtifactType.RAW_DOCUMENT,
            schema_version="1.0.0",
            content_ref=f"package/{filename}",
            content_hash=sha256(content).hexdigest(),
        )
        assessment = DeterministicPreflightScanner().assess(
            artifact=raw,
            document_id=f"DOC-{index:03d}",
            filename=filename,
            content=content,
            assessed_at=CHAIN_NOW,
        )
        result = decide_document(assessment)
        assert result.verdict is SecurityVerdict.ALLOW
        cleared = SecurityClearedArtifact(
            artifact=raw,
            document_id=f"DOC-{index:03d}",
            security_result=result,
        )
        parser = parser_for(filename.rsplit(".", 1)[1])
        assert parser is not None
        canonical_artifact_id = f"ART-20260804-{index + 10:06d}"
        parsed = parser.parse(
            cleared=cleared,
            content=content,
            filename=filename,
            canonical_artifact_id=canonical_artifact_id,
        )
        documents.append(
            build_canonical_document(
                cleared,
                parsed,
                filename=filename,
                canonical_artifact_id=canonical_artifact_id,
                run_id=CHAIN_RUN_ID,
                created_at=CHAIN_NOW,
                parser_name=parser.parser_name,
                parser_version=parser.parser_version,
            )
        )
    return tuple(documents)


def build_rfp_minimal_canonicals() -> tuple[CanonicalDocument, ...]:
    """Canonical documents of the clean fixture package."""
    return build_package_canonicals(RFP_MINIMAL, _CHAIN_FILENAMES)


# ---------------------------------------------------------------------------
# Synthetic golden knowledge snapshot (offline stand-in for the runtime store)
# ---------------------------------------------------------------------------

GOLDEN_SOURCE_ID = "GKS-00000000000a"
GOLDEN_SOURCE_FILENAME = "SD-Synthetic MTD v1.0.docx"
_GOLDEN_HASH = "e" * 64

#: The pilot capabilities the synthetic snapshot claims, one claim each.
SYNTHETIC_GOLDEN_CAPABILITIES = (
    CapabilityCategory.TWENTY_FOUR_SEVEN_MONITORING,
    CapabilityCategory.MICROSOFT_SENTINEL_SUPPORT,
    CapabilityCategory.MICROSOFT_DEFENDER_XDR_SUPPORT,
    CapabilityCategory.INCIDENT_ISOLATION,
    CapabilityCategory.TRANSITION_ACTIVATION,
    CapabilityCategory.HANDOVER_TO_OPERATIONS,
)


def synthetic_golden_claims(
    capabilities: tuple[CapabilityCategory, ...] = SYNTHETIC_GOLDEN_CAPABILITIES,
) -> tuple[CapabilityClaim, ...]:
    """Synthetic EXTRACTED_UNVERIFIED claims with synthetic evidence."""
    return tuple(
        CapabilityClaim(
            claim_id=f"GCL-{index:012x}",
            service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
            technology=Technology.GENERIC_MTD,
            capability=capability,
            statement=f"Synthetic claim for {capability.value}.",
            evidence_refs=(
                EvidenceReference(
                    source_id=GOLDEN_SOURCE_ID,
                    section_id=f"SEC-{index:04d}",
                    locator=KnowledgeSourceLocator(paragraph_index=index),
                    source_version="1.0",
                ),
            ),
            confidence_band=ConfidenceBand.HIGH,
        )
        for index, capability in enumerate(capabilities, start=1)
    )


def populate_synthetic_golden_store(
    root: Path,
    claims: tuple[CapabilityClaim, ...] | None = None,
) -> GoldenKnowledgeStore:
    """Write a complete, referentially intact synthetic golden store."""
    if claims is None:
        claims = synthetic_golden_claims()
    store = GoldenKnowledgeStore(root)
    store.write_inventory(
        KnowledgeInventory(
            dataset_label="synthetic-test-set",
            sources=(
                KnowledgeSource(
                    source_id=GOLDEN_SOURCE_ID,
                    filename=GOLDEN_SOURCE_FILENAME,
                    extension="docx",
                    file_size=100,
                    source_hash=_GOLDEN_HASH,
                    service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
                    technology=Technology.GENERIC_MTD,
                    document_type=DocumentType.SERVICE_DESCRIPTION,
                    version="1.0",
                    parse_support=ParseSupport.SUPPORTED,
                    parse_status=ParseStatus.PARSED,
                    ingestion_status=IngestionStatus.INGESTED,
                    review_status=HumanReviewStatus.REQUIRED,
                    provenance_id="GPV-000000000abc",
                ),
            ),
        )
    )
    section_ids = sorted(
        {reference.section_id for claim in claims for reference in claim.evidence_refs}
    ) or ["SEC-0001"]
    store.write_document(
        KnowledgeDocument(
            knowledge_document_id="GKD-00000000000a",
            source_id=GOLDEN_SOURCE_ID,
            schema_version="1.0.0",
            title="Synthetic MTD service description",
            service_family=ServiceFamily.MANAGED_THREAT_DETECTION,
            technology=Technology.GENERIC_MTD,
            document_type=DocumentType.SERVICE_DESCRIPTION,
            source_version="1.0",
            sections=tuple(
                KnowledgeSection(
                    section_id=section_id,
                    heading=None,
                    text=f"Synthetic capability statement {section_id}.",
                    source_locator=KnowledgeSourceLocator(paragraph_index=index),
                    source_id=GOLDEN_SOURCE_ID,
                )
                for index, section_id in enumerate(section_ids, start=1)
            ),
            provenance=KnowledgeProvenance(
                source_id=GOLDEN_SOURCE_ID,
                filename=GOLDEN_SOURCE_FILENAME,
                source_hash=_GOLDEN_HASH,
                document_version="1.0",
                locator=KnowledgeSourceLocator(whole_document=True),
            ),
            extraction_status=ExtractionStatus.EXTRACTED,
            review_status=HumanReviewStatus.REQUIRED,
            provenance_status=ProvenanceStatus.PROVENANCE_FULL,
        )
    )
    store.write_claims(claims)
    return store


@pytest.fixture
def synthetic_golden_store(tmp_path: Path) -> Path:
    """A populated synthetic golden store root below ``tmp_path``."""
    root = tmp_path / "golden-store"
    populate_synthetic_golden_store(root)
    return root


def _network_blocked(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("network access is disabled in BidFusion tests")


class _GuardedSocket(socket.socket):
    """Socket class that refuses AF_INET/AF_INET6 creation entirely."""

    def __init__(
        self,
        family: int = -1,
        type: int = -1,  # noqa: A002 - mirrors the stdlib signature
        proto: int = -1,
        fileno: int | None = None,
    ) -> None:
        # -1 resolves to AF_INET in the stdlib, so the default is blocked too.
        if fileno is None and (family == -1 or family in _INET_FAMILIES):
            _network_blocked()
        super().__init__(family, type, proto, fileno)


def _guarded_socket_method(name: str) -> Any:
    original = getattr(_REAL_SOCKET_CLASS, name)

    def guarded(self: socket.socket, *args: object, **kwargs: object) -> object:
        if self.family in _INET_FAMILIES:
            _network_blocked()
        return original(self, *args, **kwargs)

    return guarded


_SUBPROCESS_STATE = {"allowed": False}
_REAL_POPEN = subprocess.Popen
_DNS_FUNCTIONS = (
    "getaddrinfo",
    "gethostbyname",
    "gethostbyname_ex",
    "gethostbyaddr",
    "getnameinfo",
)
_OS_PROCESS_FUNCTIONS = (
    "system",
    "popen",
    "posix_spawn",
    "posix_spawnp",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "fork",
    "forkpty",
)


def _dns_blocked(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("network access is disabled in BidFusion tests (DNS)")


def _subprocess_blocked_message() -> str:
    return (
        "subprocess execution is disabled in BidFusion tests; mark the "
        "test with @pytest.mark.allow_subprocess if it genuinely needs it"
    )


def _guarded_popen(*args: Any, **kwargs: Any) -> Any:
    if not _SUBPROCESS_STATE["allowed"]:
        raise RuntimeError(_subprocess_blocked_message())
    return _REAL_POPEN(*args, **kwargs)


def _guarded_os_process(name: str) -> Any:
    original = getattr(os, name)

    def guarded(*args: Any, **kwargs: Any) -> Any:
        if not _SUBPROCESS_STATE["allowed"]:
            raise RuntimeError(_subprocess_blocked_message())
        return original(*args, **kwargs)

    return guarded


@pytest.fixture(autouse=True)
def _subprocess_allowlist(request: pytest.FixtureRequest) -> Any:
    """Toggle the session-wide subprocess guard for allowlisted tests."""
    allowed = request.node.get_closest_marker("allow_subprocess") is not None
    _SUBPROCESS_STATE["allowed"] = allowed
    yield
    _SUBPROCESS_STATE["allowed"] = False


def _is_protected_path(target: object) -> bool:
    if not isinstance(target, str | bytes | os.PathLike):
        return False  # integer descriptors and exotic targets
    raw: str | bytes = os.fspath(target)
    if isinstance(raw, bytes):
        try:
            raw = raw.decode()
        except UnicodeDecodeError:
            return True  # fail closed on undecodable paths
    try:
        resolved = Path(raw).resolve()
    except (OSError, ValueError):
        return True  # fail closed when the path cannot be resolved
    return any(resolved == root or resolved.is_relative_to(root) for root in _PROTECTED_ROOTS)


def _deny_protected(target: object) -> None:
    raise PermissionError(
        "reading the repository inbox/ and results/ directories is blocked in BidFusion tests"
    )


def _dir_fd_base(dir_fd: int) -> Path | None:
    """Real filesystem path behind ``dir_fd``, or ``None`` when unknown."""
    if hasattr(fcntl, "F_GETPATH"):  # macOS / BSD
        try:
            raw = fcntl.fcntl(dir_fd, fcntl.F_GETPATH, bytes(1024))
        except OSError:
            return None
        return Path(os.fsdecode(raw.rstrip(b"\x00")))
    proc_link = f"/proc/self/fd/{dir_fd}"  # Linux
    try:
        return Path(os.readlink(proc_link))
    except OSError:
        return None


def _guarded_io_open(file: Any, *args: Any, **kwargs: Any) -> Any:
    if _is_protected_path(file):
        _deny_protected(file)
    return _REAL_IO_OPEN(file, *args, **kwargs)


def _guarded_os_open(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
    if dir_fd is not None and isinstance(path, str | bytes | os.PathLike):
        raw = os.fsdecode(os.fspath(path))
        if os.path.isabs(raw):
            if _is_protected_path(raw):
                _deny_protected(path)
        else:
            base = _dir_fd_base(dir_fd)
            if base is None:
                # Fail closed: an unresolvable dir_fd cannot be verified.
                _deny_protected(path)
            else:
                if _is_protected_path(base / raw):
                    _deny_protected(path)
    elif _is_protected_path(path):
        _deny_protected(path)
    return _REAL_OS_OPEN(path, flags, mode, dir_fd=dir_fd)


_GUARDS_INSTALLED = False


def pytest_configure(config: pytest.Config) -> None:
    """Install the session-wide guards before collection and any test code.

    Installation happens exactly once per process and is deliberately not
    undone: the guards are meant to cover import-time, fixture-time, and
    test-time code alike. They intercept at the Python level only — this is
    protection against accidental access, not an OS sandbox.
    """
    global _GUARDS_INSTALLED
    if _GUARDS_INSTALLED:
        return
    _GUARDS_INSTALLED = True

    # Network: no INET/INET6 socket construction, no connection/datagram
    # methods on pre-existing sockets, no regular DNS resolution.
    socket.socket = _GuardedSocket  # type: ignore[misc]
    socket.create_connection = _network_blocked  # type: ignore[assignment]
    for method in ("connect", "connect_ex", "sendto", "sendmsg"):
        setattr(_REAL_SOCKET_CLASS, method, _guarded_socket_method(method))
    for name in _DNS_FUNCTIONS:
        setattr(socket, name, _dns_blocked)

    # Subprocess and the known os process surface (allowlisted per marker).
    subprocess.Popen = _guarded_popen  # type: ignore[misc,assignment]
    for name in _OS_PROCESS_FUNCTIONS:
        if hasattr(os, name):
            setattr(os, name, _guarded_os_process(name))

    # Protected repository paths.
    builtins.open = _guarded_io_open
    io.open = _guarded_io_open
    os.open = _guarded_os_open


@pytest.fixture
def unguarded_socket_class() -> type[socket.socket]:
    """The real socket class, for self-testing the method-level guards."""
    return _REAL_SOCKET_CLASS


@pytest.fixture
def canonicals_builder() -> Any:
    """The full gate-to-canonical chain builder, for custom test packages."""
    return build_package_canonicals


@pytest.fixture(scope="session")
def rfp_minimal_canonicals() -> tuple[CanonicalDocument, ...]:
    """Canonical documents of the clean fixture package, built once per session."""
    return build_rfp_minimal_canonicals()


@pytest.fixture(scope="session")
def rfp_quality_canonicals() -> tuple[CanonicalDocument, ...]:
    """Canonical documents of the quality-review fixture package."""
    return build_package_canonicals(
        SYNTHETIC_FIXTURES / "rfp-quality-review",
        ("mixed-scan.pdf", "quality-matrix.xlsx"),
    )
