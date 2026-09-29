"""Supersession: find chunks that assert different values for the same key.

This is pattern matching, not language understanding. Two shapes are recognised,
one assertion per line or sentence:

``key: value``
    ``- Orion project lead: Sam Okafor``. The key is the text before the
    first colon (at most 6 words). Lines that look like URLs or times are skipped.

``X is Y`` / ``X is now Y`` / ``X moved to Y`` / ``X changed to Y``
    ``The Orion project lead is now Sam Okafor.`` The subject must have at least
    one content word and must not be a pronoun ("it", "this", "she" ...).

Keys are compared as a sorted set of stemmed content words, so "Project lead"
and "lead of the project" match. Outside dated log sections a key is qualified
with the document's entity (front matter ``entity:``, else the H1 title unless
that title is a date) when it does not already name it, so ``Status: paused`` in
``orion.md`` and in ``atlas.md`` are different keys, and ``Project lead`` in
``orion.md`` matches ``Orion project lead`` written in a log. Log entries under
a dated heading are not qualified: name the thing you are talking about.

Values are compared after dropping everything from the first ", ", ";" or
" - ", so trailing commentary does not create a false conflict.

The same key repeated with different values inside one file on one date is
read as a list, not a conflict.

When one key has several values, the chunk with the newest effective date wins
and the others are marked SUPERSEDED. Equal dates are reported as unresolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .markdown import Chunk, Document, is_date_heading
from .text import tokenize, words

_KV_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])?\s*(?:\*\*)?(?P<key>[^:|`]{2,60}?)(?:\*\*)?\s*:\s+(?P<val>\S.*)$")
_IS_RE = re.compile(
    r"^(?P<subj>[A-Za-z][\w'’ -]{1,60}?)\s+(?:is now|are now|is|are|moved to|changed to|was changed to|switched to)\s+(?P<val>[^.;]{1,80})",  # noqa: E501
)
_PRONOUNS = frozenset(
    [
        "it",
        "this",
        "that",
        "he",
        "she",
        "they",
        "there",
        "which",
        "who",
        "what",
        "we",
        "i",
        "you",
        "here",
        "these",
        "those",
        "one",
        "everything",
        "something",
        "nothing",
    ]
)
_SKIP_KEYS = frozenset({"http", "https", "note", "notes", "todo", "tip", "tl;dr", "example", "warning", "q", "a"})
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_TRAILING_RE = re.compile(r"\s*(\[(?:verified:[^\]]*|volatile)\])\s*", re.IGNORECASE)


@dataclass(frozen=True)
class Assertion:
    key: str  # canonical key, e.g. "lead orion project"
    label: str  # human readable key as written
    value: str  # normalised value for comparison
    raw_value: str


def _norm_value(v: str) -> str:
    v = _TRAILING_RE.sub(" ", v)
    v = re.split(r",\s|;|\s[-–—]\s", v, maxsplit=1)[0]
    v = re.sub(r"\(.*?\)", " ", v)
    toks = words(v)
    toks = [t for t in toks if t not in ("now", "currently", "still")]
    return " ".join(toks)


def _qualifier(doc: Document) -> list[str]:
    ent = doc.meta.get("entity", "")
    if ent:
        return tokenize(ent)
    title = doc.title
    if title and not is_date_heading(title):
        return tokenize(title)
    return []


def _key(subject: str, doc: Document, chunk: Chunk) -> tuple[str, str] | None:
    toks = tokenize(subject)
    if not toks:
        return None
    if chunk.date_source != "heading":
        qual = _qualifier(doc)
        if qual and not set(qual) & set(toks):
            toks = qual + toks
    if len(toks) > 8:
        return None
    return " ".join(sorted(set(toks))), subject.strip()


def extract(chunk: Chunk, doc: Document) -> list[Assertion]:
    """All key/value assertions found in a chunk."""
    if chunk.kind == "code":
        return []
    out: list[Assertion] = []
    for line in chunk.clean_text().split("\n"):
        kv = _KV_RE.match(line)
        if kv:
            key = kv.group("key").strip().strip("*_ ")
            first = words(key)[:1]
            if len(key.split()) <= 6 and not (first and first[0] in _SKIP_KEYS) and not re.search(r"\d$", key):
                k = _key(key, doc, chunk)
                val = _norm_value(kv.group("val"))
                if k and val:
                    out.append(Assertion(k[0], k[1], val, kv.group("val").strip()))
                    continue
        body = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)
        for sentence in _SENTENCE_RE.split(body):
            sentence = re.sub(r"^(?:the|my|our)\s+", "", sentence.strip(), flags=re.IGNORECASE)
            m = _IS_RE.match(sentence)
            if not m:
                continue
            subj = m.group("subj")
            if words(subj)[:1] and words(subj)[0] in _PRONOUNS:
                continue
            k = _key(subj, doc, chunk)
            val = _norm_value(m.group("val"))
            if k and val:
                out.append(Assertion(k[0], k[1], val, m.group("val").strip()))
    return out
