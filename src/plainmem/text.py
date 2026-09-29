"""Tokenizing, stopwords and a Porter stemmer, all stdlib.

The stemmer is a straight implementation of Porter (1980). It is not the most
accurate stemmer around, but it is small, deterministic and has no data files,
which matters more here than squeezing out the last point of recall.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "s",
        "t",
        "don",
        "isn",
        "wasn",
        "doesn",
        "didn",
        "won",
        "ll",
        "ve",
        "re",
        "d",
        "m",
        "o",
        "y",
        "what's",
        "whats",
    ]
)

_TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)


def normalize(text: str) -> str:
    """Casefold and strip accents so 'Café' and 'cafe' tokenize the same."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def words(text: str) -> list[str]:
    """Split text into lowercase word tokens (letters and digits, unicode aware)."""
    out = []
    for tok in _TOKEN_RE.findall(normalize(text)):
        tok = tok.replace("’", "'")
        if tok.endswith("'s"):
            tok = tok[:-2]
        out.append(tok.replace("'", ""))
    return [t for t in out if t]


def tokenize(text: str, *, stem: bool = True, drop_stopwords: bool = True) -> list[str]:
    """Words, optionally without stopwords and optionally stemmed."""
    toks = words(text)
    if drop_stopwords:
        toks = [t for t in toks if t not in STOPWORDS]
    if stem:
        toks = [porter_stem(t) for t in toks]
    return toks


# --- Porter stemmer ---------------------------------------------------------

_VOWELS = frozenset("aeiou")


def _is_cons(w: str, i: int) -> bool:
    ch = w[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        return i == 0 or not _is_cons(w, i - 1)
    return True


def _measure(stem: str) -> int:
    """Number of VC sequences in the stem ([C](VC)^m[V])."""
    m = 0
    prev_vowel = False
    for i in range(len(stem)):
        vowel = not _is_cons(stem, i)
        if prev_vowel and not vowel:
            m += 1
        prev_vowel = vowel
    return m


def _has_vowel(stem: str) -> bool:
    return any(not _is_cons(stem, i) for i in range(len(stem)))


def _double_cons(w: str) -> bool:
    return len(w) >= 2 and w[-1] == w[-2] and _is_cons(w, len(w) - 1)


def _cvc(w: str) -> bool:
    if len(w) < 3:
        return False
    return _is_cons(w, len(w) - 3) and not _is_cons(w, len(w) - 2) and _is_cons(w, len(w) - 1) and w[-1] not in "wxy"


def _replace(w: str, suffix: str, repl: str, min_m: int) -> str | None:
    if w.endswith(suffix):
        stem = w[: len(w) - len(suffix)]
        if _measure(stem) > min_m:
            return stem + repl
        return w
    return None


_STEP2 = [
    ("ational", "ate"),
    ("tional", "tion"),
    ("enci", "ence"),
    ("anci", "ance"),
    ("izer", "ize"),
    ("bli", "ble"),
    ("alli", "al"),
    ("entli", "ent"),
    ("eli", "e"),
    ("ousli", "ous"),
    ("ization", "ize"),
    ("ation", "ate"),
    ("ator", "ate"),
    ("alism", "al"),
    ("iveness", "ive"),
    ("fulness", "ful"),
    ("ousness", "ous"),
    ("aliti", "al"),
    ("iviti", "ive"),
    ("biliti", "ble"),
    ("logi", "log"),
]
_STEP3 = [
    ("icate", "ic"),
    ("ative", ""),
    ("alize", "al"),
    ("iciti", "ic"),
    ("ical", "ic"),
    ("ful", ""),
    ("ness", ""),
]
_STEP4 = [
    "al",
    "ance",
    "ence",
    "er",
    "ic",
    "able",
    "ible",
    "ant",
    "ement",
    "ment",
    "ent",
    "ion",
    "ou",
    "ism",
    "ate",
    "iti",
    "ous",
    "ive",
    "ize",
]


@lru_cache(maxsize=65536)
def porter_stem(word: str) -> str:
    """Porter stemmer. Words of two letters or fewer and tokens with digits pass through."""
    w = word
    if len(w) <= 2 or any(ch.isdigit() for ch in w) or not w.isascii():
        return w
    # step 1a
    if w.endswith("sses") or w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("ss"):
        pass
    elif w.endswith("s"):
        w = w[:-1]
    # step 1b
    extra = False
    if w.endswith("eed"):
        if _measure(w[:-3]) > 0:
            w = w[:-1]
    elif w.endswith("ed") and _has_vowel(w[:-2]):
        w, extra = w[:-2], True
    elif w.endswith("ing") and _has_vowel(w[:-3]):
        w, extra = w[:-3], True
    if extra:
        if w.endswith(("at", "bl", "iz")):
            w += "e"
        elif _double_cons(w) and w[-1] not in "lsz":
            w = w[:-1]
        elif _measure(w) == 1 and _cvc(w):
            w += "e"
    # step 1c
    if w.endswith("y") and _has_vowel(w[:-1]):
        w = w[:-1] + "i"
    # step 2
    for suf, rep in _STEP2:
        r = _replace(w, suf, rep, 0)
        if r is not None:
            w = r
            break
    # step 3
    for suf, rep in _STEP3:
        r = _replace(w, suf, rep, 0)
        if r is not None:
            w = r
            break
    # step 4
    for suf in _STEP4:
        if w.endswith(suf):
            stem = w[: len(w) - len(suf)]
            if _measure(stem) > 1:
                if suf == "ion":
                    if stem and stem[-1] in "st":
                        w = stem
                else:
                    w = stem
            break
    # step 5a
    if w.endswith("e"):
        stem = w[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _cvc(stem)):
            w = stem
    # step 5b
    if _measure(w) > 1 and _double_cons(w) and w.endswith("l"):
        w = w[:-1]
    return w
