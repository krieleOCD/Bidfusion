"""Confidential-by-default file output for pipeline artifacts.

All generated run artifacts are treated as confidential: directories are
created with mode ``0700`` and files with mode ``0600`` regardless of the
process umask; nothing is group- or world-readable. Writes are atomic — a
temporary file in the target directory is written, flushed, fsynced, and
moved over the target with ``os.replace`` — so readers never observe a
half-written file and an existing file is either fully replaced or left
untouched.

Directory guarantees hold for *every* controlled directory, not only for
newly created ones: each controlled path is inspected with ``lstat``,
symlinks and non-directories are rejected fail-closed, pre-existing unsafe
modes are repaired to ``0700`` (or the operation fails), and the resulting
mode is verified again after repair.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def ensure_private_directory(directory: Path, *, root: Path | None = None) -> None:
    """Create or verify ``directory`` with owner-only access.

    Every controlled directory is enforced, top-down: ``directory`` itself,
    every component this call creates, and — when ``root`` is given — every
    component between ``root`` (inclusive) and ``directory``. Enforcement
    uses ``lstat``: symlinks and non-directories are rejected, unsafe
    pre-existing modes are repaired to ``0700`` (failing closed when the
    repair is not possible), and the resulting mode is re-verified.
    """
    for path in _controlled_chain(directory, root):
        if os.path.lexists(path):
            _enforce_private_directory(path)
        else:
            path.mkdir(mode=PRIVATE_DIR_MODE)
            _enforce_private_directory(path)


def _controlled_chain(directory: Path, root: Path | None) -> tuple[Path, ...]:
    """Controlled directories from the top down, ending at ``directory``."""
    chain = [directory]
    current = directory
    if root is not None:
        while current != root:
            parent = current.parent
            if parent == current:
                msg = "the target directory must lie below the controlled root"
                raise ValueError(msg)
            current = parent
            chain.append(current)
    # Missing ancestors will be created by this call and are controlled too;
    # pre-existing ancestors outside the chain are never touched.
    while True:
        parent = current.parent
        if parent == current or os.path.lexists(parent):
            break
        current = parent
        chain.append(current)
    return tuple(reversed(chain))


def _enforce_private_directory(path: Path) -> None:
    """Fail closed unless ``path`` is a real directory; force mode 0700."""
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        msg = f"controlled output path is a symlink (refusing to follow): {path}"
        raise ValueError(msg)
    if not stat.S_ISDIR(info.st_mode):
        msg = f"controlled output path is not a directory: {path}"
        raise ValueError(msg)
    if stat.S_IMODE(info.st_mode) != PRIVATE_DIR_MODE:
        os.chmod(path, PRIVATE_DIR_MODE)
    after = os.lstat(path)
    if not stat.S_ISDIR(after.st_mode) or stat.S_IMODE(after.st_mode) != PRIVATE_DIR_MODE:
        msg = f"controlled output directory could not be made owner-only: {path}"
        raise ValueError(msg)


def write_private_bytes(path: Path, data: bytes, *, root: Path | None = None) -> None:
    """Atomically write ``data`` to ``path`` with owner-only permissions."""
    ensure_private_directory(path.parent, root=root)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, PRIVATE_FILE_MODE)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_private_text(path: Path, text: str, *, root: Path | None = None) -> None:
    """Atomically write UTF-8 text to ``path`` with owner-only permissions."""
    write_private_bytes(path, text.encode("utf-8"), root=root)
