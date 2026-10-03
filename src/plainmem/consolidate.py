"""Write-path consolidation: decide whether a new note replaces a fact already on file.

The read path never calls a model. Consolidation runs once, when a note is written:

1. ``candidates`` lists current facts the new text is plausibly about: keys that share
   words with it (weighted by rarity, so an entity name counts for more than "project"),
   or whose current value it names.
2. A classifier (any callable, usually an LLM; see ``consolidate_llm.py``) returns a verdict
   ``{"relation": ..., "target": key | None, "reason": str}``.
3. ``validate`` checks the verdict before anything is applied: the relation is one of the five,
   the target is one of the candidates shown, it is still a current fact and in effect today, and
   (for ``supersedes``) the note supplies a value of its own. A verdict that fails any check becomes
   ``unrelated``, with the failed check in ``failed_check``. When unsure, nothing changes: a missed
   supersession leaves a stale answer that a later explicit note can fix, a false one hides a true fact.
4. Only ``supersedes`` changes what is written: the note gets a ``{supersedes <key>}`` tag
   (``meta.py``), the same tag a person could have typed. The classifier never edits files.

The key is the identity: ``Orion project lead`` names the entity and the attribute. There are no
per-memory IDs.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from .engine import Engine
from .history import fact_entries
from .meta import parse_tag, strip_tags
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
        named_value = any(t.isalpha() for t in vtoks) and vtoks <= toks
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


def validate(
    raw: Any,
    cands: Sequence[Candidate],
    eng: Engine | None = None,
    text: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Check a verdict. Returns relation, target, reason, valid, failed_check, note.

    Checks, in order: ``shape`` (an object), ``relation_allowed`` (one of RELATIONS),
    ``target_in_candidates`` (targeted relations only), and with ``eng`` given: ``target_current``
    (the key still has a current value, not past its ``until`` date) and, for ``supersedes`` with
    ``text`` given, ``supplies_value`` (the note has a content word that is neither in the key nor in
    the current value). A failed check gives ``relation: unrelated, valid: False``.
    """

    def fail(check: str, note: str, reason: str = "") -> dict[str, Any]:
        return {"relation": "unrelated", "target": None, "reason": reason, "valid": False,
                "failed_check": check, "note": note}  # fmt: skip

    if not isinstance(raw, dict):
        return fail("shape", "verdict is not an object")
    rel = str(raw.get("relation", "")).strip().lower()
    reason = str(raw.get("reason") or "")[:300]
    if rel not in RELATIONS:
        return fail("relation_allowed", f"unknown relation {rel!r}", reason)
    if rel not in TARGETED:
        return {"relation": rel, "target": None, "reason": reason, "valid": True, "failed_check": None, "note": ""}
    c = _resolve(raw.get("target"), cands)
    if c is None:
        return fail("target_in_candidates", f"target {raw.get('target')!r} is not one of the candidates", reason)
    if eng is not None:
        cur = _current(eng).get(c.canonical)
        until = cur[1].meta.valid_until if cur else None
        if cur is None or (until is not None and until < (today or date.today())):
            return fail("target_current", f"{c.key!r} has no value in effect", reason)
        if rel == "supersedes" and text is not None:
            own = set(tokenize(strip_tags(text))) - set(c.canonical.split()) - cur[2]
            if not own:
                return fail("supplies_value", "the note adds no value of its own", reason)
    return {"relation": rel, "target": c.key, "reason": reason, "valid": True, "failed_check": None, "note": ""}


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


def judge(
    eng: Engine,
    text: str,
    classifier: Classifier,
    k: int = 10,
    boost: Sequence[int] = (),
    today: date | None = None,
) -> dict[str, Any]:
    """Candidates, the classifier's raw verdict and the validated verdict. Writes nothing.

    With no candidates the classifier is not called and the verdict is ``unrelated``. A classifier
    that raises counts as ``unrelated``.
    """
    cands = candidates(eng, text, k=k, boost=boost)
    shown = [c.to_dict() for c in cands]
    if not cands:
        verdict = {"relation": "unrelated", "target": None, "reason": "", "valid": True, "failed_check": None,
                   "note": "no candidates"}  # fmt: skip
        return {"candidates": shown, "raw": None, "verdict": verdict, "called": False}
    try:
        raw = classifier(text, shown)
    except Exception as e:  # noqa: BLE001 - any classifier failure is "no change"
        raw = None
        note = f"classifier error: {e}"
        verdict = {"relation": "unrelated", "target": None, "reason": "", "valid": False,
                   "failed_check": "classifier_error", "note": note}  # fmt: skip
    else:
        verdict = validate(raw, cands, eng=eng, text=text, today=today)
    return {"candidates": shown, "raw": raw, "verdict": verdict, "called": True}
