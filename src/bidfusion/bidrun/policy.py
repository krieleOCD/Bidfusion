"""Central, versioned upload acceptance policy.

Every numeric or type limit the quarantine service enforces lives here —
never as a scattered literal in :mod:`bidfusion.bidrun.quarantine`. This
is acceptance *policy* (which uploads are even considered), not a
security verdict: passing it only ever reaches ``QUARANTINED``, never
``ALLOW``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bidfusion.shared.filetype import EXTENSION_MIME_TYPES

POLICY_NAME = "bidfusion-upload-policy"
POLICY_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class UploadPolicy:
    """Versioned limits and type allowlist for one quarantine attempt."""

    policy_name: str
    policy_version: str
    max_file_size_bytes: int
    max_package_size_bytes: int
    max_files_per_package: int
    allowed_extensions: frozenset[str]
    allowed_mime_types_by_extension: dict[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.policy_name.strip() or not self.policy_version.strip():
            msg = "policy name and version must be non-empty"
            raise ValueError(msg)
        numeric_limits = (
            self.max_file_size_bytes,
            self.max_package_size_bytes,
            self.max_files_per_package,
        )
        if any(limit <= 0 for limit in numeric_limits):
            msg = "upload policy limits must be positive"
            raise ValueError(msg)
        if self.max_file_size_bytes > self.max_package_size_bytes:
            msg = "a single file cannot be allowed to exceed the whole-package limit"
            raise ValueError(msg)
        if not self.allowed_extensions:
            msg = "an upload policy must allow at least one extension"
            raise ValueError(msg)
        if any(extension != extension.lower() for extension in self.allowed_extensions):
            msg = "allowed_extensions must be lowercase"
            raise ValueError(msg)
        missing = self.allowed_extensions - self.allowed_mime_types_by_extension.keys()
        if missing:
            msg = f"allowed_mime_types_by_extension is missing entries for: {sorted(missing)}"
            raise ValueError(msg)


#: The current slice's fixed values (docs/architecture/level-1-target.md,
#: §9). Every quarantine call defaults to this policy; a later slice may
#: introduce operator-configurable policies without breaking this one.
DEFAULT_UPLOAD_POLICY = UploadPolicy(
    policy_name=POLICY_NAME,
    policy_version=POLICY_VERSION,
    max_file_size_bytes=25 * 1024 * 1024,
    max_package_size_bytes=100 * 1024 * 1024,
    max_files_per_package=20,
    allowed_extensions=frozenset({"pdf", "xlsx", "txt"}),
    allowed_mime_types_by_extension={
        "pdf": EXTENSION_MIME_TYPES["pdf"],
        "xlsx": EXTENSION_MIME_TYPES["xlsx"],
        "txt": EXTENSION_MIME_TYPES["txt"],
    },
)
