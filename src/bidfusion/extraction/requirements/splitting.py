"""Atomic requirement splitting v0.4 for assembled clause blocks.

Candidate detection (v0.2/v0.3 rule families) and atomic splitting stay
separate stages: the splitter takes one already-detected compound block and
derives atomic children from deterministic source structure only — bullet
markers, heading levels, and line continuation. It never invents text: a
child's ``original_text`` is the verbatim join of its own source units,
while ``effective_text`` additionally inherits the lead-in/heading context
needed to keep the child independently understandable. Every source unit of
the block stays traceable through exactly the children it belongs to.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from bidfusion.extraction.requirements.label_free import (
    _NON_POSITION_PREFIXES,
    _POSITION_CODE_TOKEN,
    BlockDetection,
    RuleFamily,
    normative_sentence_signal,
)
from bidfusion.extraction.requirements.signals import structural_identifier
from bidfusion.extraction.support import TextUnit


class SplitRule(StrEnum):
    """Which deterministic structure produced an atomic child."""

    BULLET_ITEM = "bullet-item"
    ASSIGNMENT_ROW = "assignment-row"
    NORMATIVE_SENTENCE = "normative-sentence"
    POSITION_ROW = "position-row"


@dataclass(frozen=True, slots=True)
class AtomicSplit:
    """One atomic child of a compound candidate, with full provenance."""

    split_rule: SplitRule
    split_index: int
    split_total: int
    units: tuple[TextUnit, ...]
    context_units: tuple[TextUnit, ...]
    original_text: str
    effective_text: str


#: Bounded bullet hierarchy of parsed tender PDFs: filled squares open
#: top-level items, small markers open nested items. A marker is only a
#: marker at the start of a line unit.
_LEVEL_ONE_MARKERS = "◼■"
_LEVEL_TWO_MARKERS = "▪•●‣○"
_MARKER_STRIP = re.compile(rf"^[{_LEVEL_ONE_MARKERS}{_LEVEL_TWO_MARKERS}]\s*")

#: Page furniture of print layouts ("Seite 7 (15) ..."): traceable as
#: provenance, never requirement text.
_PAGE_FURNITURE = re.compile(r"^Seite\s+\d", re.IGNORECASE)

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
#: Trailing contractor/customer assignment of a responsibility-matrix row.
_TRAILING_ASSIGNMENT = re.compile(r"(?:^|\s)AN(?:\s+AG)?\s*$")
_SENTENCE_END = (".", "!", "?")
_MAX_HEADING_WORDS = 12
#: An item stands alone only with at least this many content-bearing words;
#: shorter neighbours merge into one residual child so single nouns of an
#: enumeration ("Telefon", "E-Mail") never become free-floating fragments.
_MIN_STANDALONE_TOKENS = 2
_SIGNIFICANT_TOKEN_LENGTH = 4


def _bullet_level(text: str) -> int | None:
    first = text.lstrip()[:1]
    if first in _LEVEL_ONE_MARKERS:
        return 1
    if first in _LEVEL_TWO_MARKERS:
        return 2
    return None


def _strip_marker(text: str) -> str:
    return _MARKER_STRIP.sub("", text.strip())


def _significant_tokens(text: str) -> int:
    normalized = _PUNCTUATION.sub(" ", unicodedata.normalize("NFKC", text).casefold())
    return sum(1 for token in normalized.split() if len(token) >= _SIGNIFICANT_TOKEN_LENGTH)


@dataclass(slots=True)
class _Item:
    """One bullet item (or lead sentence) while the block is being walked."""

    units: list[TextUnit]
    headings: tuple[TextUnit, ...]
    residual: bool = False
    rule: SplitRule = SplitRule.BULLET_ITEM
    closed: bool = False

    @property
    def text(self) -> str:
        parts = [_strip_marker(self.units[0].text)]
        parts.extend(unit.text.strip() for unit in self.units[1:])
        return " ".join(parts)


def split_block(units: Sequence[TextUnit], detection: BlockDetection) -> tuple[AtomicSplit, ...]:
    """Split one detected clause block into atomic children, or ``()``.

    Splitting is purely structural: it fires only when the block carries at
    least two bullet items and at least two children survive the residual
    joining of short enumeration entries.
    """
    levels = [_bullet_level(unit.text) for unit in units]
    if sum(1 for level in levels if level is not None) >= 2:
        return _split_bullet_items(tuple(units), levels)
    rows = _split_assignment_rows(tuple(units))
    if rows:
        return rows
    if detection.family is RuleFamily.PRICED_POSITION:
        return _split_position_rows(tuple(units))
    if detection.family in _SENTENCE_SPLIT_EXCLUDED_FAMILIES:
        return ()
    return _split_normative_sentences(tuple(units))


def _split_bullet_items(
    units: tuple[TextUnit, ...], levels: list[int | None]
) -> tuple[AtomicSplit, ...]:
    first_bullet = next(index for index, level in enumerate(levels) if level is not None)
    lead_units = units[:first_bullet]
    lead_text = " ".join(unit.text for unit in lead_units).strip()

    lead_child: _Item | None = None
    shared_context: tuple[TextUnit, ...] = ()
    plain_context: tuple[TextUnit, ...] = ()
    if lead_units:
        if _PAGE_FURNITURE.match(lead_text):
            plain_context = lead_units
        elif lead_text.endswith(":") or (
            structural_identifier(lead_text) is not None
            and len(lead_text.split()) <= _MAX_HEADING_WORDS
        ):
            # only an explicit lead-in (colon) or a short numbered heading
            # is context; any other lead run is requirement text of its
            # own and never silently dropped
            shared_context = lead_units
        else:
            lead_child = _Item(units=list(lead_units), headings=())

    items: list[_Item] = []
    headings: dict[int, TextUnit] = {}
    index = first_bullet
    while index < len(units):
        unit = units[index]
        level = levels[index]
        if level is None:
            # continuation line — of the current item, or of the next
            # responsibility-matrix row once a trailing marker closed it
            if items and not items[-1].closed:
                items[-1].units.append(unit)
            elif items:
                items.append(
                    _Item(
                        units=[unit],
                        headings=items[-1].headings,
                        rule=SplitRule.ASSIGNMENT_ROW,
                    )
                )
            if items and _ends_with_assignment_marker(unit.text):
                items[-1].closed = True
            index += 1
            continue
        headings = {known: heading for known, heading in headings.items() if known < level}
        next_level = levels[index + 1] if index + 1 < len(units) else None
        if next_level is not None and next_level > level:
            headings[level] = unit
            index += 1
            continue
        items.append(
            _Item(
                units=[unit],
                headings=tuple(heading for _, heading in sorted(headings.items())),
                closed=_ends_with_assignment_marker(unit.text),
            )
        )
        index += 1

    children: list[_Item] = [lead_child] if lead_child is not None else []
    children.extend(_join_short_items(items))
    if len(children) < 2:
        return ()

    total = len(children)
    splits: list[AtomicSplit] = []
    for child_index, child in enumerate(children, start=1):
        context = tuple(child.headings)
        if child is not lead_child:
            context = shared_context + context
        provenance_context = context
        if child_index == 1:
            provenance_context = plain_context + provenance_context
        splits.append(
            AtomicSplit(
                split_rule=child.rule,
                split_index=child_index,
                split_total=total,
                units=tuple(child.units),
                context_units=provenance_context,
                original_text=" ".join(unit.text for unit in child.units),
                effective_text=_effective_text(context, child),
            )
        )
    return tuple(splits)


def _split_assignment_rows(units: tuple[TextUnit, ...]) -> tuple[AtomicSplit, ...]:
    """One child per responsibility-matrix row of a bullet-less block.

    A row ends at a unit whose text ends in the trailing party marker;
    wrapped lines in between belong to the row. At least two marker rows
    must exist, so ordinary prose never reaches this rule.
    """
    if sum(1 for unit in units if _ends_with_assignment_marker(unit.text)) < 2:
        return ()
    items: list[_Item] = []
    current: list[TextUnit] = []
    for unit in units:
        current.append(unit)
        if _ends_with_assignment_marker(unit.text):
            items.append(_Item(units=current, headings=(), rule=SplitRule.ASSIGNMENT_ROW))
            current = []
    if current:
        if not items:
            return ()
        items[-1].units.extend(current)
    children = _join_short_items(items)
    if len(children) < 2:
        return ()
    total = len(children)
    return tuple(
        AtomicSplit(
            split_rule=child.rule,
            split_index=child_index,
            split_total=total,
            units=tuple(child.units),
            context_units=(),
            original_text=" ".join(unit.text for unit in child.units),
            effective_text=_effective_text((), child),
        )
        for child_index, child in enumerate(children, start=1)
    )


def _join_short_items(items: list[_Item]) -> list[_Item]:
    """Merge runs of short enumeration entries under one heading."""
    joined: list[_Item] = []
    for item in items:
        item.residual = _significant_tokens(item.text) < _MIN_STANDALONE_TOKENS
        if (
            item.residual
            and joined
            and joined[-1].residual
            and joined[-1].headings == item.headings
        ):
            joined[-1].units.extend(item.units)
            continue
        joined.append(item)
    joined = _merge_assignment_fragments(joined)
    return _revert_abbreviation_groups(joined)


def _merge_assignment_fragments(items: list[_Item]) -> list[_Item]:
    """One-word responsibility-matrix rows stay with their neighbour row."""
    merged: list[_Item] = []
    pending: _Item | None = None
    for item in items:
        if item.residual and _TRAILING_ASSIGNMENT.search(item.text):
            if merged:
                merged[-1].units.extend(item.units)
            else:
                pending = item
            continue
        if pending is not None:
            item.units[:0] = pending.units
            pending = None
        merged.append(item)
    if pending is not None:
        merged.append(pending)
    return merged


def _revert_abbreviation_groups(items: list[_Item]) -> list[_Item]:
    """Groups with abbreviation-only entries honestly stay one compound.

    An entry without any content-bearing token ("BHB") cannot stand alone,
    and promoting its heading into candidate text would let the heading
    cross-map into every sibling entry; the whole group reverts instead.
    """

    def group_key(item: _Item) -> tuple[str | None, ...]:
        return tuple(unit.source.locator.paragraph_id for unit in item.headings)

    revert_keys = {
        group_key(item)
        for item in items
        if item.residual
        and item.headings
        and _significant_tokens(" ".join(unit.text for unit in item.units)) == 0
    }
    reverted: list[_Item] = []
    seen: dict[tuple[str | None, ...], _Item] = {}
    for item in items:
        key = group_key(item)
        if not item.headings or key not in revert_keys:
            reverted.append(item)
            continue
        group = seen.get(key)
        if group is None:
            group = _Item(
                units=[item.headings[-1], *item.units],
                headings=item.headings[:-1],
            )
            seen[key] = group
            reverted.append(group)
        else:
            group.units.extend(item.units)
    return reverted


#: Bounded German tender abbreviations whose trailing period never ends a
#: sentence. Compared lowercased and without the final period.
_ABBREVIATIONS = frozenset(
    {
        "z.b",
        "ggf",
        "bzw",
        "ca",
        "inkl",
        "zzgl",
        "u.a",
        "d.h",
        "i.d.r",
        "o.g",
        "s.o",
        "s.u",
        "nr",
        "ziff",
        "abs",
        "gem",
        "vgl",
        "etc",
        "evtl",
        "max",
        "min",
        "mind",
    }
)
_SENTENCE_BOUNDARY = re.compile(r"[.!?]\s+")
_MIN_SENTENCE_WORDS = 4

#: Families whose blocks never sentence-split. Catalogue position rows are
#: no prose at all; performative contractor commitments describe one
#: capability across sentences — measured against real tender text,
#: sentence children of that family broke more requirement units than
#: they freed.
_SENTENCE_SPLIT_EXCLUDED_FAMILIES = frozenset(
    {
        RuleFamily.PRICED_POSITION,
        RuleFamily.PERFORMATIVE_OBLIGATION,
        RuleFamily.MODAL_STATEMENT,
    }
)

#: German article/preposition before a trailing ``AN``: contract prose
#: ("... durch den AN"), never a responsibility-matrix row terminator.
_AN_PROSE_PRECEDERS = frozenset({"der", "des", "dem", "den", "vom", "durch", "zum", "beim"})


def _ends_with_assignment_marker(text: str) -> bool:
    match = _TRAILING_ASSIGNMENT.search(text)
    if match is None:
        return False
    prefix = text[: match.start()].rstrip()
    last_word = prefix.rsplit(None, 1)[-1].lower() if prefix.split() else ""
    return last_word not in _AN_PROSE_PRECEDERS


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Deterministic sentence spans; abbreviation and number periods bind.

    A period directly after a digit never splits (dates, numberings,
    thresholds), and neither does one that closes a bounded abbreviation.
    """
    starts = [0]
    for match in _SENTENCE_BOUNDARY.finditer(text):
        before = text[: match.start()]
        if before and before[-1].isdigit():
            continue
        last_word = before.rsplit(None, 1)[-1] if before.split() else ""
        if last_word.rstrip(".").lower().lstrip("(„\"'") in _ABBREVIATIONS:
            continue
        follower = text[match.end() : match.end() + 1]
        if follower and not (follower.isupper() or follower.isdigit() or follower in '„"('):
            continue
        starts.append(match.end())
    spans = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        if text[start:end].strip():
            spans.append((start, end))
    return spans


def _split_normative_sentences(units: tuple[TextUnit, ...]) -> tuple[AtomicSplit, ...]:
    """One child per independently signalled sentence of a clause block.

    Sentences without their own bounded obligation signal stay with the
    preceding child (or open the first one), so definitional prose is never
    orphaned. Splitting fires only when at least two sentences qualify.
    """
    text = " ".join(unit.text for unit in units)
    spans = _sentence_spans(text)
    qualifying = [
        len(text[start:end].split()) >= _MIN_SENTENCE_WORDS
        and normative_sentence_signal(text[start:end])
        for start, end in spans
    ]
    if sum(qualifying) < 2:
        return ()

    child_spans: list[tuple[int, int]] = []
    for (start, end), qualifies in zip(spans, qualifying, strict=True):
        if qualifies or not child_spans:
            child_spans.append((start, end))
        else:
            child_spans[-1] = (child_spans[-1][0], end)

    return _splits_from_spans(units, text, child_spans, SplitRule.NORMATIVE_SENTENCE)


def _splits_from_spans(
    units: tuple[TextUnit, ...],
    text: str,
    child_spans: list[tuple[int, int]],
    rule: SplitRule,
    *,
    context_units: tuple[TextUnit, ...] = (),
    effective_prefix: str = "",
) -> tuple[AtomicSplit, ...]:
    """Children from character spans of the joined block text.

    Each child owns every unit its span overlaps, so a wrapped line that
    carries the end of one child and the start of the next stays traceable
    from both.
    """
    offsets: list[tuple[int, int]] = []
    position = 0
    for unit in units:
        offsets.append((position, position + len(unit.text)))
        position += len(unit.text) + 1

    total = len(child_spans)
    splits: list[AtomicSplit] = []
    for child_index, (start, end) in enumerate(child_spans, start=1):
        own = tuple(
            unit
            for unit, (unit_start, unit_end) in zip(units, offsets, strict=True)
            if unit_start < end and unit_end > start
        )
        original = text[start:end].strip()
        splits.append(
            AtomicSplit(
                split_rule=rule,
                split_index=child_index,
                split_total=total,
                units=own,
                context_units=context_units if child_index == 1 else (),
                original_text=original,
                effective_text=(
                    f"{effective_prefix}: {original}" if effective_prefix else original
                ),
            )
        )
    return tuple(splits)


def _split_position_rows(units: tuple[TextUnit, ...]) -> tuple[AtomicSplit, ...]:
    """One child per catalogue position row of flattened table text.

    Rows start at letters-first position codes ("SO-ITSec-006"); standard
    and vulnerability references never open a row. Text before the first
    code is the flattened table header and stays context.
    """
    text = " ".join(unit.text for unit in units)
    starts = [
        match.start()
        for match in _POSITION_CODE_TOKEN.finditer(text)
        if match.group(1).upper() not in _NON_POSITION_PREFIXES
    ]
    if len(starts) < 2:
        return ()
    child_spans: list[tuple[int, int]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        segment = (start, end)
        if child_spans and _significant_tokens(text[start:end]) < _MIN_STANDALONE_TOKENS:
            child_spans[-1] = (child_spans[-1][0], end)
        else:
            child_spans.append(segment)
    if len(child_spans) < 2:
        return ()

    header = text[: starts[0]].strip()
    offsets_needed = starts[0] > 0
    header_units: tuple[TextUnit, ...] = ()
    if offsets_needed:
        position = 0
        collected: list[TextUnit] = []
        for unit in units:
            if position >= starts[0]:
                break
            collected.append(unit)
            position += len(unit.text) + 1
        header_units = tuple(collected)
    prefix = header if header and len(header.split()) <= _MAX_HEADING_WORDS else ""
    return _splits_from_spans(
        units,
        text,
        child_spans,
        SplitRule.POSITION_ROW,
        context_units=header_units,
        effective_prefix=prefix,
    )


def _effective_text(context: tuple[TextUnit, ...], child: _Item) -> str:
    """Context-inherited reading text; item boundaries stay visible."""
    item_texts = [
        _strip_marker(unit.text) if _bullet_level(unit.text) is not None else unit.text.strip()
        for unit in child.units
    ]
    # continuation lines join with a space, sibling short items with "; "
    rendered: list[str] = []
    for unit, text in zip(child.units, item_texts, strict=True):
        if rendered and _bullet_level(unit.text) is not None:
            rendered.append("; " + text)
        elif rendered:
            rendered.append(" " + text)
        else:
            rendered.append(text)
    item_text = "".join(rendered)
    # the trailing assignment marker is table layout, not requirement wording
    while _ends_with_assignment_marker(item_text):
        item_text = _TRAILING_ASSIGNMENT.sub("", item_text).rstrip()
    prefix = ": ".join(_strip_marker(unit.text).rstrip(":").strip() for unit in context)
    return f"{prefix}: {item_text}" if prefix else item_text
