"""Fact history: explain one fact and diff the facts between two dates.

Both are built on the assertions the engine already extracts (see ``facts.py``), so they
share its limits: a fact is a ``key: value`` or ``X is Y`` line, and its date is the
chunk's effective date (heading date, inline ``[verified:]``, front matter, else file mtime).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .engine import Engine, Hit
from .facts import display_value
from .freshness import assess, effective_date
from .text import tokenize


@dataclass(frozen=True)
class Entry:
    index: int  # chunk index
    label: str
    norm: str  # value as compared
    value: str  # value for display
    cite: str
    as_of: date | None
    source: str  # where the date came from


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def fact_entries(eng: Engine) -> dict[str, list[Entry]]:
    """Every assertion grouped by key, oldest first (undated entries sort before dated ones)."""
    out: dict[str, list[Entry]] = {}
    for i, alist in enumerate(eng.assertions):
        for a in alist:
            _, src = effective_date(eng.chunks[i], eng.doc_of[i])
            out.setdefault(a.key, []).append(
                Entry(i, a.label, a.value, display_value(a.raw_value), eng.chunks[i].cite, eng.dates[i], src)
            )
    for items in out.values():
        items.sort(key=lambda e: (e.as_of or date.min, e.index))
    return out


def _entry_dict(e: Entry) -> dict[str, Any]:
    return {"value": e.value, "cite": e.cite, "as_of": _iso(e.as_of), "date_source": e.source}


def _pick_fact(eng: Engine, hits: list[Hit], qset: set[str]) -> tuple[str, int] | None:
    """The first hit that states a fact whose key shares a word with the question."""
    pos = {id(c): i for i, c in enumerate(eng.chunks)}
    for h in hits:
        i = pos[id(h.chunk)]
        scored = [(len(set(a.key.split()) & qset), a.key) for a in eng.assertions[i]]
        scored = [s for s in scored if s[0] > 0]
        if scored:
            return max(scored, key=lambda s: (s[0], -len(s[1])))[1], i
    return None


def timeline(items: list[Entry]) -> list[dict[str, Any]]:
    """Value changes in order: each value from the date it was first seen to the next different value."""
    spans: list[Entry] = []
    for e in items:
        if not spans or spans[-1].norm != e.norm:
            spans.append(e)
    out = []
    for n, e in enumerate(spans):
        nxt = spans[n + 1] if n + 1 < len(spans) else None
        out.append(
            {"value": e.value, "from": _iso(e.as_of), "to": _iso(nxt.as_of) if nxt else None, "present": nxt is None}
        )
    return out


def explain(eng: Engine, question: str, now: date, searched: dict[str, Any]) -> dict[str, Any]:
    res: dict[str, Any] = {"question": question, **searched, "fact": None}
    hits = eng.search(question, k=10, now=now)
    res["no_match"] = not hits
    res["no_fact"] = False
    if not hits:
        return res
    picked = _pick_fact(eng, hits, set(tokenize(question, stem=eng.stem)))
    if picked is None:
        res["no_fact"] = True
        res["nearest"] = [h.chunk.cite for h in hits[:3]]
        return res
    key, top_i = picked
    items = fact_entries(eng)[key]
    conflict = next((c for c in eng.conflicts if c.key == key), None)
    cur = next(e for e in items if e.index == (conflict.winner if conflict else top_i))
    older = [e for e in items if conflict and e.index in conflict.losers and e.norm != cur.norm]
    fr = assess(eng.chunks[cur.index], eng.doc_of[cur.index], now, eng.cfg)
    res["fact"] = {
        "key": key,
        "label": cur.label,
        "resolved": conflict.resolved if conflict else True,
        "current": _entry_dict(cur),
        "superseded": [_entry_dict(e) for e in reversed(older)],
        "timeline": timeline(items) if conflict else timeline([cur]),
        "freshness": {
            "status": fr.status,
            "age_days": fr.age_days,
            "as_of": _iso(fr.as_of),
            "volatile": fr.volatile,
            "must_reverify": fr.must_reverify,
        },
    }
    return res


def diff(eng: Engine, since: date, until: date | None) -> dict[str, Any]:
    """Facts that first appeared (added) or whose value changed (updated) between two dates, inclusive."""
    added: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    skipped = 0
    for items in fact_entries(eng).values():
        dated = [e for e in items if e.as_of]
        skipped += len(items) - len(dated)
        before = [e for e in dated if e.as_of < since]
        inside = [e for e in dated if e.as_of >= since and (until is None or e.as_of <= until)]
        if not inside:
            continue
        last = inside[-1]
        row = {"label": last.label, "value": last.value, "cite": last.cite, "as_of": _iso(last.as_of)}
        if not before:
            added.append(row)
        elif before[-1].norm != last.norm:
            updated.append({**row, "previous": _entry_dict(before[-1])})
    added.sort(key=lambda r: (r["as_of"], r["label"]))
    updated.sort(key=lambda r: (r["as_of"], r["label"]))
    return {
        "since": since.isoformat(),
        "until": _iso(until),
        "added": added,
        "updated": updated,
        "undated_skipped": skipped,
    }
