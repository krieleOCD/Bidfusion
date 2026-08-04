"""Central path guards protecting repository harness directories.

The repository's own ``inbox/`` and ``results/`` directories may hold
confidential customer documents and are never valid pipeline inputs or
outputs — not equal, not below, not via relative paths, ``..`` segments, or
symlinks. Callers pass **resolved** paths (``Path.resolve()`` follows
symlinks and eliminates ``..``); the checks here then walk the resolved
ancestor chain.

A directory is treated as a repository checkout when it contains a
``pyproject.toml``; harness directories are recognized as ``inbox``/
``results`` children of such a checkout.
"""

from __future__ import annotations

from pathlib import Path

_HARNESS_NAMES = frozenset({"inbox", "results"})


def is_repository_harness_path(resolved: Path) -> bool:
    """True when ``resolved`` is a repository inbox/results dir or below one."""
    for candidate in (resolved, *resolved.parents):
        if candidate.name in _HARNESS_NAMES and (candidate.parent / "pyproject.toml").is_file():
            return True
    return False


def is_inside_repository_checkout(resolved: Path) -> bool:
    """True when ``resolved`` lies inside (or is) a repository checkout."""
    return any(
        (candidate / "pyproject.toml").is_file() for candidate in (resolved, *resolved.parents)
    )


def repository_root() -> Path | None:
    """Resolved root of the repository checkout this code runs from, if any.

    Walks up from this module's resolved location to the first directory
    containing a ``pyproject.toml``. Returns ``None`` for installed
    distributions that do not live inside a checkout.
    """
    module_path = Path(__file__).resolve()
    for candidate in module_path.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def trusted_synthetic_root() -> Path | None:
    """The single trusted ``fixtures/synthetic/`` directory of this checkout.

    This is the only location whose inputs may be fully processed without
    the explicit non-production override. It is derived once from the
    repository root — never from path components of the input, so external
    directories that merely *contain* ``fixtures/synthetic`` segments are
    never trusted.
    """
    root = repository_root()
    if root is None:
        return None
    synthetic = root / "fixtures" / "synthetic"
    if not synthetic.is_dir():
        return None
    return synthetic.resolve()


def is_trusted_synthetic_input(resolved: Path) -> bool:
    """True when ``resolved`` lies below the one trusted synthetic root.

    Callers pass a **resolved** path, so symlinks that point outside the
    trusted root have already been followed and fail this check.
    """
    trusted = trusted_synthetic_root()
    return trusted is not None and resolved.is_relative_to(trusted)
