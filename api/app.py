"""
FastAPI REST interface for the Pearson Specter Litt pipeline.

Start with:  uvicorn api.app:app --reload
"""
import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import LegalDocumentPipeline

app = FastAPI(
    title="Pearson Specter Litt — Legal Document API",
    description="Document ingestion, grounded drafting, and operator-edit improvement.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_UI_DIR = Path(__file__).parent.parent / "ui"
if _UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR)), name="ui")

@app.get("/", include_in_schema=False)
async def serve_ui():
    index = _UI_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Pearson Specter Litt API — visit /docs"}

_pipeline = LegalDocumentPipeline()


# ── Request / response schemas ────────────────────────────────────────────────

class EditRequest(BaseModel):
    doc_id: str
    original_draft: dict
    edited_draft: dict


class DeactivatePatternRequest(BaseModel):
    pattern_id: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/documents/upload", summary="Upload and process a document")
async def upload_document(
    file: UploadFile = File(...),
    doc_id: Optional[str] = Form(default=None),
):
    """Accept a PDF, TXT, or image file and run it through the processing pipeline."""
    suffix = Path(file.filename or "upload").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        doc = _pipeline.ingest(tmp_path, doc_id=doc_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {
        "doc_id": doc.doc_id,
        "extraction_method": doc.extraction_method,
        "chunk_count": len(doc.chunks),
        "structured_fields": doc.structured_fields,
        "processing_notes": doc.processing_notes,
    }


@app.get("/documents/{doc_id}/draft", summary="Generate a grounded draft for a document")
async def get_draft(doc_id: str, query: str = "case facts parties dates legal issues"):
    """Generate a Case Fact Summary anchored to retrieved evidence."""
    try:
        draft = _pipeline.draft(doc_id, query=query)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "doc_id": draft.doc_id,
        "draft_type": draft.draft_type,
        "generated_at": draft.generated_at,
        "content": draft.content,
        "applied_patterns": draft.applied_patterns,
        "evidence_used": [
            {"chunk_id": c.chunk_id, "score": c.score, "text_preview": c.text[:200]}
            for c in draft.evidence_used
        ],
    }


@app.post("/edits", summary="Submit an operator edit to learn style patterns")
async def submit_edit(req: EditRequest):
    """Capture a human-edited draft and extract reusable style rules."""
    try:
        record = _pipeline.submit_edit(req.doc_id, req.original_draft, req.edited_draft)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    patterns = _pipeline.get_patterns()
    return {
        "edit_id": record.edit_id,
        "doc_id": record.doc_id,
        "timestamp": record.timestamp,
        "patterns_extracted": json.loads(record.extracted_pattern) if record.extracted_pattern else [],
        "total_active_patterns": len(patterns),
    }


@app.get("/patterns", summary="List all active learned patterns")
async def list_patterns():
    patterns = _pipeline.get_patterns()
    return [
        {
            "pattern_id": p.pattern_id,
            "description": p.description,
            "rule": p.rule,
            "times_observed": p.times_observed,
            "example_before": p.example_before,
            "example_after": p.example_after,
        }
        for p in patterns
    ]


@app.post("/patterns/deactivate", summary="Suppress a learned pattern")
async def deactivate_pattern(req: DeactivatePatternRequest):
    _pipeline.editor.deactivate_pattern(req.pattern_id)
    return {"status": "deactivated", "pattern_id": req.pattern_id}


@app.get("/documents/{doc_id}/edits", summary="Fetch edit history for a document")
async def edit_history(doc_id: str):
    records = _pipeline.get_edit_history(doc_id)
    return [
        {
            "edit_id": r.edit_id,
            "timestamp": r.timestamp,
            "patterns_extracted": json.loads(r.extracted_pattern) if r.extracted_pattern else [],
        }
        for r in records
    ]


@app.get("/health")
async def health():
    return {"status": "ok"}
