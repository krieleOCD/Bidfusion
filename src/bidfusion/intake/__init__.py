"""Domain A - RFP intake. Registers incoming bid packages.

A bid (e.g. ``BID-2026-000123``) is the top-level isolation unit:
every artifact in the system is assigned to exactly one bid."""

from bidfusion.intake.register import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    RegisteredDocument,
    RegisteredPackage,
    RejectedFile,
    register_package,
)

__all__ = [
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "RegisteredDocument",
    "RegisteredPackage",
    "RejectedFile",
    "register_package",
]
