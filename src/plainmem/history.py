"""Fact history: explain one fact and diff the facts between two dates.

Both are built on the assertions the engine already extracts (see ``facts.py``), so they
share its limits: a fact is a ``key: value`` or ``X is Y`` line, and its date is the
chunk's effective date (heading date, inline ``[verified:]``, front matter, else file mtime),
or the ``from`` date in the line's metadata tag when it has one.

``as_of`` answers what was true on a past date. Dates that only come from file mtime say when
a file was saved, not when a fact became true, so an answer resting on one is reported as
``uncertain`` (or ``unknown`` when that is all there is) rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .engine import WEAK_DATE_SOURCES, Engine, Hit
from .facts import display_value
from .freshness import assess
from .meta import FactMeta
from .text import tokenize


@dataclass(frozen=True)
class Entry:
    index: int  # chunk index
    label: str
    norm: str  # value as compared
    value: str  # value for display
    cite: str
    as_of: date | None  # when the value took effect
    source: str  # where that date came from
    meta: FactMeta

    @property
    def weak(self) -> bool:
        return self.as_of is None or self.source in WEAK_DATE_SOURCES


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def fact_entries(eng: Engine) -> dict[str, list[Entry]]:
    """Every assertion grouped by key, oldest first (undated entries sort before dated ones)."""
    out: dict[str, list[Entry]] = {}
    for i, alist in enumerate(eng.assertions):
        for a in alist:
            out.setdefault(a.key, []).append(
                Entry(
                    i,
                    a.label,
                    a.value,
                    display_value(a.raw_value),
                    eng.chunks[i].cite,
                    eng.start(i, a),
                    eng.start_source(i, a),
                    a.meta,
                )
            )
    for items in out.values():
        items.sort(key=lambda e: (e.as_of or date.min, e.index))
    return out


def _entry_dict(e: Entry) -> dict[str, Any]:
    m = e.meta.to_dict()
    return {
        "value": e.value,
        "cite": e.cite,
        "as_of": _iso(e.as_of),
        "date_source": e.source,
        "authority": m["authority"],
        "source": m["source"],
        "valid_from": m["valid_from"],
        "valid_until": m["valid_until"],
    }


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
        end = nxt.as_of if nxt else None
        until = e.meta.valid_until
        if until and (end is None or until < end):
            out.append({"value": e.value, "from": _iso(e.as_of), "to": _iso(until), "present": False})
        else:
            out.append({"value": e.value, "from": _iso(e.as_of), "to": _iso(end), "present": nxt is None})
    return out


def value_at(eng: Engine, key: str, items: list[Entry], when: date) -> tuple[Entry | None, str, bool]:
    """The entry in effect on ``when``, a status, and whether it was resolved.

    status is ``known``, ``uncertain`` (rests on a file-save date, or undated entries
    disagree), ``expired`` (its ``until`` date passed), ``none`` (nothing recorded yet)
    or ``unknown`` (only undated or later-saved entries exist).
    """
    in_effect = [e for e in items if e.as_of is not None and e.as_of <= when]
    if not in_effect:
        later_weak = any(e.weak for e in items)
        return None, ("unknown" if later_weak else "none"), True
    conflict = next((c for c in eng.links(when).conflicts if c.key == key), None)
    win = conflict.winner if conflict else in_effect[-1].index
    cur = next(e for e in reversed(in_effect) if e.index == win)
    status = "known"
    if cur.meta.valid_until is not None and cur.meta.valid_until < when:
        status = "expired"
    elif cur.weak or any(e.as_of is None and e.norm != cur.norm for e in items):
        status = "uncertain"
    return cur, status, conflict.resolved if conflict else True


def explain(
    eng: Engine, question: str, now: date, searched: dict[str, Any], as_of: date | None = None
) -> dict[str, Any]:
    res: dict[str, Any] = {"question": question, **searched, "as_of": _iso(as_of), "fact": None}
    hits = eng.search(question, k=10, now=now, as_of=as_of)
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
    ref = as_of or now
    if as_of is not None:
        found, status, resolved = value_at(eng, key, items, as_of)
        if found is None:
            res["fact"] = {"key": key, "label": items[-1].label, "status": status, "current": None}
            res["fact"]["timeline"] = timeline(items)
            return res
        cur = found
    else:
        conflict = next((c for c in eng.conflicts if c.key == key), None)
        cur = next(e for e in items if e.index == (conflict.winner if conflict else top_i))
        resolved = conflict.resolved if conflict else True
        status = "expired" if cur.meta.valid_until is not None and cur.meta.valid_until < now else "known"
    older = [e for e in items if e.norm != cur.norm and (e.as_of or date.min) <= (cur.as_of or date.min)]
    later = [e for e in items if e.norm != cur.norm and e.as_of is not None and e.as_of > ref]
    conflict = next((c for c in eng.links(as_of).conflicts if c.key == key), None)
    fr = assess(eng.chunks[cur.index], eng.doc_of[cur.index], ref, eng.cfg)
    res["fact"] = {
        "key": key,
        "label": cur.label,
        "status": status,
        "resolved": resolved,
        "unresolved_reason": conflict.reason if conflict and not conflict.resolved else None,
        "current": _entry_dict(cur),
        "superseded": [_entry_dict(e) for e in reversed(older)] if conflict else [],
        "changed_after": [_entry_dict(e) for e in later] if as_of is not None else [],
        "timeline": timeline(items) if conflict or later else timeline([cur]),
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
        row = {**_entry_dict(last), "label": last.label}
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
