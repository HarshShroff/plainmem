"""Freshness: how old is a fact, and should an agent trust it without re-checking?

Every chunk gets an effective date from the most specific source available:

1. an inline ``[verified: YYYY-MM-DD]`` tag in the chunk
2. a dated heading above it (``## 2026-03-14``), which is how logs are written
3. front matter ``verified:``, ``updated:`` or ``date:``
4. the file's modification time

Status thresholds are configurable. Volatile facts (explicitly tagged, or
matching the volatile patterns below) get a much shorter window, and past it
they are flagged ``must_reverify``: the agent may mention the note exists but
should not assert the value as current.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from .markdown import Chunk, Document, parse_date, truthy

FRESH = "FRESH"
AGING = "AGING"
STALE = "STALE"

# Heuristic volatile detector. Deliberately narrow: prices, opening hours,
# availability, status words and explicit "currently"/"as of" phrasing.
VOLATILE_PATTERNS = [
    r"\bcurrently\b",
    r"\bas of\b",
    r"\bright now\b",
    r"[$€£]\s?\d",
    r"\b\d+(?:\.\d+)?\s?(?:usd|eur|gbp|dollars)\b",
    r"\bprice[sd]?\b",
    r"\bcosts?\b",
    r"\bin stock\b",
    r"\bout of stock\b",
    r"\bavailab(?:le|ility)\b",
    r"\bopen (?:until|till|from|daily|now)\b",
    r"\bclosed (?:on|until|for)\b",
    r"\bhours:",
    r"\bstatus:",
    r"\bwait ?list\b",
]
_VOLATILE_RE = re.compile("|".join(VOLATILE_PATTERNS), re.IGNORECASE)


@dataclass(frozen=True)
class FreshnessConfig:
    aging_days: int = 90
    stale_days: int = 365
    volatile_window_days: int = 30
    half_life_days: float = 180.0
    detect_volatile: bool = True


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def mtime_to_date(mtime: float) -> date | None:
    """Convert an epoch mtime to a UTC date. Zero or garbage means unknown."""
    if not mtime or mtime < 0:
        return None
    try:
        return datetime.fromtimestamp(mtime, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def effective_date(chunk: Chunk, doc: Document) -> tuple[date | None, str]:
    """Best available date for a chunk plus where it came from."""
    if chunk.verified is not None:
        return chunk.verified, chunk.date_source or "inline"
    for key in ("verified", "updated", "date"):
        d = parse_date(doc.meta.get(key, ""))
        if d is not None:
            return d, f"front-matter:{key}"
    d = mtime_to_date(doc.mtime)
    if d is not None:
        return d, "mtime"
    return None, "unknown"


def is_volatile(chunk: Chunk, doc: Document, cfg: FreshnessConfig) -> bool:
    if chunk.volatile or truthy(doc.meta.get("volatile")):
        return True
    return cfg.detect_volatile and bool(_VOLATILE_RE.search(chunk.clean_text()))


@dataclass(frozen=True)
class Freshness:
    status: str
    age_days: int | None
    as_of: date | None
    source: str
    volatile: bool
    must_reverify: bool
    decay: float  # 0..1, 1 = brand new

    def note(self) -> str:
        if self.age_days is None:
            return "age unknown"
        base = f"{self.status}, {self.age_days}d old (as of {self.as_of}, from {self.source})"
        if self.must_reverify:
            base += "; volatile, must re-verify before asserting"
        return base


def assess(chunk: Chunk, doc: Document, now: date, cfg: FreshnessConfig) -> Freshness:
    as_of, source = effective_date(chunk, doc)
    volatile = is_volatile(chunk, doc, cfg)
    if as_of is None:
        return Freshness(STALE, None, None, source, volatile, volatile, 0.0)
    # Future dates (clock skew, typos) count as age 0, never negative.
    age = max(0, (now - as_of).days)
    if age <= cfg.aging_days:
        status = FRESH
    elif age <= cfg.stale_days:
        status = AGING
    else:
        status = STALE
    must = volatile and age > cfg.volatile_window_days
    if must:
        status = STALE
    decay = 0.5 ** (age / cfg.half_life_days) if cfg.half_life_days > 0 else 1.0
    return Freshness(status, age, as_of, source, volatile, must, decay)
