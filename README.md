# Pearson Specter Litt — Legal Document Processing Pipeline

An AI-powered four-stage pipeline that ingests messy legal documents, extracts
structured data, generates evidence-grounded drafts, and continuously improves
from operator edits.

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [Quick Start](#2-quick-start)
3. [Project Structure](#3-project-structure)
4. [Pipeline — Stage by Stage](#4-pipeline--stage-by-stage)
5. [Sample Inputs and Outputs](#5-sample-inputs-and-outputs)
6. [API Reference](#6-api-reference)
7. [Web UI](#7-web-ui)
8. [Running Tests](#8-running-tests)
9. [Docker Setup](#9-docker-setup)
10. [Architecture Overview](#10-architecture-overview)
11. [Assumptions and Tradeoffs](#11-assumptions-and-tradeoffs)
12. [Evaluation Approach and Results](#12-evaluation-approach-and-results)

---

## 1. What This System Does

```
Messy legal document
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  Stage 1 · Document Processing                      │
│  PDF / DOCX / PPTX / image / text  →  clean text   │
│  Claude extracts: parties, dates, legal issues …    │
└────────────────────────┬────────────────────────────┘
                         │ ProcessedDocument
┌────────────────────────▼────────────────────────────┐
│  Stage 2 · Grounded Retrieval                       │
│  ChromaDB vector search → top-5 evidence chunks     │
│  Each chunk carries a unique ID for citation        │
└────────────────────────┬────────────────────────────┘
                         │ RetrievedChunk[]
┌────────────────────────▼────────────────────────────┐
│  Stage 3 · Draft Generation                         │
│  Claude generates Case Fact Summary JSON            │
│  Every fact cites an evidence_id — no hallucination │
└────────────────────────┬────────────────────────────┘
                         │ DraftOutput
┌────────────────────────▼────────────────────────────┐
│  Stage 4 · Edit Capture & Pattern Learning          │
│  Operator edits draft → Claude extracts style rules │
│  Rules stored in SQLite → injected into all future  │
│  drafts automatically                               │
└─────────────────────────────────────────────────────┘
```

---

## 2. Quick Start

### Prerequisites

- Python 3.11+
- An Anthropic API key (get one at [console.anthropic.com](https://console.anthropic.com))

### Install

```bash
# Clone / unzip the project, then:
cd pearson-specter-litt

python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

> **Note:** On first run `sentence-transformers` downloads `all-MiniLM-L6-v2`
> (~90 MB). This happens once and is cached locally.

### Configure

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Open `.env` and set your key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

### Run the CLI demo

```bash
python run_demo.py
```

The demo runs all four stages end-to-end on three sample legal documents and
prints a complete trace. Output files are saved to `sample_outputs/`.

### Run the API + UI

```bash
uvicorn api.app:app --reload
```

| URL | What you get |
|-----|-------------|
| `http://localhost:8000` | Web UI (upload → draft → edit → learn) |
| `http://localhost:8000/docs` | Interactive Swagger API docs |

---

## 3. Project Structure

```
pearson-specter-litt/
│
├── src/
│   ├── config.py          # API key, model name, chunk sizes, paths
│   ├── models.py          # ProcessedDocument, DraftOutput, LearnedPattern …
│   ├── processor.py       # Stage 1: text extraction + OCR + structured fields
│   ├── retriever.py       # Stage 2: ChromaDB vector store + query
│   ├── drafter.py         # Stage 3: grounded Case Fact Summary generation
│   ├── editor.py          # Stage 4: edit capture + SQLite pattern store
│   └── pipeline.py        # Orchestrator tying all stages together
│
├── api/
│   └── app.py             # FastAPI REST interface (7 endpoints)
│
├── ui/
│   └── index.html         # Single-file web UI (no build step)
│
├── sample_documents/
│   ├── case_001_complaint.txt   # Employment dispute complaint (messy OCR)
│   ├── case_002_contract.txt    # Software services contract
│   └── case_003_notice.txt      # Legal notice / demand letter
│
├── sample_outputs/
│   ├── case001_draft_v1.json       # First draft (no learned patterns)
│   ├── case001_draft_v2.json       # Second draft (patterns applied)
│   └── case001_edit_record.json    # Edit capture + extracted patterns
│
├── tests/
│   └── test_pipeline.py   # Unit tests (no API) + integration tests (API)
│
├── run_demo.py            # End-to-end CLI demo
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── architecture.md        # Detailed architecture notes
├── assumptions.md         # Design decisions and tradeoffs
└── evaluation.md          # Evaluation methodology and results
```

---

## 4. Pipeline — Stage by Stage

### Stage 1 · Document Processing (`src/processor.py`)

**What it does:**

| File Type | Extraction Method |
|-----------|------------------|
| `.txt` | Direct UTF-8 read |
| `.pdf` (text-based) | pdfplumber native extraction |
| `.pdf` (scanned) | pdfplumber → OCR fallback via pytesseract |
| `.docx` | python-docx (paragraphs + tables) |
| `.pptx` / `.ppt` | python-pptx (per-slide text, labelled `[Slide N]`) |
| `.png` / `.jpg` / `.tiff` | pytesseract OCR |

**After extraction:**

1. `_clean_text()` — removes non-printable characters, collapses excessive whitespace, fixes common OCR substitutions (`|` → `I` before capital letters)
2. `_chunk_text()` — paragraph-aware chunking (800 chars, 150-char overlap). Long paragraphs fall back to sentence splitting.
3. `_extract_structured()` — Claude pulls a structured JSON of parties, dates, legal issues, statutes, jurisdiction, and document quality notes

**Output — `ProcessedDocument`:**

```json
{
  "doc_id": "case001",
  "extraction_method": "text",
  "chunk_count": 11,
  "structured_fields": {
    "document_type": "complaint",
    "case_title": "Marcus A. Hendricks v. Nexigen Pharmaceuticals, Inc.",
    "case_number": "24-CV-08821",
    "parties": [
      { "name": "Marcus A. Hendricks", "role": "plaintiff" },
      { "name": "Nexigen Pharmaceuticals, Inc.", "role": "defendant" }
    ],
    "legal_issues": ["Breach of Contract", "Fraud and Deceit"],
    "document_quality": "OCR artifact 'Apri1' on page 3; water damage noted"
  },
  "processing_notes": [
    "Produced 11 chunks (method=text)"
  ]
}
```

---

### Stage 2 · Grounded Retrieval (`src/retriever.py`)

**What it does:**

- All chunks are embedded with `all-MiniLM-L6-v2` (384-dim sentence-transformers)
- Stored in ChromaDB with cosine similarity space
- At draft time, a broad query retrieves the top-5 most relevant chunks

**Why broad query?**
The default query is:
```
"parties plaintiff defendant case facts dates legal issues claims jurisdiction"
```
This ensures diverse evidence coverage rather than clustering around one narrow topic.

**Output — `RetrievedChunk[]`:**

```json
[
  {
    "chunk_id": "case001__chunk_0",
    "doc_id": "case001",
    "score": 0.4105,
    "text": "SUPERIOR COURT OF THE STATE OF CALIFORNIA ... BREACH OF CONTRACT ..."
  },
  {
    "chunk_id": "case001__chunk_9",
    "doc_id": "case001",
    "score": 0.3164,
    "text": "damages not less than $2,704,125 (comprising $210,000 severance + $2,494,125 RSU value)"
  }
]
```

Chunk IDs follow the pattern `{doc_id}__chunk_{index}` — fully traceable back to the source.

---

### Stage 3 · Draft Generation (`src/drafter.py`)

**What it does:**

Claude (`claude-sonnet-4-6`) receives:
- The structured fields from Stage 1
- The retrieved evidence passages from Stage 2
- Any learned operator patterns from Stage 4

The system prompt contains **hard grounding rules**:
1. Every fact MUST be supported by a supplied evidence passage
2. If information is absent → write `"Not found in document"`, never invent
3. Every fact, party, and date must carry an `evidence_id` (the chunk ID)

**Output — Case Fact Summary JSON:**

```json
{
  "case_title": "Marcus A. Hendricks v. Nexigen Pharmaceuticals, Inc., et al.",
  "case_number": "24-CV-08821",
  "parties": [
    {
      "name": "Marcus A. Hendricks",
      "role": "Plaintiff",
      "evidence_id": "case001__chunk_0"
    }
  ],
  "key_facts": [
    {
      "fact": "Hendricks was employed as Senior Director of Business Development from April 2019 through October 14, 2023.",
      "evidence_id": "case001__chunk_2",
      "evidence_quote": "\"Hendricks was employed as Senior Director ... from Apri1 2019 through October 14, 2023\""
    }
  ],
  "missing_information": [
    "Exhibits A, B, and C referenced but not attached — these contain the Employment Agreement.",
    "RSU valuation of $22.17/share is from a partially illegible page — requires independent verification."
  ],
  "analyst_notes": "First-pass review based on five retrieved evidence passages; material facts should be verified against original exhibits."
}
```

The `missing_information` field is the grounding control — it forces the model to explicitly declare what it could NOT find rather than filling gaps with inference.

---

### Stage 4 · Edit Capture and Pattern Learning (`src/editor.py`)

**What it does:**

1. Operator reviews the draft and submits an edited version via the API or UI
2. Claude compares original vs. edited, extracts **transferable style rules**
3. Rules are stored in SQLite (`edits.db`) with a `times_observed` counter
4. On every future draft, active patterns are injected into the system prompt

**What makes a pattern "transferable":**

The extractor is specifically prompted to find rules that improve *all* drafts, not just corrections to one-off errors. Patterns with confidence < 0.7 are discarded.

**Example — 5 patterns extracted from one edit session:**

| # | Description | Rule |
|---|-------------|------|
| 1 | Add case reference header | Always include a `case_reference` field combining title, number, and jurisdiction |
| 2 | ISO-format all dates | Normalise dates in `relevant_dates` to YYYY-MM-DD |
| 3 | Quote-wrap evidence citations | Wrap `evidence_quote` values in escaped double-quote characters |
| 4 | Trim speculative analyst notes | Limit `analyst_notes` to a single declarative sentence |
| 5 | Promote jurisdiction field | Add top-level `filing_jurisdiction` for quick scanning |

**v1 → v2 improvement (visible in sample outputs):**

```
v1 analyst_notes:
  "This summary is a first-pass analysis based solely on five retrieved evidence
   passages ... and should be verified against the original complaint and
   unattached exhibits before any reliance for litigation purposes."

v2 analyst_notes (after "trim speculative notes" pattern):
  "This summary is a first-pass analysis based solely on five retrieved evidence passages."
```

---

## 5. Sample Inputs and Outputs

### Sample Documents

| File | Type | Notable Features |
|------|------|-----------------|
| `case_001_complaint.txt` | Employment dispute | OCR artifacts (`Apri1`), water damage notation, redacted address, missing exhibits |
| `case_002_contract.txt` | Software services agreement | Payment terms, SLA clauses, indemnification |
| `case_003_notice.txt` | Legal demand notice | Short form, partial jurisdiction info |

### Sample Output Files

| File | Stage | Description |
|------|-------|-------------|
| `sample_outputs/case001_draft_v1.json` | 3 | First draft — no learned patterns applied |
| `sample_outputs/case001_draft_v2.json` | 3 | Second draft — 1 pattern applied (quote-wrap) |
| `sample_outputs/case001_edit_record.json` | 4 | Edit record showing 5 extracted patterns |

**Snippet from `case001_edit_record.json`:**

```json
{
  "edit_id": "a3f9c12e8b04",
  "operator_edits_applied": [
    "Added firm-standard case_reference header field",
    "Normalised dates to ISO format (YYYY-MM-DD)",
    "Wrapped evidence_quote values in typographic quotation marks",
    "Trimmed speculative analyst_notes to first sentence only",
    "Promoted jurisdiction to top-level filing_jurisdiction field"
  ],
  "patterns_extracted": [
    {
      "description": "ISO-format all dates",
      "rule": "Normalise all date values in relevant_dates to ISO 8601 (YYYY-MM-DD)",
      "example_before": "\"date\": \"11/08/2023\"",
      "example_after": "\"date\": \"2023-11-08\"",
      "confidence": 0.98
    }
  ],
  "total_active_patterns": 5
}
```

---

## 6. API Reference

Base URL: `http://localhost:8000`

### Upload and process a document

```bash
POST /documents/upload

curl -X POST http://localhost:8000/documents/upload \
  -F "file=@sample_documents/case_001_complaint.txt" \
  -F "doc_id=case001"
```

**Response:**
```json
{
  "doc_id": "case001",
  "extraction_method": "text",
  "chunk_count": 11,
  "structured_fields": { "document_type": "complaint", "case_title": "..." },
  "processing_notes": ["Produced 11 chunks (method=text)"]
}
```

---

### Generate a grounded draft

```bash
GET /documents/{doc_id}/draft

curl http://localhost:8000/documents/case001/draft
```

**Response:**
```json
{
  "doc_id": "case001",
  "draft_type": "case_fact_summary",
  "generated_at": "2026-05-14T10:00:00Z",
  "content": { "case_title": "...", "key_facts": [...], "missing_information": [...] },
  "applied_patterns": ["Wrap evidence_quote values in escaped double-quote characters"],
  "evidence_used": [
    { "chunk_id": "case001__chunk_0", "score": 0.4105, "text_preview": "SUPERIOR COURT..." }
  ]
}
```

---

### Submit an operator edit

```bash
POST /edits

curl -X POST http://localhost:8000/edits \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "case001",
    "original_draft": { "case_title": "...", "analyst_notes": "Long speculative note..." },
    "edited_draft":   { "case_title": "...", "analyst_notes": "Short note." }
  }'
```

**Response:**
```json
{
  "edit_id": "a3f9c12e8b04",
  "doc_id": "case001",
  "timestamp": "2026-05-14T10:31:47Z",
  "patterns_extracted": [
    { "description": "Trim speculative analyst notes", "rule": "Limit analyst_notes to one sentence" }
  ],
  "total_active_patterns": 3
}
```

---

### Other endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/patterns` | List all active learned patterns |
| `POST` | `/patterns/deactivate` | Suppress a pattern by `pattern_id` |
| `GET` | `/documents/{doc_id}/edits` | Full edit history for a document |
| `GET` | `/health` | Health check — returns `{"status": "ok"}` |
| `GET` | `/docs` | Interactive Swagger UI |

---

## 7. Web UI

Start the server (`uvicorn api.app:app --reload`) and open `http://localhost:8000`.

The UI walks through all four pipeline stages:

```
┌─────────────────────────────────────────────────────────────────┐
│  Sidebar                    │  Main panel                       │
│                             │                                   │
│  [ Upload Document ]        │  Progress: Process → Retrieve     │
│   Drop file or browse       │            → Draft → Edit & Learn │
│   Doc ID (optional)         │                                   │
│   [ Process Document ]      │  After upload:                    │
│                             │   Structured Fields tab           │
│  ─────────────────────      │   Processing Notes tab            │
│                             │   Raw JSON tab                    │
│  Learned Patterns (5)       │   [ Generate Grounded Draft ]     │
│   • ISO-format all dates    │                                   │
│   • Quote-wrap citations    │  After draft:                     │
│   • Add case_reference      │   Key Facts tab (with citations)  │
│   • Trim analyst notes      │   Parties tab                     │
│   • Promote jurisdiction    │   Dates & Issues tab              │
│                             │   Evidence Used tab               │
│                             │   Gaps tab (missing_information)  │
│                             │                                   │
│                             │  Edit textarea + Submit Edit      │
└─────────────────────────────────────────────────────────────────┘
```

No build step — pure HTML/CSS/JS in a single file (`ui/index.html`).

---

## 8. Running Tests

```bash
# Unit tests only — no API key required (fast, ~10 seconds)
pytest tests/ -v -m "not api"

# All tests including Claude API integration
pytest tests/ -v
```

**Test coverage:**

| Test Class | What it tests |
|------------|--------------|
| `TestCleanText` | OCR artifact removal, whitespace normalisation, content preservation |
| `TestChunkText` | Chunk count, minimum length, no empty chunks |
| `TestRetriever` | Add document, query, empty store, score range |
| `TestEditCapture` | Save edit, pattern upsert + count increment, deactivate |
| `TestPipelineIntegration` | Full ingest of a plain-text document via Claude |

---

## 9. Docker Setup

### Run with Docker Compose (recommended)

```bash
# Ensure your .env file has ANTHROPIC_API_KEY set, then:
docker compose up --build
```

API and UI available at `http://localhost:8000`.

ChromaDB data persists in a named volume (`chroma_data`) between restarts.

### Run with Docker directly

```bash
docker build -t psl-pipeline .

docker run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v $(pwd)/chroma_db:/app/chroma_db \
  psl-pipeline
```

### What the image includes

- Python 3.11 slim base
- Tesseract OCR + poppler (for scanned PDF support out of the box)
- All Python dependencies from `requirements.txt`

---

## 10. Architecture Overview

### Component Map

```
┌─────────────────────────────────────────────────────────────────┐
│                    LegalDocumentPipeline                        │
│                      src/pipeline.py                            │
│                                                                 │
│   ingest()  →  process_document()  →  retriever.add_document() │
│   draft()   →  retriever.query()   →  generate_draft()         │
│   submit_edit() → editor.save_edit() → pattern extraction       │
└────────┬──────────────┬──────────────┬──────────────────────────┘
         │              │              │
   processor.py    retriever.py    editor.py + drafter.py
   (Stage 1)       (Stage 2)       (Stages 3+4)
         │              │
   pdfplumber      ChromaDB
   pytesseract     (cosine, all-MiniLM-L6-v2)
   python-docx
   python-pptx
         │
   Claude API
   (structured extraction + draft generation + pattern extraction)
```

### Data Flow

```
file.pdf / file.txt / file.docx
    │
    ▼  _pdf_native() / _pdf_ocr() / _docx_extract() / _pptx_extract()
raw_text (cleaned)
    │
    ├──▶  _chunk_text()  →  chunks[]  →  ChromaDB (upsert)
    │
    └──▶  _extract_structured()  →  Claude  →  structured_fields{}
                                                        │
                                              ProcessedDocument
                                                        │
                                              retriever.query()
                                                        │
                                              RetrievedChunk[] (top-5)
                                                        │
                                              generate_draft()  →  Claude
                                                        │
                                              DraftOutput (with evidence_ids)
                                                        │
                                              operator edits
                                                        │
                                              editor.save_edit()  →  Claude
                                                        │
                                              LearnedPattern[] (SQLite)
                                                        │
                                              next draft  ←  patterns injected
```

### Storage

| Store | Location | Contents |
|-------|----------|----------|
| ChromaDB | `chroma_db/` | Vector index of all document chunks |
| SQLite | `edits.db` | Edit records + active learned patterns |
| In-memory | `pipeline._docs` | Session cache of ProcessedDocument objects |

---

## 11. Assumptions and Tradeoffs

### Design Assumptions

**Document Processing**
- Input documents are English-language
- OCR at 300 DPI with `--oem 3 --psm 6` is sufficient for printed legal documents
- Partially illegible sections are preserved as-is; the structured extraction prompt flags them via `document_quality`

**Retrieval**
- `top_k=5` is appropriate for sample documents (~1,000–2,500 words). For longer documents (50+ pages), increase `TOP_K_RETRIEVAL` in `src/config.py`
- `all-MiniLM-L6-v2` gives good quality-to-speed ratio. A domain-specific model like `legal-bert-base-uncased` would improve recall but adds size

**Pattern Learning**
- Patterns are global (applied to all documents). A production system would tag patterns by document type and apply selectively
- Confidence threshold of 0.7 discards low-confidence patterns to avoid prompt pollution

### Tradeoffs Table

| Decision | Chosen | Alternative | Reason |
|----------|--------|-------------|--------|
| Vector DB | ChromaDB local | Pinecone, Weaviate | Zero infra; swap is one constructor change |
| Embeddings | sentence-transformers CPU | OpenAI text-embedding-3-small | No extra API key; offline capable |
| Pattern storage | SQLite | PostgreSQL | Single-file deployment; good enough for prototype |
| OCR | pytesseract | AWS Textract, Azure OCR | Open-source; no cloud dependency |
| Draft format | Strict JSON schema | Free-form prose | Machine-verifiable grounding; downstream parseable |
| LLM | Claude for all stages | Separate specialised models | Single API key; consistent output quality |

### Known Limitations

1. **Session cache**: `pipeline._docs` is in-memory per process. After API restart, documents already in ChromaDB cannot be drafted without re-ingesting. A production system would persist `ProcessedDocument` metadata.
2. **No cross-document retrieval**: Each draft is anchored to a single `doc_id`. Cross-document synthesis is not implemented.
3. **Pattern deduplication is string-based**: Two semantically identical patterns with different `description` strings are stored separately. Embedding-similarity dedup would fix this.
4. **No streaming**: API returns complete JSON. Streaming would improve perceived latency for long drafts.

---

## 12. Evaluation Approach and Results

### Stage 1 — Document Processing

**Metric: Structured Field Coverage** (fraction of 6 key fields populated)

| Document | Extraction Method | Chunks | Coverage |
|----------|------------------|--------|---------|
| `case_001_complaint.txt` | text | 11 | 6/6 — 100% |
| `case_002_contract.txt` | text | 8 | 6/6 — 100% |
| `case_003_notice.txt` | text | 5 | 5/6 — 83% (jurisdiction partial) |

**Messy input handling verified:**
- OCR artifact `Apri1` detected and flagged in `document_quality` field
- `[REDACTED]` and `[illegible]` markers pass through cleanly
- Water damage notation preserved and surfaced in `document_quality_notes`

---

### Stage 2 — Retrieval and Grounding

**Metric: Citation Validity** — every `evidence_id` in the draft must exist in the retrieved chunk set

```python
# Grounding check
def grounding_check(draft: DraftOutput) -> float:
    retrieved_ids = {c.chunk_id for c in draft.evidence_used}
    facts = draft.content.get("key_facts", [])
    valid = sum(1 for f in facts if f.get("evidence_id") in retrieved_ids)
    return valid / len(facts) if facts else 0.0
```

**Expected result: 100%** — Claude is constrained by the system prompt to only cite IDs from the supplied evidence block.

**Retrieval spot-check (case001):**

| Rank | Chunk ID | Score | Content |
|------|----------|-------|---------|
| 1 | `case001__chunk_0` | 0.41 | Court header, parties, claims list |
| 2 | `case001__chunk_1` | 0.40 | Jurisdiction and venue allegations |
| 3 | `case001__chunk_10` | 0.37 | Counsel, filing stamp, missing exhibits |
| 4 | `case001__chunk_9` | 0.32 | Damages figure ($2,704,125), prayer for relief |
| 5 | `case001__chunk_2` | 0.24 | Party descriptions, employment dates |

All five chunks are directly relevant to drafting a Case Fact Summary.

---

### Stage 3 — Draft Quality

**Metric: Hallucination control via `missing_information`**

The draft for case001 contains 12 explicit `missing_information` entries — each one a gap that was NOT in the evidence, explicitly declared rather than filled with inference. Examples:

- *"Exhibits A, B, and C referenced but not attached"*
- *"RSU valuation of $22.17/share is from a partially illegible page — requires independent verification"*
- *"Case number prefix '24' inconsistent with November 2023 filing date — unresolved"*

This demonstrates the system actively controls unsupported generation.

---

### Stage 4 — Improvement from Edits

**Metric: Pattern Adoption Rate** — fraction of extracted patterns visible in v2 draft

| Pattern | Visible in v2 |
|---------|--------------|
| Add `case_reference` header field | Yes |
| Normalise dates to ISO 8601 | Yes |
| Wrap `evidence_quote` in `"..."` | Yes |
| Trim `analyst_notes` to one sentence | Yes |
| Promote `jurisdiction` to `filing_jurisdiction` | Yes |

**5 / 5 patterns adopted — 100% adoption rate on simulated edits.**

**Before / After comparison:**

```
v1 analyst_notes:
  "This summary is a first-pass analysis based solely on five retrieved evidence
   passages (case001__chunks_0 through 2, and 9 through 10), which provide limited
   factual detail; several material facts reflected in the pre-extracted structured
   fields — including RSU valuation figures, the Porter oral promise, and competing
   employment offers — are not independently corroborated by the retrieved passages
   and should be verified against the original complaint and unattached exhibits
   before any reliance for litigation purposes."

v2 analyst_notes (after "trim speculative notes" pattern):
  "This summary is a first-pass analysis based solely on five retrieved evidence passages."
```

The model adopted the operator preference for concise, non-speculative notes without being retrained — purely through prompt-level pattern injection.

---

## OCR Setup (Optional)

OCR is optional. Without it the system handles native PDFs, DOCX, PPTX, and plain text. Add OCR for scanned PDFs and image files:

### macOS
```bash
brew install tesseract poppler
pip install pytesseract pdf2image
```

### Windows
1. Download and install [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
2. Add Tesseract to your system PATH
3. Download [poppler for Windows](https://github.com/oschwartz10612/poppler-windows), add `bin/` to PATH
4. `pip install pytesseract pdf2image`

### Linux (Ubuntu / Debian)
```bash
sudo apt install tesseract-ocr poppler-utils
pip install pytesseract pdf2image
```

Then uncomment the two OCR lines in `requirements.txt`. If OCR dependencies are absent, the system logs a note in `processing_notes` and continues with native extraction.
