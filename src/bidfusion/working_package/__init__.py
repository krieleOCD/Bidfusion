"""Domain J - Bid Working Package.

The first human-oriented product of the pipeline: executive overview,
timeline, submission instructions, requirements overview, critical
requirements, risks, open questions - all backed by evidence."""

from bidfusion.working_package.builder import (
    WORKING_PACKAGE_BUILDER_NAME,
    WORKING_PACKAGE_BUILDER_VERSION,
    build_working_package,
)
from bidfusion.working_package.markdown import render_markdown

__all__ = [
    "WORKING_PACKAGE_BUILDER_NAME",
    "WORKING_PACKAGE_BUILDER_VERSION",
    "build_working_package",
    "render_markdown",
]
