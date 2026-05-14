import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str = "claude-sonnet-4-6"
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

CHROMA_PERSIST_DIR: str = str(BASE_DIR / "chroma_db")
EDIT_DB_PATH: str = str(BASE_DIR / "edits.db")

CHUNK_SIZE: int = 800
CHUNK_OVERLAP: int = 150
TOP_K_RETRIEVAL: int = 5
MAX_PATTERNS: int = 10
