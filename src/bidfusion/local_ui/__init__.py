"""Local demonstration UI: a thin presentation layer over the pipeline.

This package contains no security-, parsing-, extraction-,
normalization-, or quality logic. It lists the trusted synthetic
fixture packages, starts runs through the existing
:func:`bidfusion.orchestration.run_package` API, and renders the
versioned run artifacts. Pipeline status always comes from the run
summaries and artifacts on disk — never from the UI itself.
"""
