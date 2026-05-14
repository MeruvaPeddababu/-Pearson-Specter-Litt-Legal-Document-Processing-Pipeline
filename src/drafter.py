"""
Draft generator: produces grounded Case Fact Summaries anchored
to retrieved evidence passages, with explicit citation IDs.
"""
import json
import logging
import re
from datetime import datetime, timezone

from anthropic import Anthropic

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .models import ProcessedDocument, RetrievedChunk, DraftOutput

logger = logging.getLogger(__name__)
_client = Anthropic(api_key=ANTHROPIC_API_KEY)

_SYSTEM = """\
You are a senior legal analyst at Pearson Specter Litt. Produce a structured Case Fact Summary.

Rules (non-negotiable):
1. Every fact MUST be directly supported by the evidence passages supplied.
2. If information is absent from the evidence, write "Not found in document" — never invent or infer.
3. For each fact or party, cite the exact evidence passage ID (e.g. "doc001__chunk_2").
4. Keep the tone formal and concise — this is a first-pass internal memo.
5. Note any gaps an attorney would expect to see.
{patterns_block}\
"""

_USER = """\
Document ID: {doc_id}

PRE-EXTRACTED STRUCTURED FIELDS:
{structured_fields}

RETRIEVED EVIDENCE PASSAGES (use these as your only factual source):
{evidence}

Produce a JSON object with this exact schema:
{{
  "case_title": "string or 'Not found in document'",
  "case_number": "string or null",
  "document_type": "string",
  "jurisdiction": "string or null",
  "parties": [
    {{
      "name": "string",
      "role": "string",
      "evidence_id": "chunk ID"
    }}
  ],
  "key_facts": [
    {{
      "fact": "stated fact",
      "evidence_id": "chunk ID",
      "evidence_quote": "verbatim short quote"
    }}
  ],
  "relevant_dates": [
    {{
      "date": "string",
      "event": "string",
      "evidence_id": "chunk ID"
    }}
  ],
  "legal_issues": [
    {{
      "issue": "string",
      "evidence_id": "chunk ID"
    }}
  ],
  "missing_information": ["things an attorney would expect but that are absent"],
  "document_quality_notes": "string — OCR issues, illegible sections, etc.",
  "analyst_notes": "one-sentence caveat on reliability/completeness"
}}

Return ONLY valid JSON.\
"""


def _format_evidence(chunks: list) -> str:
    parts = []
    for c in chunks:
        parts.append(f"[{c.chunk_id}] relevance={c.score:.3f}\n{c.text}")
    return "\n\n---\n\n".join(parts)


def generate_draft(
    doc: ProcessedDocument,
    retrieved_chunks: list,
    learned_patterns: list,
) -> DraftOutput:
    """Generate a grounded Case Fact Summary from retrieved evidence."""

    patterns_block = ""
    if learned_patterns:
        rules = "\n".join(f"  - {r}" for r in learned_patterns)
        patterns_block = f"\nApply these operator-validated style preferences:\n{rules}\n"

    system_prompt = _SYSTEM.format(patterns_block=patterns_block)

    user_msg = _USER.format(
        doc_id=doc.doc_id,
        structured_fields=json.dumps(doc.structured_fields, indent=2),
        evidence=_format_evidence(retrieved_chunks),
    )

    response = _client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=3000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw)

    try:
        content = json.loads(raw)
    except json.JSONDecodeError:
        content = {"raw_output": raw, "parse_error": "Response was not valid JSON"}

    return DraftOutput(
        doc_id=doc.doc_id,
        draft_type="case_fact_summary",
        generated_at=datetime.now(timezone.utc).isoformat(),
        content=content,
        applied_patterns=learned_patterns,
        evidence_used=retrieved_chunks,
    )
