from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProcessedDocument:
    doc_id: str
    file_path: str
    raw_text: str
    structured_fields: dict
    chunks: list
    extraction_method: str  # "native_pdf" | "ocr" | "text"
    processing_notes: list


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    text: str
    score: float
    chunk_index: int


@dataclass
class DraftOutput:
    doc_id: str
    draft_type: str
    generated_at: str
    content: dict
    applied_patterns: list
    evidence_used: list  # list[RetrievedChunk]


@dataclass
class EditRecord:
    edit_id: str
    doc_id: str
    original_draft: dict
    edited_draft: dict
    timestamp: str
    extracted_pattern: Optional[str] = None


@dataclass
class LearnedPattern:
    pattern_id: str
    description: str
    rule: str
    example_before: str
    example_after: str
    times_observed: int
    created_at: str
    active: bool = True
