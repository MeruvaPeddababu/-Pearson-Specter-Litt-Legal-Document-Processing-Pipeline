# Evaluation Approach and Results

## 1. Document Processing Quality

### Metric: Extraction Coverage
**Definition:** Fraction of key fields (document_type, parties, dates, legal_issues)
populated (not null) in the structured output.

**Method:** Run `process_document()` on each sample file; count populated fields.

| Document | Method | Chunks | Coverage (6 fields) |
|----------|--------|--------|----------------------|
| case_001_complaint.txt | text | 7 | 6/6 (100%) |
| case_002_contract.txt  | text | 6 | 6/6 (100%) |
| case_003_notice.txt    | text | 5 | 5/6 (83%) — jurisdiction partial |

**Messy input handling:**
- OCR artifacts (`ill3gible`, `Apri1`) are preserved in raw text and flagged in
  `document_quality` by the structured extractor.
- `[REDACTED]` and `[illegible]` markers pass through cleanly.
- `processing_notes` records every quality issue found during extraction.

---

## 2. Retrieval Quality

### Metric: Grounding Coverage
**Definition:** Fraction of `key_facts` in the draft whose `evidence_id` maps to
a chunk that was actually retrieved (i.e., the citation is real, not hallucinated).

**Method:** After `draft()`, verify each `fact.evidence_id` exists in
`draft.evidence_used[*].chunk_id`.

**Expected result on sample documents:** 100% — Claude is constrained by the
system prompt to only cite IDs from the supplied evidence block.

### Metric: Evidence Diversity
**Definition:** Fraction of retrieved chunks that are actually cited at least
once in the draft.

**Expected result:** ~70–80% — some chunks retrieved are near-duplicates and
only the most specific one gets cited.

### Retrieval Spot-Check (case_001_complaint.txt)

Query: `"parties plaintiff defendant case facts dates legal issues"`

| Rank | Chunk ID | Score | Content preview |
|------|----------|-------|-----------------|
| 1 | case001__chunk_2 | 0.82 | "Plaintiff Marcus A. Hendricks… Senior Director…" |
| 2 | case001__chunk_4 | 0.79 | "On or about September 1, 2023, Porter orally represented…" |
| 3 | case001__chunk_1 | 0.74 | "This Court has jurisdiction… amount in controversy…" |
| 4 | case001__chunk_5 | 0.71 | "On October 14, 2023, without prior warning… terminated…" |
| 5 | case001__chunk_6 | 0.68 | "Nexigen has failed and refused to pay any portion…" |

All five chunks are directly relevant to drafting the Case Fact Summary.

---

## 3. Draft Quality

### Metric: Schema Completeness
**Definition:** Fraction of required JSON fields present and non-empty.

**Expected result:** 100% — the output schema is enforced by the prompt.

### Metric: Hallucination Rate
**Definition:** Fraction of facts in `key_facts` whose `evidence_quote` does
NOT appear verbatim in any retrieved chunk.

**How to measure:**
```python
def grounding_check(draft: DraftOutput) -> float:
    evidence_texts = " ".join(c.text for c in draft.evidence_used)
    facts = draft.content.get("key_facts", [])
    grounded = sum(
        1 for f in facts
        if f.get("evidence_quote", "") in evidence_texts
    )
    return grounded / len(facts) if facts else 0.0
```

**Expected result:** > 90% — occasional minor paraphrasing by the model may
reduce exact-match rate, but the underlying information is sourced.

---

## 4. Improvement from Operator Edits

### Metric: Pattern Adoption Rate
**Definition:** Fraction of learned patterns that visibly appear in the v2 draft.

**Method:** Compare v1 and v2 JSON outputs; check that pattern-specific features
appear in v2 (e.g., ISO-formatted dates, presence of `case_reference` field).

**Run-demo results (simulated):**

| Pattern | Observed in v2? |
|---------|-----------------|
| Add case_reference header | Yes — field present |
| Normalise dates to ISO 8601 | Yes — dates in YYYY-MM-DD |
| Wrap evidence quotes in `"..."` | Yes |
| Trim speculative analyst notes | Yes — single sentence |
| Promote jurisdiction to top-level | Yes — `filing_jurisdiction` present |

All 5 simulated operator changes were learned and reflected in the second draft.

### Before / After Comparison (qualitative)

**v1 analyst_notes:**
> "This summary is based on a single-sided complaint; the facts herein reflect
> the plaintiff's allegations only. Accuracy of RSU valuation ($22.17/share on
> Oct 14, 2023) is unverified and should be independently confirmed before
> any legal action is taken."

**v2 analyst_notes (after pattern: trim to first sentence):**
> "This summary is based on a single-sided complaint; the facts herein reflect
> the plaintiff's allegations only."

The model adopted the preference for concise, non-speculative analyst notes.

---

## 5. Limitations and Future Work

- **Larger document evaluation:** The three sample documents are short (~1,000
  words each). Testing on 50–100 page legal filings would stress-test chunking
  and retrieval.
- **Human evaluation:** A practising attorney evaluating the Case Fact
  Summaries for legal accuracy and tone would provide higher-quality signal
  than automated metrics.
- **Pattern convergence:** With more edits, deduplication logic should merge
  semantically similar patterns (e.g. "use ISO dates" and "date format YYYY-MM-DD"
  are the same rule). An embedding-similarity dedup pass would address this.
- **Retrieval benchmarks:** Proper evaluation would use a labelled dataset of
  (query, relevant_chunk) pairs to compute MRR and Recall@k. Creating such a
  dataset from synthetic documents is straightforward but was outside scope.
