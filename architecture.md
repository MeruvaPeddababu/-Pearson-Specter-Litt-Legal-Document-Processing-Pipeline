# Architecture Overview

## System Diagram

```
                    ┌─────────────────────────────────────┐
                    │         Input Documents              │
                    │  .pdf  |  .txt  |  .png/.jpg (scan) │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │   Stage 1: Document Processor        │
                    │   src/processor.py                   │
                    │                                      │
                    │  ┌─────────────────────────────┐    │
                    │  │  pdfplumber (native PDF)     │    │
                    │  │  → if sparse: pytesseract    │    │
                    │  │    (OCR via pdf2image)        │    │
                    │  │  plain .txt → direct read    │    │
                    │  └──────────┬──────────────────┘    │
                    │             │ raw_text               │
                    │  ┌──────────▼──────────────────┐    │
                    │  │  _clean_text()               │    │
                    │  │  _chunk_text()  (800 chars,  │    │
                    │  │                 150 overlap) │    │
                    │  └──────────┬──────────────────┘    │
                    │             │ chunks[]               │
                    │  ┌──────────▼──────────────────┐    │
                    │  │  Claude: structured field    │    │
                    │  │  extraction (JSON output)    │    │
                    │  └──────────┬──────────────────┘    │
                    │             │ ProcessedDocument      │
                    └─────────────┼───────────────────────┘
                                  │
               ┌──────────────────▼──────────────────────────┐
               │   Stage 2: Retrieval Layer                   │
               │   src/retriever.py                           │
               │                                              │
               │  ChromaDB (persistent local vector store)   │
               │  Embeddings: all-MiniLM-L6-v2 (384-dim)     │
               │  Similarity: cosine                          │
               │  Chunks upserted with doc_id + chunk_index  │
               │                                              │
               │  query(text, doc_id, top_k=5)               │
               │    → RetrievedChunk[] with chunk_id + score │
               └──────────────────┬──────────────────────────┘
                                  │ retrieved evidence
               ┌──────────────────▼──────────────────────────┐
               │   Stage 3: Draft Generator                   │
               │   src/drafter.py                             │
               │                                              │
               │  Claude (claude-sonnet-4-6)                  │
               │  System prompt: strict grounding rules +     │
               │                 learned operator patterns    │
               │  Output: Case Fact Summary JSON with         │
               │          evidence_id citations per fact      │
               └──────────────────┬──────────────────────────┘
                                  │ DraftOutput
               ┌──────────────────▼──────────────────────────┐
               │   Stage 4: Edit Capture + Pattern Learning   │
               │   src/editor.py                              │
               │                                              │
               │  Operator submits (original, edited) pair   │
               │  Claude extracts transferable style rules    │
               │  Patterns stored in SQLite (edits.db)        │
               │  Active patterns injected into Stage 3       │
               │  on all subsequent drafts                    │
               └─────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Chunking Strategy
Paragraph-aware chunking with 150-character tail overlap. Paragraph boundaries
are respected first; sentence splitting is a fallback for very long paragraphs.
This preserves logical units (numbered clauses, fact paragraphs) as single chunks.

### 2. Two-tier Retrieval Query
The draft query is deliberately broad:
`"parties plaintiff defendant case facts dates legal issues claims jurisdiction"`
This ensures diverse evidence coverage rather than retrieving only the most
semantically similar chunk. Future enhancement: multi-query fusion (HyRAG).

### 3. Grounding Enforcement
The system prompt contains hard rules: *every fact must cite a chunk ID*.
Claude returns a structured JSON schema where `evidence_id` is mandatory for
each fact, date, and party. The evaluator can mechanically verify that every
cited ID exists in the retrieved set.

### 4. Pattern Learning Loop
Rather than storing diffs, the system asks Claude to identify *transferable*
style rules. A rule like "Format all dates as ISO 8601" improves all future
drafts, not just the one that was edited. Patterns are deduplicated by
`description` and given an `times_observed` counter — frequently reinforced
patterns rank highest.

### 5. Graceful OCR Degradation
OCR is an optional dependency. If `pytesseract`/`pdf2image` are absent, the
system logs a note in `processing_notes` and continues with native PDF
extraction. For documents where native extraction produces < 200 chars, it
attempts OCR and uses whichever yields more content.

## Data Storage

| Store | Contents |
|-------|----------|
| `chroma_db/` | ChromaDB vector index (persistent across runs) |
| `edits.db` | SQLite: edit records + learned patterns |

## Scalability Notes

- ChromaDB can be swapped for a hosted vector DB (Pinecone, Weaviate) by
  changing the `DocumentRetriever` constructor.
- The SQLite pattern store works for prototypes; a production deployment would
  move to PostgreSQL.
- The pipeline is stateless between requests at the API layer — `_docs` cache
  in `LegalDocumentPipeline` is per-process. A production system would
  reload processed documents from a document store on demand.
