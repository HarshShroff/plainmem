"""plainmem: Markdown-first long-term memory for AI agents, with freshness awareness."""

from .engine import BM25, Engine, Hit, RankConfig
from .freshness import AGING, FRESH, STALE, FreshnessConfig
from .index import IndexCorruptError, IndexMissingError
from .memory import Memory, SearchResponse, engine_from_texts

__version__ = "0.1.0"

__all__ = [
    "AGING",
    "BM25",
    "FRESH",
    "STALE",
    "Engine",
    "FreshnessConfig",
    "Hit",
    "IndexCorruptError",
    "IndexMissingError",
    "Memory",
    "RankConfig",
    "SearchResponse",
    "engine_from_texts",
    "__version__",
]
