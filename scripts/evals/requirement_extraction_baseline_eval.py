"""Requirement Extraction Baseline Evaluation #1 (read-only eval tooling).

Compares the deterministic BidFusion requirement extractor output of one
local pipeline run against the manually curated Ground Truth v1 workbook.

This script is EVALUATION TOOLING ONLY:
- it never modifies application code, Ground Truth, or run artifacts;
- it uses deterministic text comparison only (Unicode/whitespace/punctuation
  normalization, token overlap) — no LLM, no embeddings, no network;
- all outputs go to the gitignored runtime/evals/ directory.

Usage:
    uv run python scripts/evals/requirement_extraction_baseline_eval.py \
        --ground-truth <GT xlsx> --run-dir <pipeline run dir> --out-dir <dir>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import openpyxl

SCRIPT_VERSION = "1.1.0"

# Detection classes (Level 1)
EXACT = "EXACT_DETECTION"
PARTIAL = "PARTIAL_DETECTION"
MISSED = "MISSED"
AMBIGUOUS = "AMBIGUOUS_MAPPING"
FALSE_POSITIVE = "FALSE_POSITIVE"

# Deterministic mapping thresholds (token containment of GT wording in a
# single extractor candidate from the same source document).
EXACT_THRESHOLD = 0.85
PARTIAL_THRESHOLD = 0.50
AMBIGUITY_MARGIN = 0.05

# Text-presence tiers used for miss-reason evidence.
VERBATIM_PRESENT = "VERBATIM_PRESENT"
TOKEN_MAJORITY_PRESENT = "TOKEN_MAJORITY_PRESENT"
NOT_FOUND_IN_PARSE = "NOT_FOUND_IN_PARSE"
TOKEN_PRESENCE_THRESHOLD = 0.70

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
_REQ_LABEL = re.compile(r"\bREQ-[A-Za-z0-9]+\b")


def normalize(text: str) -> str:
    """Deterministic normalization: NFKC, casefold, strip punctuation/ws."""
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def tokens(text: str) -> set[str]:
    return {t for t in normalize(text).split() if len(t) > 3}


def containment(needle: set[str], haystack: set[str]) -> float:
    if not needle:
        return 0.0
    return len(needle & haystack) / len(needle)


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_gt(path: Path) -> tuple[list[dict], list[dict], list[str]]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    def sheet_rows(name: str) -> list[dict]:
        rows = list(wb[name].iter_rows(values_only=True))
        header = [str(h) for h in rows[0]]
        return [
            {header[i]: row[i] if i < len(row) else None for i in range(len(header))}
            for row in rows[1:]
            if any(v not in (None, "") for v in row)
        ]
    requirements = sheet_rows("Requirements_GT")
    facts = sheet_rows("Facts_and_Sizing")
    sources = [r["source_doc"] for r in sheet_rows("Source_Index")]
    return requirements, facts, sources


def load_run(run_dir: Path) -> tuple[dict, dict[str, dict], list[dict]]:
    summary = json.loads((run_dir / "run-summary.json").read_text())
    canonicals: dict[str, dict] = {}
    for doc in summary["documents"]:
        payload = run_dir / "canonical" / f"{doc['document_id']}-canonical.payload.json"
        if payload.is_file():
            canonicals[doc["document_id"]] = json.loads(payload.read_text())["payload"]
    extraction = json.loads(
        (run_dir / "extraction" / "requirement-extraction.payload.json").read_text()
    )["payload"]
    return summary, canonicals, extraction


def document_units(canonical: dict) -> list[str]:
    """All extractor-visible text units: paragraphs and table cells."""
    units: list[str] = []
    for page in canonical.get("pages", []):
        for para in page.get("paragraphs", []):
            if para.get("text"):
                units.append(para["text"])
        for table in page.get("tables", []):
            for row in table.get("rows", []):
                for cell in row.get("cells", []):
                    text = cell.get("text") if isinstance(cell, dict) else str(cell)
                    if text:
                        units.append(text)
    return units


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ground-truth", type=Path, required=True)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = ap.parse_args()

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    gt_reqs, gt_facts, gt_sources = load_gt(args.ground_truth)
    summary, canonicals, extraction = load_run(args.run_dir)

    filename_to_doc = {d["filename"]: d["document_id"] for d in summary["documents"]}
    doc_to_filename = {v: k for k, v in filename_to_doc.items()}

    # Per-document parsed text corpus.
    doc_units: dict[str, list[str]] = {
        doc_id: document_units(canonical) for doc_id, canonical in canonicals.items()
    }
    doc_norm_blob: dict[str, str] = {
        doc_id: "   ".join(normalize(u) for u in units)
        for doc_id, units in doc_units.items()
    }
    doc_token_sets: dict[str, set[str]] = {
        doc_id: set(doc_norm_blob[doc_id].split()) for doc_id in doc_units
    }
    req_labels_in_parse = {
        doc_id: sum(len(_REQ_LABEL.findall(u)) for u in units)
        for doc_id, units in doc_units.items()
    }

    extractor_reqs: list[dict] = list(extraction.get("requirements", []))

    # ---- Map extractor outputs to GT (deterministic, source-doc scoped) ----
    gt_by_id = {r["gt_id"]: r for r in gt_reqs}
    ext_to_gt: dict[str, list[tuple[str, float]]] = {}
    gt_to_ext: dict[str, list[tuple[str, float]]] = {r["gt_id"]: [] for r in gt_reqs}

    for ext in extractor_reqs:
        ext_id = ext["requirement_id"]
        source_file = Path(ext.get("source", {}).get("filename", "")).name
        ext_tok = tokens(ext.get("original_text", ""))
        scored: list[tuple[str, float]] = []
        for gt in gt_reqs:
            if gt["source_doc"] != source_file:
                continue
            gt_tok = tokens(str(gt["original_wording"] or ""))
            score = max(containment(gt_tok, ext_tok), containment(ext_tok, gt_tok))
            if score >= PARTIAL_THRESHOLD:
                scored.append((gt["gt_id"], score))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        ext_to_gt[ext_id] = scored
        for gt_id, score in scored:
            gt_to_ext[gt_id].append((ext_id, score))

    # ---- Level 1 detection per GT occurrence ----
    detection: dict[str, str] = {}
    for gt in gt_reqs:
        matches = sorted(gt_to_ext[gt["gt_id"]], key=lambda p: -p[1])
        if not matches:
            detection[gt["gt_id"]] = MISSED
        elif len(matches) > 1 and matches[0][1] - matches[1][1] < AMBIGUITY_MARGIN:
            detection[gt["gt_id"]] = AMBIGUOUS
        elif matches[0][1] >= EXACT_THRESHOLD:
            detection[gt["gt_id"]] = EXACT
        else:
            detection[gt["gt_id"]] = PARTIAL

    false_positives = [
        ext for ext in extractor_reqs if not ext_to_gt.get(ext["requirement_id"])
    ]

    # ---- Level 2 atomization for detected GT entries ----
    atomization: dict[str, str] = {}
    ext_match_counts = Counter(
        gt_id for pairs in ext_to_gt.values() for gt_id, _ in pairs[:1]
    )
    for gt in gt_reqs:
        gt_id = gt["gt_id"]
        matched_exts = [e for e, _ in gt_to_ext[gt_id]]
        if not matched_exts:
            atomization[gt_id] = MISSED
            continue
        best_ext = matched_exts[0]
        gt_ids_of_best_ext = [g for g, _ in ext_to_gt[best_ext]]
        if len(matched_exts) > 1:
            atomization[gt_id] = "OVER_SPLIT"
        elif len(gt_ids_of_best_ext) > 1:
            atomization[gt_id] = "OVER_MERGED"
        elif detection[gt_id] == EXACT:
            atomization[gt_id] = "ONE_TO_ONE"
        else:
            atomization[gt_id] = "PARTIAL_SPAN"

    # ---- Miss-reason evidence (deterministic, parse-structure based) ----
    def text_presence(gt: dict) -> str:
        doc_id = filename_to_doc.get(gt["source_doc"])
        if doc_id is None or doc_id not in doc_norm_blob:
            return NOT_FOUND_IN_PARSE
        wording = normalize(str(gt["original_wording"] or ""))
        if wording and wording in doc_norm_blob[doc_id]:
            return VERBATIM_PRESENT
        gt_tok = tokens(str(gt["original_wording"] or ""))
        if containment(gt_tok, doc_token_sets[doc_id]) >= TOKEN_PRESENCE_THRESHOLD:
            return TOKEN_MAJORITY_PRESENT
        return NOT_FOUND_IN_PARSE

    def miss_reason(gt: dict, presence: str) -> str:
        if detection[gt["gt_id"]] not in (MISSED, PARTIAL):
            return ""
        doc_id = filename_to_doc.get(gt["source_doc"])
        if doc_id is None or doc_id not in doc_units:
            return "PARSER_STRUCTURE_LOSS"
        # The extractor's only trigger is a REQ-<label> paragraph or table
        # cell; if the parse contains zero such labels in this document, the
        # miss is deterministically attributable to the missing label. Text
        # presence is reported separately as evidence, not as a reason: GT
        # wording is curated (often ellipsis-condensed), so a sub-threshold
        # containment score does NOT establish parser loss.
        if req_labels_in_parse.get(doc_id, 0) == 0:
            return "REQ_LABEL_NOT_PRESENT"
        return "UNKNOWN_OTHER"

    presence_by_gt = {gt["gt_id"]: text_presence(gt) for gt in gt_reqs}

    # ---- Fact/Sizing control set ----
    fact_false_positives = []
    for fact in gt_facts:
        fact_tok = tokens(f"{fact.get('parameter','')} {fact.get('known_value','')}")
        for ext in false_positives:
            if containment(fact_tok, tokens(ext.get("original_text", ""))) >= EXACT_THRESHOLD:
                fact_false_positives.append((fact["fact_id"], ext["requirement_id"]))

    # ---- Source-conflict entries (from GT Method_Notes, never altered).
    # Conflict 1 (criterion 2.3.1 references "LB 2.2.2" although LB 2.2.2 is
    # SIEM) is deterministically anchored at the Kriterienkatalog row with
    # section 2.3.1. Conflict 2 (criteria catalogue references the price
    # method in Ziffer 12.2 vs section 11 in the offer conditions) has no
    # verbatim "12.2" in any GT row wording; its probable carrier is the
    # Kriterienkatalog price criterion (section 3.1.1), recorded as
    # NOT_DETERMINISTICALLY_ANCHORED rather than guessed.
    conflict_anchored = [
        gt["gt_id"] for gt in gt_reqs
        if gt["source_doc"].startswith("6983748")
        and str(gt.get("section") or "").strip() == "2.3.1"
    ]
    conflict_probable = [
        gt["gt_id"] for gt in gt_reqs
        if gt["source_doc"].startswith("6983748")
        and str(gt.get("section") or "").strip() == "3.1.1"
    ]
    conflict_gt_ids = sorted(set(conflict_anchored))

    # ---- Assemble artifacts ----
    def git(*argv: str) -> str:
        return subprocess.run(
            ["git", "-C", str(args.repo), *argv],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    hard = [g for g in gt_reqs if str(g.get("hard_gate")).strip().lower() == "yes"]
    det_counts = Counter(detection.values())
    hard_det = Counter(detection[g["gt_id"]] for g in hard)
    atom_counts = Counter(atomization[g["gt_id"]] for g in gt_reqs)
    total = len(gt_reqs)

    mapping_rows = []
    for gt in gt_reqs:
        gt_id = gt["gt_id"]
        detected = detection[gt_id] in (EXACT, PARTIAL, AMBIGUOUS)
        presence = presence_by_gt[gt_id]
        mapping_rows.append({
            "gt_id": gt_id,
            "source_doc": gt["source_doc"],
            "pdf_page": gt.get("pdf_page"),
            "section": gt.get("section"),
            "requirement_class": gt.get("requirement_class"),
            "requirement_level": gt.get("requirement_level"),
            "hard_gate": gt.get("hard_gate"),
            "extractor_status": "DETECTED" if detected else "NOT_DETECTED",
            "extractor_requirement_ids": ";".join(e for e, _ in gt_to_ext[gt_id]),
            "detection_class": detection[gt_id],
            "atomization_class": atomization[gt_id],
            "modality_result": "NOT_APPLICABLE_NO_DETECTION" if not detected else "",
            "negation_result": "NOT_AVAILABLE" if not detected else "",
            "type_result": "NOT_APPLICABLE_NO_DETECTION" if not detected else "",
            "provenance_result": "MISSING" if not detected else "",
            "text_presence_in_parse": presence,
            "miss_reason": miss_reason(gt, presence),
            "mapping_confidence": "HIGH_DETERMINISTIC",
            "source_conflict": (
                "SOURCE_CONFLICT_PRESERVED" if gt_id in conflict_gt_ids else ""
            ),
        })

    with (out / "gt_mapping.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(mapping_rows[0].keys()))
        writer.writeheader()
        writer.writerows(mapping_rows)

    with (out / "miss_analysis.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["gt_id", "source_doc", "section", "hard_gate",
                         "text_presence_in_parse", "miss_reason"])
        for row in mapping_rows:
            if row["detection_class"] in (MISSED, PARTIAL):
                writer.writerow([row["gt_id"], row["source_doc"], row["section"],
                                 row["hard_gate"], row["text_presence_in_parse"],
                                 row["miss_reason"]])

    with (out / "false_positives.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["extractor_requirement_id", "source_filename",
                         "classification", "probable_reason",
                         "overlaps_fact_or_sizing"])
        fact_fp_ext_ids = {e for _, e in fact_false_positives}
        for ext in false_positives:
            ext_id = ext["requirement_id"]
            writer.writerow([
                ext_id,
                Path(ext.get("source", {}).get("filename", "")).name,
                "FACT_OR_SIZING" if ext_id in fact_fp_ext_ids else "OTHER",
                "", "yes" if ext_id in fact_fp_ext_ids else "no",
            ])

    by_source = {}
    for src in gt_sources:
        rows = [r for r in mapping_rows if r["source_doc"] == src]
        misses = [r for r in rows if r["detection_class"] == MISSED]
        by_source[src] = {
            "gt_requirements": len(rows),
            "exact": sum(r["detection_class"] == EXACT for r in rows),
            "partial": sum(r["detection_class"] == PARTIAL for r in rows),
            "missed": len(misses),
            "extractor_outputs": sum(
                Path(e.get("source", {}).get("filename", "")).name == src
                for e in extractor_reqs
            ),
            "false_positives": sum(
                Path(e.get("source", {}).get("filename", "")).name == src
                for e in false_positives
            ),
            "dominant_miss_reason": (
                Counter(r["miss_reason"] for r in misses).most_common(1)[0][0]
                if misses else None
            ),
        }

    by_level = {}
    for level in sorted({str(g.get("requirement_level")) for g in gt_reqs}):
        rows = [r for r in mapping_rows if str(gt_by_id[r["gt_id"]]["requirement_level"]) == level]
        by_level[level] = {
            "gt_total": len(rows),
            "exact": sum(r["detection_class"] == EXACT for r in rows),
            "partial": sum(r["detection_class"] == PARTIAL for r in rows),
            "missed": sum(r["detection_class"] == MISSED for r in rows),
        }

    n_exact = det_counts.get(EXACT, 0)
    n_partial = det_counts.get(PARTIAL, 0)
    baseline_summary = {
        "evaluation": "Requirement Extraction Baseline Evaluation #1",
        "frozen": True,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "eval_script_version": SCRIPT_VERSION,
        "baseline": {
            "extractor_name": extraction.get("agent_name"),
            "extractor_version": extraction.get("agent_version"),
            "git_commit": git("rev-parse", "HEAD"),
            "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "pipeline_run_id": summary["run_id"],
            "pipeline_outcome": summary["outcome"],
        },
        "inputs": {
            "ground_truth_file": args.ground_truth.name,
            "ground_truth_sha256": sha256_file(args.ground_truth),
            "source_package": "Controlled Real RFP Pilot #1 (2025_DE_RAG)",
            "source_documents": {
                d["filename"]: {"document_id": d["document_id"],
                                "parse_status": d["parse_status"]}
                for d in summary["documents"]
            },
        },
        "ground_truth_totals": {
            "requirements": total,
            "hard_gate": len(hard),
            "facts_sizing": len(gt_facts),
            "source_documents": len(gt_sources),
        },
        "extractor_output_count": len(extractor_reqs),
        "detection": {
            "exact": n_exact,
            "partial": n_partial,
            "missed": det_counts.get(MISSED, 0),
            "ambiguous": det_counts.get(AMBIGUOUS, 0),
            "false_positives": len(false_positives),
            "strict_recall": round(n_exact / total, 4),
            "inclusive_recall": round((n_exact + n_partial) / total, 4),
            "miss_rate": round(det_counts.get(MISSED, 0) / total, 4),
        },
        "hard_gate": {
            "gt_total": len(hard),
            "exact": hard_det.get(EXACT, 0),
            "partial": hard_det.get(PARTIAL, 0),
            "missed": hard_det.get(MISSED, 0),
            "strict_recall": round(hard_det.get(EXACT, 0) / len(hard), 4),
            "inclusive_recall": round(
                (hard_det.get(EXACT, 0) + hard_det.get(PARTIAL, 0)) / len(hard), 4
            ),
        },
        "facts_sizing_control": {
            "gt_total": len(gt_facts),
            "fact_false_positives": len(fact_false_positives),
        },
        "atomization": {k: atom_counts.get(k, 0) for k in
                        ["ONE_TO_ONE", "OVER_MERGED", "OVER_SPLIT",
                         "PARTIAL_SPAN", "DUPLICATE_EXTRACTION", "MISSED"]},
        "semantics_note": (
            "No GT requirement was detected; every semantic dimension "
            "(modality, negation, type, provenance) is NOT_APPLICABLE with "
            "zero detected requirements. Negation/exclusion is additionally "
            "NOT_AVAILABLE in the extractor contract (no such field)."
            if not extractor_reqs else "see gt_mapping.csv"
        ),
        "req_labels_found_in_parsed_documents": req_labels_in_parse,
        "text_presence_in_parse": dict(Counter(presence_by_gt.values())),
        "miss_reasons": dict(Counter(
            r["miss_reason"] for r in mapping_rows if r["miss_reason"]
        )),
        "by_source_document": by_source,
        "by_requirement_level": by_level,
        "source_conflicts": {
            "policy": "SOURCE_CONFLICT_PRESERVED",
            "conflict_1_criterion_2_3_1_vs_lb_2_2_2": {
                "anchored_gt_ids": conflict_anchored,
                "extractor_handling": {
                    gt_id: ("DROPPED_NOT_DETECTED"
                            if detection[gt_id] == MISSED else detection[gt_id])
                    for gt_id in conflict_anchored
                },
            },
            "conflict_2_price_method_ziffer_12_2_vs_section_11": {
                "anchoring": "NOT_DETERMINISTICALLY_ANCHORED",
                "probable_carrier_gt_ids": conflict_probable,
                "extractor_handling": {
                    gt_id: ("DROPPED_NOT_DETECTED"
                            if detection[gt_id] == MISSED else detection[gt_id])
                    for gt_id in conflict_probable
                },
            },
        },
    }

    (out / "baseline_summary.json").write_text(
        json.dumps(baseline_summary, indent=2, ensure_ascii=False) + "\n"
    )

    # Metadata-only console output (no requirement text).
    print(json.dumps({
        k: baseline_summary[k] for k in
        ["baseline", "ground_truth_totals", "extractor_output_count",
         "detection", "hard_gate", "facts_sizing_control", "atomization",
         "req_labels_found_in_parsed_documents", "text_presence_in_parse",
         "miss_reasons", "by_source_document", "by_requirement_level",
         "source_conflicts"]
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
