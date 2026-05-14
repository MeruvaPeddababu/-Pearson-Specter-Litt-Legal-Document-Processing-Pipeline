"""
Retrieval layer: stores document chunks in ChromaDB and surfaces
relevant passages for grounded draft generation.
"""
import logging
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

from .config import CHROMA_PERSIST_DIR, EMBEDDING_MODEL, TOP_K_RETRIEVAL
from .models import ProcessedDocument, RetrievedChunk

logger = logging.getLogger(__name__)


class DocumentRetriever:
    def __init__(self, collection_name: str = "legal_docs", persist_dir: str = CHROMA_PERSIST_DIR):
        self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        self._chroma = chromadb.PersistentClient(path=persist_dir)
        self._col = self._chroma.get_or_create_collection(
            name=collection_name,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"Retriever ready — {self._col.count()} chunks in store")

    # ── Indexing ──────────────────────────────────────────────────

    def add_document(self, doc: ProcessedDocument) -> None:
        """Index all chunks of a processed document."""
        if not doc.chunks:
            logger.warning(f"[{doc.doc_id}] No chunks to index")
            return

        ids = [f"{doc.doc_id}__chunk_{i}" for i in range(len(doc.chunks))]
        metas = [
            {
                "doc_id": doc.doc_id,
                "chunk_index": i,
                "extraction_method": doc.extraction_method,
            }
            for i in range(len(doc.chunks))
        ]

        # Upsert in batches of 100 to avoid memory spikes
        for start in range(0, len(doc.chunks), 100):
            end = min(start + 100, len(doc.chunks))
            self._col.upsert(
                ids=ids[start:end],
                documents=doc.chunks[start:end],
                metadatas=metas[start:end],
            )

        logger.info(f"[{doc.doc_id}] Indexed {len(doc.chunks)} chunks")

    def delete_document(self, doc_id: str) -> None:
        self._col.delete(where={"doc_id": doc_id})
        logger.info(f"[{doc_id}] Removed from index")

    # ── Querying ──────────────────────────────────────────────────

    def query(
        self,
        query_text: str,
        doc_id: Optional[str] = None,
        top_k: int = TOP_K_RETRIEVAL,
    ) -> list:
        """
        Return the top-k most relevant chunks.
        Optionally restrict to a single document.
        Each result includes the source chunk_id for citation.
        """
        total = self._col.count()
        if total == 0:
            return []

        where = {"doc_id": doc_id} if doc_id else None
        n = min(top_k, total)

        results = self._col.query(
            query_texts=[query_text],
            n_results=n,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        chunks = []
        docs_list = results.get("documents", [[]])[0]
        metas_list = results.get("metadatas", [[]])[0]
        dists_list = results.get("distances", [[]])[0]

        for text, meta, dist in zip(docs_list, metas_list, dists_list):
            chunks.append(
                RetrievedChunk(
                    chunk_id=f"{meta['doc_id']}__chunk_{meta['chunk_index']}",
                    doc_id=meta["doc_id"],
                    text=text,
                    score=round(1.0 - dist, 4),  # cosine distance → similarity
                    chunk_index=meta["chunk_index"],
                )
            )

        return chunks

    def list_doc_ids(self) -> list:
        """Return the set of document IDs currently in the index."""
        result = self._col.get(include=["metadatas"])
        seen = set()
        for meta in result.get("metadatas", []):
            if meta and "doc_id" in meta:
                seen.add(meta["doc_id"])
        return list(seen)
