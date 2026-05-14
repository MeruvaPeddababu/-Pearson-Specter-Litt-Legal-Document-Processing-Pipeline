"""
Unit and integration tests for the Pearson Specter Litt pipeline.

Tests that hit the Claude API are marked with @pytest.mark.api
and are skipped unless ANTHROPIC_API_KEY is set.

Run all:           pytest tests/ -v
Skip API tests:    pytest tests/ -v -m "not api"
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.processor import _clean_text, _chunk_text
from src.models import ProcessedDocument, RetrievedChunk

_HAS_API_KEY = bool(os.getenv("ANTHROPIC_API_KEY"))


# ── Text cleaning ─────────────────────────────────────────────────────────────

class TestCleanText:
    def test_collapses_blank_lines(self):
        assert "\n\n\n" not in _clean_text("a\n\n\n\nb")

    def test_collapses_spaces(self):
        assert "   " not in _clean_text("foo   bar")

    def test_strips_non_ascii(self):
        result = _clean_text("hello\x00\xff world")
        assert "\x00" not in result
        assert "\xff" not in result

    def test_preserves_content(self):
        text = "Plaintiff John Doe vs. Acme Corp — Filed: 2024-01-15"
        result = _clean_text(text)
        assert "John Doe" in result
        assert "2024-01-15" in result

    def test_empty_string(self):
        assert _clean_text("") == ""


# ── Chunking ──────────────────────────────────────────────────────────────────

class TestChunkText:
    def test_single_short_paragraph(self):
        text = "A short legal document about a breach of contract."
        chunks = _chunk_text(text, chunk_size=500)
        assert len(chunks) == 1

    def test_multiple_paragraphs_produce_multiple_chunks(self):
        paragraphs = [f"Paragraph {i}: " + "word " * 60 for i in range(15)]
        text = "\n\n".join(paragraphs)
        chunks = _chunk_text(text, chunk_size=400, overlap=80)
        assert len(chunks) > 1

    def test_all_chunks_above_minimum_length(self):
        text = "\n\n".join(["x " * 30] * 10 + ["y"])  # last para is tiny
        chunks = _chunk_text(text)
        assert all(len(c.strip()) > 40 for c in chunks)

    def test_no_empty_chunks(self):
        text = "\n\n".join(["Para " + str(i) + " " + "content " * 20 for i in range(5)])
        chunks = _chunk_text(text)
        assert all(c.strip() for c in chunks)


# ── Retriever ─────────────────────────────────────────────────────────────────

class TestRetriever:
    @pytest.fixture
    def ephemeral_retriever(self):
        """Create a retriever backed by an in-memory ChromaDB instance."""
        import chromadb
        from chromadb.utils import embedding_functions
        from src.retriever import DocumentRetriever

        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        r = DocumentRetriever.__new__(DocumentRetriever)
        r._ef = ef
        r._chroma = chromadb.EphemeralClient()
        r._col = r._chroma.create_collection(
            name="test_col", embedding_function=ef, metadata={"hnsw:space": "cosine"}
        )
        return r

    def test_add_and_query(self, ephemeral_retriever):
        doc = ProcessedDocument(
            doc_id="t001",
            file_path="test.txt",
            raw_text="Alice Smith filed a complaint against Beta Corp for breach of contract.",
            structured_fields={},
            chunks=["Alice Smith filed a complaint against Beta Corp for breach of contract."],
            extraction_method="text",
            processing_notes=[],
        )
        ephemeral_retriever.add_document(doc)
        results = ephemeral_retriever.query("who filed the complaint?", doc_id="t001", top_k=1)
        assert len(results) == 1
        assert results[0].doc_id == "t001"
        assert "Alice Smith" in results[0].text

    def test_empty_store_returns_empty(self, ephemeral_retriever):
        results = ephemeral_retriever.query("anything", top_k=5)
        assert results == []

    def test_score_is_between_0_and_1(self, ephemeral_retriever):
        doc = ProcessedDocument(
            doc_id="t002",
            file_path="x.txt",
            raw_text="Legal matter concerning real estate title dispute in New York.",
            structured_fields={},
            chunks=["Legal matter concerning real estate title dispute in New York."],
            extraction_method="text",
            processing_notes=[],
        )
        ephemeral_retriever.add_document(doc)
        results = ephemeral_retriever.query("real estate", doc_id="t002")
        for r in results:
            assert 0.0 <= r.score <= 1.0


# ── EditCapture ───────────────────────────────────────────────────────────────

class TestEditCapture:
    @pytest.fixture
    def editor(self, tmp_path):
        from src.editor import EditCapture
        ec = EditCapture(db_path=str(tmp_path / "edits.db"))
        # Stub out API call
        ec._extract_patterns = lambda o, e: []
        return ec

    def test_save_and_retrieve(self, editor):
        orig = {"case_title": "Doe v. Corp", "key_facts": ["Fact A"]}
        edit = {"case_title": "Doe v. Corp", "key_facts": ["Fact A", "Fact B"]}
        record = editor.save_edit("doc1", orig, edit)
        assert record.edit_id
        history = editor.get_edit_history("doc1")
        assert len(history) == 1
        assert history[0].edit_id == record.edit_id

    def test_pattern_upsert_and_count(self, editor):
        p = {
            "description": "iso-dates",
            "rule": "Format all dates as ISO 8601 (YYYY-MM-DD)",
            "example_before": "01/15/2024",
            "example_after": "2024-01-15",
            "confidence": 0.9,
        }
        editor._upsert_pattern(p)
        editor._upsert_pattern(p)  # second time → increment count
        patterns = editor.get_active_patterns()
        assert len(patterns) == 1
        assert patterns[0].times_observed == 2

    def test_deactivate_removes_from_active(self, editor):
        p = {
            "description": "include-jurisdiction",
            "rule": "Always include filing jurisdiction",
            "example_before": "",
            "example_after": "Filed in: SDNY",
            "confidence": 0.85,
        }
        editor._upsert_pattern(p)
        patterns = editor.get_active_patterns()
        assert len(patterns) == 1

        editor.deactivate_pattern(patterns[0].pattern_id)
        assert editor.get_active_patterns() == []


# ── Integration: ingest plain-text document ───────────────────────────────────

@pytest.mark.api
@pytest.mark.skipif(not _HAS_API_KEY, reason="ANTHROPIC_API_KEY not set")
class TestPipelineIntegration:
    def test_text_document_full_ingest(self, tmp_path):
        """Full ingest of a plain-text document including structured extraction."""
        import chromadb
        from chromadb.utils import embedding_functions
        from src.pipeline import LegalDocumentPipeline
        from src.retriever import DocumentRetriever
        from src.editor import EditCapture

        doc_path = tmp_path / "case.txt"
        doc_path.write_text(
            "CIVIL COMPLAINT\n\n"
            "Plaintiff: Alice Smith\nDefendant: Beta Corporation\n\n"
            "On January 15, 2024, Beta Corporation breached Contract No. 2023-456 "
            "by failing to deliver industrial equipment as specified in the agreement. "
            "The plaintiff seeks compensatory damages of $120,000 and injunctive relief.\n\n"
            "Filed in: Superior Court, County of Los Angeles, State of California\n"
            "Filing Date: February 1, 2024\nCase No.: 24-CV-00512"
        )

        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        pipeline = LegalDocumentPipeline.__new__(LegalDocumentPipeline)
        pipeline._docs = {}

        retriever = DocumentRetriever.__new__(DocumentRetriever)
        retriever._ef = ef
        retriever._chroma = chromadb.EphemeralClient()
        retriever._col = retriever._chroma.create_collection(
            name="int_test", embedding_function=ef, metadata={"hnsw:space": "cosine"}
        )
        pipeline.retriever = retriever
        pipeline.editor = EditCapture(db_path=str(tmp_path / "test.db"))

        doc = pipeline.ingest(str(doc_path), doc_id="int001")

        assert doc.doc_id == "int001"
        assert doc.extraction_method == "text"
        assert len(doc.chunks) >= 1
        assert "Alice Smith" in doc.raw_text
        assert doc.structured_fields.get("document_type") is not None
