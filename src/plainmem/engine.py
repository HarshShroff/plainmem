"""In-memory retrieval engine: BM25 over chunks, plus freshness and supersession.

The engine is pure: it takes parsed documents and a reference date and never
touches the filesystem. Persistence lives in ``index.py``.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from .facts import Assertion, extract
from .freshness import Freshness, FreshnessConfig, assess, effective_date
from .markdown import Chunk, Document
from .text import tokenize

SUPERSEDED = "SUPERSEDED"


class BM25:
    """Okapi BM25 with an inverted index. k1 and b are the usual defaults."""

    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.lengths = [len(d) for d in docs]
        self.avgdl = (sum(self.lengths) / self.n) if self.n else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, toks in enumerate(docs):
            for term, tf in Counter(toks).items():
                self.postings[term].append((i, tf))

    def idf(self, term: str) -> float:
        df = len(self.postings.get(term, ()))
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def scores(self, query: list[str]) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        if not self.n or self.avgdl == 0:
            return {}
        for term in set(query):
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = self.idf(term)
            for i, tf in plist:
                norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avgdl)
                out[i] += idf * tf * (self.k1 + 1) / (tf + norm)
        return dict(out)


def chunk_tokens(chunk: Chunk, stem: bool = True) -> list[str]:
    """Index tokens: the chunk text plus its heading path (headings counted once)."""
    toks = tokenize(chunk.clean_text(), stem=stem)
    head = tokenize(" ".join(chunk.heading_path), stem=stem)
    return toks + sorted(set(head) - set(toks))


@dataclass
class Hit:
    chunk: Chunk
    score: float
    freshness: Freshness | None = None
    superseded_by: list[Chunk] = field(default_factory=list)
    supersedes: list[Chunk] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.superseded_by:
            return SUPERSEDED
        return self.freshness.status if self.freshness else "UNKNOWN"

    @property
    def must_reverify(self) -> bool:
        return bool(self.freshness and self.freshness.must_reverify)


@dataclass
class Conflict:
    key: str
    label: str
    winner: int  # chunk index
    losers: list[int]
    values: dict[int, str]
    resolved: bool  # False when the newest date is shared by different values


@dataclass(frozen=True)
class RankConfig:
    freshness_weight: float = 0.25  # share of the score that decays with age
    superseded_penalty: float = 0.6  # multiplier for a chunk whose fact was replaced
    promote_superseding: bool = True


class Engine:
    def __init__(
        self,
        docs: list[Document],
        cfg: FreshnessConfig | None = None,
        rank: RankConfig | None = None,
        stem: bool = True,
        tokens: list[list[str]] | None = None,
    ) -> None:
        self.cfg = cfg or FreshnessConfig()
        self.rank = rank or RankConfig()
        self.stem = stem
        self.docs = docs
        self.chunks: list[Chunk] = []
        self.doc_of: list[Document] = []
        for d in docs:
            for c in d.chunks:
                self.chunks.append(c)
                self.doc_of.append(d)
        if tokens is not None and len(tokens) == len(self.chunks):
            self.tokens = tokens
        else:
            self.tokens = [chunk_tokens(c, stem) for c in self.chunks]
        self.bm25 = BM25(self.tokens)
        self.dates = [effective_date(c, d)[0] for c, d in zip(self.chunks, self.doc_of, strict=True)]
        self.assertions: list[list[Assertion]] = [extract(c, d) for c, d in zip(self.chunks, self.doc_of, strict=True)]
        self.conflicts = self._conflicts()
        self.superseded_by: dict[int, list[tuple[int, str]]] = defaultdict(list)
        self.supersedes: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for cf in self.conflicts:
            if not cf.resolved:
                continue
            for loser in cf.losers:
                self.superseded_by[loser].append((cf.winner, cf.key))
                self.supersedes[cf.winner].append((loser, cf.key))

    # --- supersession -----------------------------------------------------

    def _conflicts(self) -> list[Conflict]:
        by_key: dict[str, list[tuple[int, Assertion]]] = defaultdict(list)
        for i, alist in enumerate(self.assertions):
            for a in alist:
                by_key[a.key].append((i, a))
        out: list[Conflict] = []
        for key, items in by_key.items():
            if len({a.value for _, a in items}) < 2:
                continue
            dated = [(self.dates[i] or date.min, i, a) for i, a in items]
            dated.sort(key=lambda t: (t[0], t[1]))
            newest_date, winner, _ = dated[-1]
            winner_val = dated[-1][2].value
            same_day_rivals = {a.value for d, _, a in dated if d == newest_date} - {winner_val}
            losers = sorted({i for _, i, a in dated if a.value != winner_val and i != winner})
            values = {i: a.raw_value for _, i, a in dated}
            out.append(Conflict(key, items[0][1].label, winner, losers, values, not same_day_rivals))
        out.sort(key=lambda c: c.key)
        return out

    # --- search -----------------------------------------------------------

    def _hit(self, i: int, score: float, now: date, fresh: bool) -> Hit:
        return Hit(
            chunk=self.chunks[i],
            score=score,
            freshness=assess(self.chunks[i], self.doc_of[i], now, self.cfg) if fresh else None,
            superseded_by=[self.chunks[j] for j, _ in self.superseded_by.get(i, [])] if fresh else [],
            supersedes=[self.chunks[j] for j, _ in self.supersedes.get(i, [])] if fresh else [],
            keys=sorted({k for _, k in self.superseded_by.get(i, [])} | {k for _, k in self.supersedes.get(i, [])}),
        )

    def search(self, query: str, k: int = 5, now: date | None = None, mode: str = "full") -> list[Hit]:
        """Rank chunks for a query.

        mode="bm25" is plain BM25. mode="full" adds time decay, demotes
        superseded chunks and lifts the chunk that superseded them above them.
        """
        if mode not in ("full", "bm25"):
            raise ValueError(f"unknown mode {mode!r}")
        now = now or date.today()
        q = tokenize(query, stem=self.stem)
        raw = self.bm25.scores(q)
        if not raw:
            return []
        if mode == "bm25":
            ranked = sorted(raw.items(), key=lambda t: (-t[1], t[0]))[:k]
            return [self._hit(i, s, now, fresh=False) for i, s in ranked]

        return self.rerank(raw, set(q), k, now)

    def rerank(self, raw: dict[int, float], query_terms: set[str], k: int, now: date) -> list[Hit]:
        """Apply time decay and supersession to any first-stage scores (BM25, embeddings, ...).

        ``raw`` maps chunk index to a non-negative relevance score. ``query_terms`` are
        stemmed query tokens, used to decide whether a superseding chunk is on topic.
        """
        w = self.rank.freshness_weight
        scored: dict[int, float] = {}
        for i, s in raw.items():
            f = assess(self.chunks[i], self.doc_of[i], now, self.cfg)
            s = s * ((1 - w) + w * f.decay)
            if i in self.superseded_by:
                s *= self.rank.superseded_penalty
            scored[i] = s
        order = [i for i, _ in sorted(scored.items(), key=lambda t: (-t[1], t[0]))]
        if self.rank.promote_superseding:
            order = self._promote(order, query_terms, k)
        return [self._hit(i, scored.get(i, 0.0), now, fresh=True) for i in order[:k]]

    def _promote(self, order: list[int], qset: set[str], k: int) -> list[int]:
        """Group each fact with its history: the newest version first, superseded versions right below it.

        Only applies when the conflicting key shares a word with the query, so an unrelated
        hit is never displaced by a correction about something else.
        """
        window = order[: max(k * 3, k + 5)]
        in_window = set(window)
        out: list[int] = []
        placed: set[int] = set()

        def put(i: int) -> None:
            if i in placed:
                return
            out.append(i)
            placed.add(i)
            for j, key in self.supersedes.get(i, []):
                if j in in_window and set(key.split()) & qset:
                    put(j)

        for i in window:
            if i in placed:
                continue
            for j, key in self.superseded_by.get(i, []):
                if set(key.split()) & qset:
                    put(j)
            put(i)
        return out + [i for i in order if i not in placed]

    def stale(self, now: date | None = None) -> list[Hit]:
        """Every chunk that is volatile past its window, oldest first."""
        now = now or date.today()
        hits = []
        for i in range(len(self.chunks)):
            f = assess(self.chunks[i], self.doc_of[i], now, self.cfg)
            if f.must_reverify:
                hits.append(Hit(self.chunks[i], 0.0, f))
        hits.sort(key=lambda h: (-(h.freshness.age_days or 0), h.chunk.cite))
        return hits
