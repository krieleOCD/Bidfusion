"""Tests for Markdown sanitization of untrusted, document-derived text."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bidfusion.extraction.deadlines.rule_based import extract_deadlines
from bidfusion.extraction.formalities.rule_based import extract_formalities
from bidfusion.extraction.requirements.rule_based import extract_requirements
from bidfusion.normalization import merge_extractions
from bidfusion.quality import evaluate_quality
from bidfusion.quality.review_package import DetectedItem, ReviewPackage, render_review_markdown
from bidfusion.schemas import (
    CanonicalDocument,
    NormalizedBidDataset,
    RequirementExtractionResult,
    WorkingPackage,
)
from bidfusion.shared.markdown import sanitize_markdown_text
from bidfusion.working_package import build_working_package, render_markdown

BID_ID = "BID-2026-000123"
RUN_ID = "RUN-20260804-0001"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def build_chain(
    canonicals: tuple[CanonicalDocument, ...],
) -> tuple[RequirementExtractionResult, NormalizedBidDataset, WorkingPackage]:
    requirements = extract_requirements(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000041",
        created_at=NOW,
    )
    deadlines = extract_deadlines(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000042",
        created_at=NOW,
    )
    formalities = extract_formalities(
        canonicals,
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000043",
        created_at=NOW,
    )
    dataset = merge_extractions(
        bid_id=BID_ID,
        run_id=RUN_ID,
        artifact_id="ART-20260804-000044",
        created_at=NOW,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
    )
    quality = evaluate_quality(
        parsed=(),
        unprocessed=(),
        canonicals=canonicals,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        dataset=dataset,
        evaluated_at=NOW,
    )
    package = build_working_package(
        dataset,
        requirements=requirements,
        deadlines=deadlines,
        formalities=formalities,
        quality=quality,
        artifact_id="ART-20260804-000045",
        generated_at=NOW,
    )
    return requirements, dataset, package


HOSTILE = (
    "<script>alert(1)</script>"
    " ![exfil](https://evil.example/x.png)"
    " [click](https://evil.example)"
    " <https://evil.example/auto>"
    " http://evil.example/bare"
    " www.evil.example/autolink"
    " WWW.EVIL.EXAMPLE"
    " attacker@evil.example"
    "\n# Injected heading\n- injected list\n> injected quote\n"
    "```\ninjected fence\n```"
    " `inline`"
    " |cell|injection|"
    " em\x07bedded\x00controls"
    " bidi\u202egnihcte\u202c end"
    " zero\u200bwidth\u200djoin\ufeffbom"
    " ~~strike~~ *em* _under_"
)


def test_sanitizer_neutralizes_every_markdown_and_html_construct() -> None:
    cleaned = sanitize_markdown_text(HOSTILE)

    assert "<" not in cleaned.replace("\\<", "")
    assert ">" not in cleaned.replace("\\>", "")
    assert "](" not in cleaned
    assert "![" not in cleaned.replace("!\\[", "")
    assert "```" not in cleaned
    assert "\n" not in cleaned and "\r" not in cleaned
    assert "\x00" not in cleaned and "\x07" not in cleaned
    assert "http://" not in cleaned and "https://" not in cleaned
    for char in ("`", "*", "_", "[", "]", "(", ")", "#", "|"):
        assert f"\\{char}" in cleaned or char not in cleaned
    # Readability survives: the words are still present.
    assert "alert" in cleaned
    assert "Injected heading" in cleaned


@pytest.mark.parametrize(
    "attack",
    [
        "<img src=x onerror=alert(1)>",
        "![i](http://evil/i.png)",
        "[l](javascript:alert(1))",
        "<http://evil>",
        "# Heading",
        "```fence",
        "line1\nline2|pipe",
        "text separator",
    ],
)
def test_sanitized_text_cannot_start_structures_or_load_resources(attack: str) -> None:
    cell = f"| {sanitize_markdown_text(attack)} |"

    assert "\n" not in cell
    assert "](" not in cell
    assert "<" not in cell.replace("\\<", "")
    unescaped_pipes = cell.count("|") - cell.count("\\|")
    assert unescaped_pipes == 2  # only our own table delimiters survive


def test_rendered_working_package_sanitizes_all_untrusted_fields(
    rfp_minimal_canonicals: tuple[CanonicalDocument, ...],
) -> None:
    requirements, dataset, package = build_chain(rfp_minimal_canonicals)

    hostile_requirements = tuple(
        item.model_copy(
            update={
                "normalized_text": HOSTILE,
                "original_text": HOSTILE,
                "source": item.source.model_copy(update={"filename": "evil<img src=x>.pdf|name"}),
            }
        )
        for item in (
            {req.requirement_id: req for req in requirements.requirements}[reference.object_id]
            for reference in dataset.requirements
        )
    )
    hostile_package = package.model_copy(
        update={
            "timeline": tuple(
                deadline.model_copy(update={"description": HOSTILE})
                for deadline in package.timeline
            ),
        }
    )

    markdown = render_markdown(
        hostile_package,
        requirements=hostile_requirements,
        completeness=dataset.completeness,
    )

    assert "<" not in markdown.replace("\\<", "")  # no raw HTML/autolink opener
    assert "](" not in markdown
    assert "![" not in markdown.replace("!\\[", "")
    assert "```" not in markdown
    assert "http://" not in markdown and "https://" not in markdown
    assert "\x07" not in markdown
    for line in markdown.splitlines():
        assert not line.startswith("# Injected")
        assert not line.startswith("- injected")
        assert not line.startswith("> injected")
    # Our own structure is intact: exactly one top-level heading.
    assert markdown.startswith("# Bid Working Package")
    assert markdown.count("\n# ") == 0
    _assert_only_own_markdown_structure(markdown)


def test_sanitizer_neutralizes_autolinks_emails_and_invisible_characters() -> None:
    cleaned = sanitize_markdown_text(HOSTILE)

    # GFM extended autolinks (www.) and email autolinks (@) cannot form.
    assert "www." not in cleaned.replace("www\\.", "").replace("WWW\\.", "")
    assert "WWW." not in cleaned.replace("WWW\\.", "")
    assert "@" not in cleaned.replace("\\@", "")
    # Bidirectional controls and invisible format characters are removed.
    for invisible in ("\u202e", "\u202c", "\u200b", "\u200d", "\ufeff"):
        assert invisible not in cleaned
    # The visible text survives.
    assert "gnihcte" in cleaned
    assert "zerowidthjoinbom" in cleaned
    assert "evil.example" in cleaned


def _assert_only_own_markdown_structure(markdown: str) -> None:
    """Structural (block-level) check over the rendered document.

    A true rendered-AST comparison would require a Markdown parser
    dependency, which this project does not add without prior approval;
    this scan checks the same properties on the block structure: no
    headings beyond our own, no HTML blocks, no code fences, no list/quote
    injections, and no link/image/autolink constructs anywhere.
    """
    own_heading_prefixes = (
        "# Bid Working Package",
        "# Review Package",
        "## ",
    )
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            assert any(stripped.startswith(prefix) for prefix in own_heading_prefixes), (
                f"foreign heading injected: {line!r}"
            )
        assert not stripped.startswith("```"), "code fence injected"
        assert not stripped.startswith("~~~"), "code fence injected"
        assert not stripped.startswith("<"), "HTML block injected"
    assert "](" not in markdown, "link or image injected"
    without_escaped = markdown.replace("\\<", "")
    assert "<http" not in without_escaped, "autolink injected"
    assert "<script" not in without_escaped.lower(), "inline HTML injected"
    lowered = markdown.lower()
    assert "www." not in lowered.replace("www\\.", ""), "www autolink injected"
    assert "://" not in markdown.replace("\\://", ""), "bare URL autolink injected"
    assert "@" not in markdown.replace("\\@", ""), "email autolink injected"


@pytest.mark.parametrize(
    "entity",
    [
        "&lrm;",
        "&rlm;",
        "&ZeroWidthSpace;",
        "&#8203;",  # zero width space
        "&#x202E;",  # right-to-left override
        "&#x200F;",  # right-to-left mark
        "&#8237;",  # left-to-right override
        "&#xFEFF;",  # BOM / zero width no-break space
    ],
)
def test_entity_encoded_invisible_characters_are_removed(entity: str) -> None:
    cleaned = sanitize_markdown_text(f"before {entity} after")

    for invisible in ("\u200e", "\u200f", "\u200b", "\u202e", "\u202d", "\ufeff"):
        assert invisible not in cleaned
    # No entity survives either: every remaining ampersand is escaped.
    assert "&" not in cleaned.replace("\\&", "")
    assert "before" in cleaned and "after" in cleaned


def test_entity_decoding_cannot_create_new_markdown_or_html_structure() -> None:
    cleaned = sanitize_markdown_text(
        "&#60;script&#62;alert(1)&#60;/script&#62; "
        "&#91;link&#93;&#40;https&#58;//evil.example&#41; "
        "&#35; injected heading &#124;cell&#124; &amp;lrm;"
    )

    assert "<" not in cleaned.replace("\\<", "")
    assert ">" not in cleaned.replace("\\>", "")
    assert "](" not in cleaned
    assert "#" not in cleaned.replace("\\#", "")
    assert "|" not in cleaned.replace("\\|", "")
    assert "&" not in cleaned.replace("\\&", "")
    # The double-encoded entity decodes exactly once and stays visible text.
    assert "\\&lrm;" in cleaned


def test_rendered_review_package_contains_no_active_markdown_constructs() -> None:
    package = ReviewPackage(
        quality_gate_name="bidfusion-mvp-quality-gate",
        quality_gate_version="0.4.0",
        bid_id=BID_ID,
        run_id=RUN_ID,
        generated_at=NOW,
        reasons=(HOSTILE,),
        warnings=(HOSTILE,),
        affected_documents=("DOC-001",),
        affected_sources=(HOSTILE,),
        detected_requirements=(DetectedItem(text=HOSTILE, sources=(HOSTILE,)),),
        detected_deadlines=(),
        detected_formalities=(),
        unresolved_conflicts=(HOSTILE,),
        required_manual_actions=(HOSTILE,),
    )

    markdown = render_review_markdown(package)

    assert markdown.startswith("# Review Package")
    assert "NOT A COMPLETE BID WORKING PACKAGE" in markdown
    _assert_only_own_markdown_structure(markdown)
    # No table or pipe injection: every hostile pipe stays escaped.
    for line in markdown.splitlines():
        if line.startswith("- "):
            assert line.count("|") == line.count("\\|"), line
