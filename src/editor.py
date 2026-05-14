"""
Edit capture and pattern learning.
Operators submit edited drafts; Claude extracts transferable style rules
that are persisted in SQLite and injected into all future drafts.
"""
import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from anthropic import Anthropic

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL, EDIT_DB_PATH, MAX_PATTERNS
from .models import EditRecord, LearnedPattern

logger = logging.getLogger(__name__)
_client = Anthropic(api_key=ANTHROPIC_API_KEY)

_PATTERN_PROMPT = """\
An AI generated a legal draft.  A human operator then edited it.
Your job: identify what was changed and distil *transferable* style rules
that should improve ALL future drafts — not just corrections of one-off errors.

ORIGINAL DRAFT:
{original}

EDITED DRAFT:
{edited}

Focus on:
- Structural additions or removals (new sections, reordered content)
- Tone shifts (more formal, more concise, fewer qualifiers)
- Formatting preferences (ISO dates, quoted evidence, bullet vs. prose)
- Content depth (more detail on parties, less speculation, include statutes)
- Citation style changes

Return a JSON array.  Each element:
{{
  "description": "short label (≤6 words)",
  "rule": "actionable instruction for the generator (start with a verb)",
  "example_before": "≤15-word quote from original illustrating the issue",
  "example_after": "≤15-word quote from edit showing the improvement",
  "confidence": 0.0-1.0
}}

Only include patterns with confidence ≥ 0.7.
If there are no transferable patterns, return [].
Return ONLY valid JSON.\
"""

_DDL = """\
CREATE TABLE IF NOT EXISTS edits (
    edit_id      TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL,
    original     TEXT NOT NULL,
    edited       TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    patterns_raw TEXT
);
CREATE TABLE IF NOT EXISTS patterns (
    pattern_id     TEXT PRIMARY KEY,
    description    TEXT NOT NULL,
    rule           TEXT NOT NULL,
    example_before TEXT,
    example_after  TEXT,
    times_observed INTEGER DEFAULT 1,
    created_at     TEXT NOT NULL,
    active         INTEGER DEFAULT 1
);
"""


class EditCapture:
    def __init__(self, db_path: str = EDIT_DB_PATH):
        self._db = db_path
        with sqlite3.connect(self._db) as conn:
            conn.executescript(_DDL)

    # ── Public interface ──────────────────────────────────────────

    def save_edit(self, doc_id: str, original_draft: dict, edited_draft: dict) -> EditRecord:
        """
        Persist an operator edit, extract reusable patterns via Claude,
        and upsert those patterns into the store.
        """
        edit_id = str(uuid.uuid4())[:12]
        timestamp = datetime.now(timezone.utc).isoformat()

        patterns = self._extract_patterns(original_draft, edited_draft)
        patterns_raw = json.dumps(patterns) if patterns else None

        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "INSERT INTO edits VALUES (?,?,?,?,?,?)",
                (
                    edit_id,
                    doc_id,
                    json.dumps(original_draft),
                    json.dumps(edited_draft),
                    timestamp,
                    patterns_raw,
                ),
            )

        for p in patterns:
            self._upsert_pattern(p)

        logger.info(f"[{edit_id}] Saved edit for {doc_id}, extracted {len(patterns)} pattern(s)")
        return EditRecord(
            edit_id=edit_id,
            doc_id=doc_id,
            original_draft=original_draft,
            edited_draft=edited_draft,
            timestamp=timestamp,
            extracted_pattern=patterns_raw,
        )

    def get_active_patterns(self, limit: int = MAX_PATTERNS) -> list:
        """Return active patterns ordered by frequency (most-observed first)."""
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                """SELECT pattern_id, description, rule, example_before, example_after,
                          times_observed, created_at, active
                   FROM patterns
                   WHERE active = 1
                   ORDER BY times_observed DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            LearnedPattern(
                pattern_id=r[0],
                description=r[1],
                rule=r[2],
                example_before=r[3] or "",
                example_after=r[4] or "",
                times_observed=r[5],
                created_at=r[6],
                active=bool(r[7]),
            )
            for r in rows
        ]

    def get_edit_history(self, doc_id: Optional[str] = None) -> list:
        with sqlite3.connect(self._db) as conn:
            if doc_id:
                rows = conn.execute(
                    "SELECT * FROM edits WHERE doc_id = ? ORDER BY timestamp DESC", (doc_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM edits ORDER BY timestamp DESC").fetchall()
        return [
            EditRecord(
                edit_id=r[0],
                doc_id=r[1],
                original_draft=json.loads(r[2]),
                edited_draft=json.loads(r[3]),
                timestamp=r[4],
                extracted_pattern=r[5],
            )
            for r in rows
        ]

    def deactivate_pattern(self, pattern_id: str) -> None:
        """Operator can suppress a pattern they no longer want applied."""
        with sqlite3.connect(self._db) as conn:
            conn.execute("UPDATE patterns SET active = 0 WHERE pattern_id = ?", (pattern_id,))

    # ── Internal helpers ──────────────────────────────────────────

    def _extract_patterns(self, original: dict, edited: dict) -> list:
        """Ask Claude to find transferable style rules from the edit diff."""
        response = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": _PATTERN_PROMPT.format(
                        original=json.dumps(original, indent=2)[:3000],
                        edited=json.dumps(edited, indent=2)[:3000],
                    ),
                }
            ],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'^```(?:json)?\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
        try:
            data = json.loads(raw)
            return [p for p in data if isinstance(p, dict) and p.get("rule")]
        except (json.JSONDecodeError, TypeError):
            logger.warning("Pattern extraction returned unparseable response")
            return []

    def _upsert_pattern(self, pattern: dict) -> None:
        """Increment count if an identical description exists; else insert."""
        desc = pattern.get("description", "unnamed")
        with sqlite3.connect(self._db) as conn:
            existing = conn.execute(
                "SELECT pattern_id FROM patterns WHERE description = ?", (desc,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE patterns SET times_observed = times_observed + 1 WHERE pattern_id = ?",
                    (existing[0],),
                )
            else:
                conn.execute(
                    "INSERT INTO patterns VALUES (?,?,?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4())[:12],
                        desc,
                        pattern.get("rule", ""),
                        pattern.get("example_before", ""),
                        pattern.get("example_after", ""),
                        1,
                        datetime.now(timezone.utc).isoformat(),
                        1,
                    ),
                )
