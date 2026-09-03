"""Unit tests for the local UI application service (fixture listing).

The UI must offer exactly the trusted synthetic fixture packages and
nothing else; free or manipulated package names are rejected before any
path operation happens.
"""

from __future__ import annotations

import pytest

from bidfusion.local_ui import service
from bidfusion.shared.pathguards import trusted_synthetic_root

KNOWN_PACKAGES = (
    "rfp-blocked",
    "rfp-german-procurement",
    "rfp-minimal",
    "rfp-mtd",
    "rfp-quality-review",
    "rfp-review",
    "rfp-unsupported",
)


def test_list_packages_offers_exactly_the_known_synthetic_fixtures() -> None:
    packages = service.list_packages()

    assert tuple(package.name for package in packages) == KNOWN_PACKAGES
    by_name = {package.name: package for package in packages}
    minimal = by_name["rfp-minimal"]
    assert minimal.document_count == 3
    assert {file.name for file in minimal.files} == {
        "notes.txt",
        "requirements-matrix.xlsx",
        "rfp-invitation.pdf",
    }
    assert {file.file_type for file in minimal.files} == {"TXT", "XLSX", "PDF"}


def test_every_offered_package_lies_below_the_trusted_synthetic_root() -> None:
    root = trusted_synthetic_root()

    assert root is not None
    for package in service.list_packages():
        assert service.package_input_dir(package.name).is_relative_to(root)


@pytest.mark.parametrize(
    "name",
    [
        "does-not-exist",
        "",
        "..",
        "../rfp-minimal",
        "rfp-minimal/..",
        "rfp-minimal/../rfp-blocked",
        "/etc",
        "rfp-minimal/notes.txt",
        "README.md",
        "rfp-minimal ",
    ],
)
def test_unknown_or_manipulated_package_names_are_rejected(name: str) -> None:
    with pytest.raises(service.UnknownPackageError):
        service.package_input_dir(name)
