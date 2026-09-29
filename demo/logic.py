"""Pure functions behind the Streamlit demo, kept out of app.py so pytest can cover them.

Nothing here touches the network or the filesystem beyond importing the package.
Visitor notes live only in the caller's session state.
"""

from __future__ import annotations

import html
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT / "bench"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from synth import NOW, generate  # noqa: E402

from plainmem import Engine, engine_from_texts  # noqa: E402
from plainmem.engine import Hit  # noqa: E402

MAX_NOTE_CHARS = 400
MAX_NOTES = 20
VISITOR_DIR = "visitor"

BADGE_COLORS = {
    "FRESH": "#1b7f3b",
    "AGING": "#9a6700",
    "STALE": "#b42318",
    "SUPERSEDED": "#6e40c9",
    "UNKNOWN": "#57606a",
    "BM25": "#57606a",
}


@dataclass
class Row:
    rank: int
    cite: str
    heading: str
    text: str
    status: str
    detail: str
    must_reverify: bool


def load_base(seed: int = 7) -> tuple[dict[str, str], dict[str, float], list]:
    c = generate(seed)
    return c.texts(), c.mtimes(), c.queries


def sample_queries(queries: list, per_type: int = 3) -> list[str]:
    """A few example questions of each type, in a stable order."""
    out: list[str] = []
    for qtype in ("superseded", "stale", "lookup", "paraphrase"):
        out += [q.query for q in queries if q.qtype == qtype][:per_type]
    return out


def make_note(text: str, day: date, index: int) -> tuple[str, str]:
    """Turn visitor input into a dated Markdown note. Raises ValueError on bad input."""
    body = re.sub(r"\s+", " ", (text or "")).strip()
    if not body:
        raise ValueError("Write something first.")
    if len(body) > MAX_NOTE_CHARS:
        raise ValueError(f"Keep it under {MAX_NOTE_CHARS} characters.")
    if index >= MAX_NOTES:
        raise ValueError(f"This demo keeps at most {MAX_NOTES} notes per session.")
    body = body.lstrip("#>-*` ")
    return f"{VISITOR_DIR}/note-{index + 1:02d}.md", f"# {day.isoformat()}\n\n- {body}\n"


def build_engine(base: dict[str, str], mtimes: dict[str, float], visitor: dict[str, str]) -> Engine:
    return engine_from_texts({**base, **visitor}, mtimes)


def _row(rank: int, h: Hit, mode: str) -> Row:
    f = h.freshness
    if mode == "bm25" or f is None:
        status, detail = "BM25", f"score {h.score:.2f}"
    else:
        status = h.status
        detail = f"{f.age_days}d old" if f.age_days is not None else "age unknown"
        if f.as_of:
            detail += f", as of {f.as_of}"
        if h.superseded_by:
            detail += "; superseded by " + ", ".join(c.cite for c in h.superseded_by)
        if h.supersedes:
            detail += "; replaces " + ", ".join(c.cite for c in h.supersedes)
    return Row(
        rank=rank,
        cite=h.chunk.cite,
        heading=" > ".join(h.chunk.heading_path),
        text=h.chunk.clean_text(),
        status=status,
        detail=detail,
        must_reverify=h.must_reverify,
    )


def run_query(engine: Engine, query: str, mode: str, k: int = 5, now: date = NOW) -> list[Row]:
    query = (query or "").strip()[:200]
    if not query:
        return []
    return [_row(i + 1, h, mode) for i, h in enumerate(engine.search(query, k=k, now=now, mode=mode))]


def badge_html(status: str) -> str:
    color = BADGE_COLORS.get(status, BADGE_COLORS["UNKNOWN"])
    return (
        f'<span style="background:{color};color:white;border-radius:4px;padding:1px 6px;'
        f'font-size:0.75em;font-weight:600">{html.escape(status)}</span>'
    )


def row_html(r: Row) -> str:
    """One result as escaped HTML. Visitor text is always escaped; nothing is rendered as markup."""
    warn = (
        '<div style="color:#b42318;font-size:0.8em">volatile fact past its window: re-verify before asserting</div>'
        if r.must_reverify
        else ""
    )
    return (
        f'<div style="margin-bottom:0.8em">{badge_html(r.status)} '
        f"<code>{html.escape(r.cite)}</code> "
        f'<span style="color:#57606a;font-size:0.8em">{html.escape(r.heading)}</span><br>'
        f"{html.escape(r.text)}<br>"
        f'<span style="color:#57606a;font-size:0.8em">{html.escape(r.detail)}</span>{warn}</div>'
    )


def visitor_conflicts(engine: Engine) -> list[dict[str, object]]:
    """Conflicts where a visitor note is involved, newest value first."""
    out = []
    for c in engine.conflicts:
        idxs = [c.winner, *c.losers]
        if not any(engine.chunks[i].path.startswith(VISITOR_DIR + "/") for i in idxs):
            continue
        out.append(
            {
                "key": c.label,
                "current": f"{engine.chunks[c.winner].cite}: {c.values[c.winner]}",
                "superseded": [f"{engine.chunks[i].cite}: {c.values[i]}" for i in c.losers],
                "resolved": c.resolved,
            }
        )
    return out
