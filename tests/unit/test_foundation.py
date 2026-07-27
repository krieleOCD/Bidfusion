"""Smoke tests: the foundation package imports and all domains exist."""

import importlib

import bidfusion

DOMAIN_PACKAGES = [
    "intake",
    "security",
    "inventory",
    "document_understanding",
    "extraction",
    "normalization",
    "quality",
    "working_package",
    "bid_intelligence",
    "golden_dataset",
    "orchestration",
    "provenance",
    "observability",
    "llm_gateway",
    "storage",
    "schemas",
    "shared",
]


def test_version() -> None:
    assert bidfusion.__version__ == "0.1.0"


def test_all_domain_packages_import() -> None:
    for name in DOMAIN_PACKAGES:
        module = importlib.import_module(f"bidfusion.{name}")
        assert module.__doc__, f"bidfusion.{name} must document its domain purpose"
