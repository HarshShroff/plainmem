"""Write-path consolidation: decide whether a new note replaces a fact already on file.

The read path never calls a model. Consolidation runs once, when a note is written:

1. ``candidates`` lists current facts the new text is plausibly about: keys that share
   words with it (weighted by rarity, so an entity name counts for more than "project"),
   or whose current value it names.
2. A classifier (any callable, usually an LLM; see ``consolidate_llm.py``) returns a verdict
   ``{"relation": ..., "target": key | None, "reason": str}``.
3. ``validate`` checks the verdict. The target must be one of the candidates it was shown,
   otherwise the verdict counts as ``unrelated``. Anything malformed counts as ``unrelated``.
4. Only ``supersedes`` changes what is written: the note gets a ``{supersedes <key>}`` tag
   (``meta.py``), the same tag a person could have typed. The classifier never edits files.

The key is the identity: ``Orion project lead`` names the entity and the attribute. There are no
per-memory IDs.

``lexical_classifier`` is a deterministic, model-free classifier for comparison. It only
supersedes when the text has a change word ("took over", "no longer", "now" ...) and points at
exactly one candidate, by naming its current value or a word of its key.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from .engine import Engine
from .history import fact_entries
from .meta import parse_tag
from .text import tokenize

RELATIONS = ("supersedes", "refines", "contradicts", "unrelated", "insufficient")
TARGETED = ("supersedes", "refines", "contradicts")

Classifier = Callable[[str, list[dict[str, Any]]], Any]

_TAG_END_RE = re.compile(r"[ \t]*\{([^{}\n]*)\}[ \t]*$")
_PROPER_RE = re.compile(r"\b[A-Z][\w-]*")


@dataclass(frozen=True)
class Candidate:
    key: str  # label to write after "supersedes", e.g. "Orion project lead"
    canonical: str  # canonical key, e.g. "lead orion project"
    value: str
    cite: str
    as_of: date | None
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "cite": self.cite,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "score": round(self.score, 3),
        }


def _label(eng: Engine, i: int, label: str, canonical: str) -> str | None:
    """A human key that maps back to ``canonical`` when written in a dated log entry, else None."""
    want = set(canonical.split())
    lab = label.strip()
    if set(tokenize(lab)) == want:
        return lab
    doc = eng.doc_of[i]
    ent = doc.meta.get("entity") or doc.title
    if ent and set(tokenize(f"{ent} {lab}")) == want:
        return f"{ent} {lab}"
    return None


def _current(eng: Engine) -> dict[str, tuple[str, Any, set[str]]]:
    """canonical key -> (label, newest entry, value tokens). Cached on the engine."""
    cached = getattr(eng, "_consolidate_current", None)
    if cached is not None:
        return cached
    out: dict[str, tuple[str, Any, set[str]]] = {}
    for key, items in fact_entries(eng).items():
        cur = items[-1]
        label = None
        for e in reversed(items):  # newest label that round-trips, so a tagged update's label is reused
            label = _label(eng, e.index, e.label, key)
            if label:
                break
        if label and len(label) <= 60 and not re.search(r"[,{}\n]", label):
            out[key] = (label, cur, set(tokenize(cur.norm)))
    inv: dict[str, set[str]] = {}
    for key, (_, _, vtoks) in out.items():
        for t in set(key.split()) | vtoks:
            inv.setdefault(t, set()).add(key)
    eng._consolidate_current = out  # type: ignore[attr-defined]
    eng._consolidate_inv = inv  # type: ignore[attr-defined]
    return out


def candidates(eng: Engine, text: str, k: int = 10, boost: Sequence[int] = ()) -> list[Candidate]:
    """Current facts the text may be about, best first.

    A key qualifies when it shares a capitalised word (an entity or a name) with the text, or when
    the text names its current value; when the text has no capitalised word, any shared key word
    qualifies. ``boost`` is a list of chunk indices from another retriever (hybrid), whose keys are
    added and lifted.
    """
    cur = _current(eng)
    inv: dict[str, set[str]] = eng._consolidate_inv  # type: ignore[attr-defined]
    toks = set(tokenize(text))
    proper = set(tokenize(" ".join(_PROPER_RE.findall(text))))
    pool: set[str] = set()
    for t in toks:
        pool |= inv.get(t, set())
    boosted: dict[str, float] = {}
    for r, i in enumerate(boost):
        for a in eng.assertions[i]:
            if a.key in cur:
                boosted.setdefault(a.key, 1.0 / (1 + r))
    pool |= set(boosted)
    idf = eng.bm25.idf
    out: list[Candidate] = []
    for key in pool:
        label, entry, vtoks = cur[key]
        kt = set(key.split())
        key_hit = kt & toks
        val_hit = (vtoks & toks) - key_hit
        named_value = bool(vtoks) and vtoks <= toks
        if key not in boosted and not named_value and not (key_hit & proper if proper else key_hit):
            continue
        score = sum(idf(t) for t in key_hit) + 0.5 * sum(idf(t) for t in val_hit) + 2.0 * boosted.get(key, 0.0)
        out.append(Candidate(label, key, entry.value, entry.cite, entry.as_of, score))
    out.sort(key=lambda c: (-c.score, c.key))
    return out[: max(0, k)]


def _resolve(target: Any, cands: Sequence[Candidate]) -> Candidate | None:
    if not isinstance(target, str) or not target.strip():
        return None
    t = target.strip()
    for c in cands:
        if c.key == t:
            return c
    for c in cands:
        if c.key.lower() == t.lower() or c.canonical == t:
            return c
    return None


def validate(raw: Any, cands: Sequence[Candidate]) -> dict[str, Any]:
    """Check a classifier's verdict. Returns relation, target (a candidate key or None), reason, valid, note.

    An unknown relation, a non-dict, or a targeted relation whose target is not one of ``cands``
    becomes ``unrelated`` with ``valid: False``. ``insufficient`` and ``unrelated`` never carry a target.
    """
    bad = {"relation": "unrelated", "target": None, "reason": "", "valid": False}
    if not isinstance(raw, dict):
        return {**bad, "note": "verdict is not an object"}
    rel = str(raw.get("relation", "")).strip().lower()
    reason = str(raw.get("reason") or "")[:300]
    if rel not in RELATIONS:
        return {**bad, "reason": reason, "note": f"unknown relation {rel!r}"}
    if rel not in TARGETED:
        return {"relation": rel, "target": None, "reason": reason, "valid": True, "note": ""}
    c = _resolve(raw.get("target"), cands)
    if c is None:
        return {**bad, "reason": reason, "note": f"target {raw.get('target')!r} is not one of the candidates"}
    return {"relation": rel, "target": c.key, "reason": reason, "valid": True, "note": ""}


def tag_text(text: str, supersedes: str) -> str:
    """``text`` with ``supersedes <key>`` added to the tag on its first line (creating the tag if needed)."""
    key = " ".join(supersedes.split())
    if not key or len(key) > 60 or re.search(r"[,{}]", key):
        raise ValueError(f"not a usable key for supersedes: {supersedes!r}")
    first, nl, rest = text.strip().partition("\n")
    m = _TAG_END_RE.search(first)
    if m and parse_tag(m.group(1)) is not None:
        meta = parse_tag(m.group(1))
        if meta and meta.supersedes:
            raise ValueError("line already has a supersedes tag")
        inner = f"{m.group(1).strip()}, supersedes {key}"
        if parse_tag(inner) is None:
            raise ValueError(f"cannot add supersedes to tag {{{m.group(1)}}}")
        first = f"{first[: m.start()]} {{{inner}}}"
    else:
        first = f"{first.rstrip()} {{supersedes {key}}}"
    return first + nl + rest


def judge(eng: Engine, text: str, classifier: Classifier, k: int = 10, boost: Sequence[int] = ()) -> dict[str, Any]:
    """Candidates, the classifier's raw verdict and the validated verdict. Writes nothing.

    With no candidates the classifier is not called and the verdict is ``unrelated``. A classifier
    that raises counts as ``unrelated``.
    """
    cands = candidates(eng, text, k=k, boost=boost)
    shown = [c.to_dict() for c in cands]
    if not cands:
        verdict = {"relation": "unrelated", "target": None, "reason": "", "valid": True, "note": "no candidates"}
        return {"candidates": shown, "raw": None, "verdict": verdict, "called": False}
    try:
        raw = classifier(text, shown)
    except Exception as e:  # noqa: BLE001 - any classifier failure is "no change"
        raw = None
        note = f"classifier error: {e}"
        verdict = {"relation": "unrelated", "target": None, "reason": "", "valid": False, "note": note}
    else:
        verdict = validate(raw, cands)
    return {"candidates": shown, "raw": raw, "verdict": verdict, "called": True}


# --- model-free comparison classifier -------------------------------------------------

_CHANGE_RE = re.compile(
    r"\b(no longer|took over|takes over|taken over|replac\w*|switched|moved (?:off|to|onto)|migrat\w*|"
    r"from now on|now|these days|instead of|anymore|handed (?:over|off)|succeed\w*|changed hands|retired|"
    r"dropped|relocated|stepped (?:down|back))\b",
    re.IGNORECASE,
)
_HEDGE_RE = re.compile(
    r"\b(lately|maybe|may|might|probably|possibly|perhaps|evaluating|considering|suggested|thinking about|"
    r"rumou?r\w*|seems?|at some point|temporar\w*|covering|this week|for now|a few)\b",
    re.IGNORECASE,
)


def lexical_classifier(new_text: str, cands: list[dict[str, Any]]) -> dict[str, Any]:
    """Supersede only on a change word plus exactly one candidate pointed at; hedges are insufficient."""
    if _HEDGE_RE.search(new_text):
        return {"relation": "insufficient", "target": None, "reason": "hedged wording"}
    if not _CHANGE_RE.search(new_text):
        return {"relation": "unrelated", "target": None, "reason": "no change word"}
    toks = set(tokenize(new_text))
    proper = set(tokenize(" ".join(_PROPER_RE.findall(new_text))))
    by_value = [c for c in cands if (v := set(tokenize(c["value"]))) and v <= toks]
    if len(by_value) == 1:
        return {"relation": "supersedes", "target": by_value[0]["key"], "reason": "names the current value"}
    by_key = [c for c in cands if (set(tokenize(c["key"])) - proper) & toks]
    if len(by_key) == 1:
        return {"relation": "supersedes", "target": by_key[0]["key"], "reason": "names the attribute"}
    return {"relation": "insufficient", "target": None, "reason": f"{len(by_value)} value / {len(by_key)} key matches"}
