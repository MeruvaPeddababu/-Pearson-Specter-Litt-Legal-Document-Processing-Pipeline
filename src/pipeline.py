"""
Orchestrator: ties together processing → retrieval → drafting → edit capture.
"""
import logging
from typing import Optional

from .processor import process_document
from .retriever import DocumentRetriever
from .drafter import generate_draft
from .editor import EditCapture
from .models import DraftOutput, EditRecord, ProcessedDocument

logger = logging.getLogger(__name__)

_DEFAULT_DRAFT_QUERY = (
    "parties plaintiff defendant case facts dates legal issues claims jurisdiction"
)


class LegalDocumentPipeline:
    def __init__(self):
        self.retriever = DocumentRetriever()
        self.editor = EditCapture()
        self._docs: dict = {}  # doc_id → ProcessedDocument (session cache)

    # ── Stage 1 ───────────────────────────────────────────────────

    def ingest(self, file_path: str, doc_id: Optional[str] = None) -> ProcessedDocument:
        """
        Process a document and add it to the retrieval index.
        Returns the ProcessedDocument so callers can inspect extraction results.
        """
        logger.info(f"Ingesting: {file_path}")
        doc = process_document(file_path, doc_id=doc_id)
        self.retriever.add_document(doc)
        self._docs[doc.doc_id] = doc
        return doc

    # ── Stages 2 + 3 ─────────────────────────────────────────────

    def draft(
        self,
        doc_id: str,
        query: str = _DEFAULT_DRAFT_QUERY,
        top_k: int = 5,
    ) -> DraftOutput:
        """
        Retrieve relevant evidence for doc_id and generate a grounded draft.
        Learned operator patterns are automatically injected into the prompt.
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            raise ValueError(
                f"Document '{doc_id}' not found in session. Call ingest() first."
            )

        chunks = self.retriever.query(query, doc_id=doc_id, top_k=top_k)
        logger.info(f"[{doc_id}] Retrieved {len(chunks)} evidence chunks")

        patterns = self.editor.get_active_patterns()
        pattern_rules = [p.rule for p in patterns]

        return generate_draft(doc, chunks, pattern_rules)

    # ── Stage 4 ───────────────────────────────────────────────────

    def submit_edit(
        self, doc_id: str, original_draft: dict, edited_draft: dict
    ) -> EditRecord:
        """
        Capture an operator edit and extract reusable style patterns.
        Those patterns will be applied to all future drafts automatically.
        """
        return self.editor.save_edit(doc_id, original_draft, edited_draft)

    # ── Inspection ────────────────────────────────────────────────

    def get_patterns(self) -> list:
        return self.editor.get_active_patterns()

    def get_edit_history(self, doc_id: Optional[str] = None) -> list:
        return self.editor.get_edit_history(doc_id)
