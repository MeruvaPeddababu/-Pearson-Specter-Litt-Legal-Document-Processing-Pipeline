#!/usr/bin/env python3
"""
Full end-to-end demo for Pearson Specter Litt Legal Document Pipeline.

Demonstrates all four stages:
  1. Document ingestion (OCR / text extraction + structured field extraction)
  2. Grounded retrieval (ChromaDB vector search with evidence IDs)
  3. Case Fact Summary generation (grounded, with citations)
  4. Operator edit capture → pattern learning → improved second draft
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.pipeline import LegalDocumentPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

SAMPLE_DOCS = [
    ("sample_documents/case_001_complaint.txt", "case001"),
    ("sample_documents/case_002_contract.txt", "case002"),
    ("sample_documents/case_003_notice.txt", "case003"),
]


def section(title: str) -> None:
    print(f"\n{'='*64}")
    print(f"  {title}")
    print(f"{'='*64}\n")


def main() -> None:
    section("Pearson Specter Litt — Legal Document Processing System")

    pipeline = LegalDocumentPipeline()

    # ── Stage 1: Ingest ───────────────────────────────────────────
    section("STAGE 1 · Document Ingestion")

    ingested = []
    for path, doc_id in SAMPLE_DOCS:
        if not Path(path).exists():
            print(f"  [SKIP] {path} — file not found")
            continue
        doc = pipeline.ingest(path, doc_id=doc_id)
        ingested.append(doc)
        print(f"  [OK] {doc.doc_id}")
        print(f"       method : {doc.extraction_method}")
        print(f"       chunks : {len(doc.chunks)}")
        print(f"       type   : {doc.structured_fields.get('document_type', 'unknown')}")
        print(f"       notes  : {doc.processing_notes[:2]}")
        print()

    if not ingested:
        print("No documents ingested — exiting.")
        return

    primary = ingested[0]

    # ── Stages 2 + 3: First draft ─────────────────────────────────
    section("STAGES 2+3 · Grounded Draft Generation (First Pass)")

    print(f"Generating Case Fact Summary for document: {primary.doc_id}\n")
    draft_v1 = pipeline.draft(primary.doc_id)

    print("DRAFT (v1):")
    print(json.dumps(draft_v1.content, indent=2))

    print(f"\nApplied patterns : {draft_v1.applied_patterns or ['(none — first run)']}")
    print(f"Evidence chunks  : {len(draft_v1.evidence_used)}")
    print("\nEvidence used (top 3):")
    for c in draft_v1.evidence_used[:3]:
        print(f"  [{c.chunk_id}] score={c.score:.3f}  {c.text[:110]}…")

    Path("sample_outputs").mkdir(exist_ok=True)
    v1_path = f"sample_outputs/{primary.doc_id}_draft_v1.json"
    with open(v1_path, "w") as f:
        json.dump(
            {
                "draft": draft_v1.content,
                "applied_patterns": draft_v1.applied_patterns,
                "evidence": [
                    {"chunk_id": c.chunk_id, "score": c.score, "text": c.text[:300]}
                    for c in draft_v1.evidence_used
                ],
            },
            f,
            indent=2,
        )
    print(f"\nSaved → {v1_path}")

    # ── Stage 4: Simulate operator edits ─────────────────────────
    section("STAGE 4 · Operator Edit Capture & Pattern Learning")

    # Build a realistic edited version
    edited = json.loads(json.dumps(draft_v1.content))  # deep copy

    # Operator edit 1: add firm-standard header reference
    edited["case_reference"] = (
        f"{edited.get('case_title', 'MATTER')} | "
        f"No. {edited.get('case_number') or 'UNKNOWN'} | "
        f"{edited.get('jurisdiction') or 'Jurisdiction TBD'}"
    )

    # Operator edit 2: ISO-format all dates
    for entry in edited.get("relevant_dates", []):
        raw_date = entry.get("date", "")
        if raw_date and "/" in raw_date:
            parts = raw_date.split("/")
            if len(parts) == 3:
                entry["date"] = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"

    # Operator edit 3: wrap evidence quotes in proper quotation marks
    for fact in edited.get("key_facts", []):
        q = fact.get("evidence_quote", "")
        if q and not q.startswith('"'):
            fact["evidence_quote"] = f'"{q}"'

    # Operator edit 4: trim speculative analyst notes
    if "analyst_notes" in edited:
        note = edited["analyst_notes"]
        edited["analyst_notes"] = note.split(".")[0].strip() + "." if "." in note else note

    # Operator edit 5: add jurisdiction to top
    if "jurisdiction" in edited and edited["jurisdiction"]:
        edited["filing_jurisdiction"] = edited["jurisdiction"]

    print("Operator edits applied:")
    print("  1. Added firm-standard case reference header (case_reference field)")
    print("  2. Normalised dates to ISO format (YYYY-MM-DD)")
    print("  3. Wrapped evidence quotes in typographic quotation marks")
    print("  4. Trimmed speculative analyst notes to first sentence")
    print("  5. Promoted jurisdiction to top-level filing_jurisdiction field")

    record = pipeline.submit_edit(primary.doc_id, draft_v1.content, edited)
    print(f"\nEdit saved: {record.edit_id}")

    patterns = pipeline.get_patterns()
    print(f"\nLearned {len(patterns)} active pattern(s):")
    for p in patterns:
        print(f"  [{p.pattern_id}] (×{p.times_observed}) {p.description}")
        print(f"    Rule: {p.rule}")

    edit_record_path = f"sample_outputs/{primary.doc_id}_edit_record.json"
    with open(edit_record_path, "w") as f:
        json.dump(
            {
                "edit_id": record.edit_id,
                "doc_id": record.doc_id,
                "timestamp": record.timestamp,
                "operator_edits_applied": [
                    "Added firm-standard case_reference header field",
                    "Normalised dates to ISO format (YYYY-MM-DD)",
                    "Wrapped evidence_quote values in typographic quotation marks",
                    "Trimmed speculative analyst_notes to first sentence only",
                    "Promoted jurisdiction to top-level filing_jurisdiction field",
                ],
                "patterns_extracted": json.loads(record.extracted_pattern) if record.extracted_pattern else [],
                "total_active_patterns": len(patterns),
                "active_patterns": [
                    {
                        "pattern_id": p.pattern_id,
                        "description": p.description,
                        "rule": p.rule,
                        "example_before": p.example_before,
                        "example_after": p.example_after,
                        "times_observed": p.times_observed,
                    }
                    for p in patterns
                ],
            },
            f,
            indent=2,
        )
    print(f"\nSaved → {edit_record_path}")

    # ── Stages 2 + 3 again: Improved draft ───────────────────────
    section("STAGES 2+3 · Draft Generation (With Learned Patterns)")

    draft_v2 = pipeline.draft(primary.doc_id)
    print("DRAFT (v2 — with learned patterns):")
    print(json.dumps(draft_v2.content, indent=2))
    print(f"\nPatterns applied: {draft_v2.applied_patterns}")

    v2_path = f"sample_outputs/{primary.doc_id}_draft_v2.json"
    with open(v2_path, "w") as f:
        json.dump(
            {
                "draft": draft_v2.content,
                "applied_patterns": draft_v2.applied_patterns,
                "evidence": [
                    {"chunk_id": c.chunk_id, "score": c.score, "text": c.text[:300]}
                    for c in draft_v2.evidence_used
                ],
            },
            f,
            indent=2,
        )
    print(f"\nSaved → {v2_path}")

    # ── Summary ───────────────────────────────────────────────────
    section("Demo Complete")
    print("Pipeline stages demonstrated:")
    print("  [1] Document Processing  — extraction method:", primary.extraction_method)
    print("  [2] Grounded Retrieval   — ChromaDB cosine similarity with chunk IDs")
    print("  [3] Draft Generation     — Case Fact Summary with evidence citations")
    print("  [4] Edit + Learning      — Operator patterns extracted and stored")
    print(f"\nOutput files:")
    print(f"  {v1_path}  (first draft, no patterns)")
    print(f"  {v2_path}  (second draft, with {len(patterns)} learned pattern(s))")


if __name__ == "__main__":
    main()
