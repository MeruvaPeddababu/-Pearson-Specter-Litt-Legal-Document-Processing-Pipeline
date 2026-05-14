# Assumptions and Tradeoffs

## Draft Type Choice: Case Fact Summary

I chose the **Case Fact Summary** as the output type because:
- It requires synthesising parties, facts, dates, and legal issues — forcing the
  model to demonstrate broad document understanding, not just extraction.
- Every field has a natural "evidence required" property, making grounding
  violations easy to detect.
- It maps directly to what a junior associate would prepare before a partner
  meeting, which is a realistic internal workflow.

## Assumptions

### Document Processing
- Input documents are predominantly English-language.
- OCR quality is "good enough" once pytesseract has been applied at 300 DPI;
  a secondary correction pass (e.g. using an LLM to fix OCR artifacts) is not
  implemented but noted as a future enhancement.
- Partially illegible sections are preserved as-is in the extracted text
  (e.g. `[illegible]` markers). The structured-field extraction prompt
  acknowledges this via the `document_quality` field.

### Retrieval
- Five retrieved chunks per draft is sufficient for the sample documents
  (each ~1,500–2,500 words). For longer documents (50+ pages), `TOP_K_RETRIEVAL`
  should be increased to 10–15.
- `all-MiniLM-L6-v2` (384-dimensional, ~80 MB) provides good retrieval quality
  for legal text at low latency. For higher accuracy, `legal-bert-base-uncased`
  or `multi-qa-mpnet-base-dot-v1` would be better choices but are larger.

### Operator Edit Simulation
- In `run_demo.py` I simulate five realistic edits that reflect common attorney
  preferences (ISO dates, case reference headers, tighter analyst notes). In a
  production system, the operator would use a UI diff editor.
- Pattern extraction confidence threshold is 0.7. Lower-confidence patterns
  are discarded rather than accumulated, to avoid polluting the prompt with
  noise.

### Improvement Loop
- The improvement loop works at the **prompt level**: extracted patterns become
  additional instructions in the system prompt. This is the simplest approach
  that avoids fine-tuning while still producing measurable draft improvements.
- Patterns are global (shared across all documents). A more sophisticated
  implementation would tag patterns by document type (contract vs. complaint)
  and apply them selectively.

## Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|----------|----------------|-------------|-----|
| Vector DB | ChromaDB (local) | Pinecone, Weaviate | Zero-infra for assessment; easy swap |
| Embeddings | sentence-transformers CPU | OpenAI text-embedding-3-small | No extra API key; works offline |
| Pattern storage | SQLite | PostgreSQL | Simplicity; single-file deployment |
| OCR | pytesseract | AWS Textract, Azure OCR | Open-source; no cloud dependency |
| Draft format | JSON schema | Free-form prose | Machine-readable; grounding is verifiable |
| LLM calls | Claude for both extraction and drafting | Separate specialised models | Single API, consistent quality |

## Known Limitations

1. **No cross-document retrieval in draft**: Each draft is anchored to a single
   `doc_id`. Cross-document synthesis (e.g. comparing two contracts) is not
   implemented.
2. **Pattern deduplication is naive**: Two patterns with slightly different
   `description` strings are stored separately even if semantically identical.
3. **No re-ranking**: Retrieved chunks are ranked by cosine similarity only.
   BM25 hybrid re-ranking would improve precision on keyword-heavy legal queries.
4. **No streaming**: The API returns complete JSON responses. Streaming would
   improve perceived latency for long drafts.
