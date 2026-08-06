"""UploadPolicy values and invariants."""

from __future__ import annotations

import pytest

from bidfusion.bidrun.policy import DEFAULT_UPLOAD_POLICY, UploadPolicy


def test_default_policy_matches_the_agreed_values() -> None:
    assert DEFAULT_UPLOAD_POLICY.max_file_size_bytes == 25 * 1024 * 1024
    assert DEFAULT_UPLOAD_POLICY.max_package_size_bytes == 100 * 1024 * 1024
    assert DEFAULT_UPLOAD_POLICY.max_files_per_package == 20
    assert DEFAULT_UPLOAD_POLICY.allowed_extensions == frozenset({"pdf", "xlsx", "txt"})
    assert DEFAULT_UPLOAD_POLICY.policy_name
    assert DEFAULT_UPLOAD_POLICY.policy_version


def test_policy_rejects_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        UploadPolicy(
            policy_name="p",
            policy_version="0.1.0",
            max_file_size_bytes=0,
            max_package_size_bytes=10,
            max_files_per_package=1,
            allowed_extensions=frozenset({"pdf"}),
            allowed_mime_types_by_extension={"pdf": frozenset({"application/pdf"})},
        )


def test_policy_rejects_a_file_limit_above_the_package_limit() -> None:
    with pytest.raises(ValueError, match="exceed the whole-package limit"):
        UploadPolicy(
            policy_name="p",
            policy_version="0.1.0",
            max_file_size_bytes=100,
            max_package_size_bytes=10,
            max_files_per_package=1,
            allowed_extensions=frozenset({"pdf"}),
            allowed_mime_types_by_extension={"pdf": frozenset({"application/pdf"})},
        )


def test_policy_requires_a_mime_mapping_for_every_allowed_extension() -> None:
    with pytest.raises(ValueError, match="missing entries"):
        UploadPolicy(
            policy_name="p",
            policy_version="0.1.0",
            max_file_size_bytes=10,
            max_package_size_bytes=10,
            max_files_per_package=1,
            allowed_extensions=frozenset({"pdf", "xlsx"}),
            allowed_mime_types_by_extension={"pdf": frozenset({"application/pdf"})},
        )


def test_policy_rejects_uppercase_extensions() -> None:
    with pytest.raises(ValueError, match="lowercase"):
        UploadPolicy(
            policy_name="p",
            policy_version="0.1.0",
            max_file_size_bytes=10,
            max_package_size_bytes=10,
            max_files_per_package=1,
            allowed_extensions=frozenset({"PDF"}),
            allowed_mime_types_by_extension={"PDF": frozenset({"application/pdf"})},
        )
