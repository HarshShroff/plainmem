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
from .meta import AUTHORITY_RANK
from .text import tokenize

SUPERSEDED = "SUPERSEDED"
EXPIRED = "EXPIRED"
WEAK_DATE_SOURCES = ("mtime", "unknown")  # dates that say when a file was saved, not when a fact became true


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
    facts: list[Assertion] = field(default_factory=list)
    expired: bool = False

    @property
    def status(self) -> str:
        if self.superseded_by:
            return SUPERSEDED
        if self.expired:
            return EXPIRED
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
    reason: str = ""  # why it is unresolved: "same-date" or "inferred-over-explicit"


@dataclass
class Links:
    conflicts: list[Conflict]
    superseded_by: dict[int, list[tuple[int, str]]]
    supersedes: dict[int, list[tuple[int, str]]]


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
        eff = [effective_date(c, d) for c, d in zip(self.chunks, self.doc_of, strict=True)]
        self.dates = [d for d, _ in eff]
        self.date_sources = [src for _, src in eff]
        self.assertions: list[list[Assertion]] = [extract(c, d) for c, d in zip(self.chunks, self.doc_of, strict=True)]
        self._links: dict[date | None, Links] = {}
        links = self.links(None)
        self.conflicts = links.conflicts
        self.superseded_by = links.superseded_by
        self.supersedes = links.supersedes

    # --- dates ------------------------------------------------------------

    def start(self, i: int, a: Assertion) -> date | None:
        """When an assertion took effect: its ``from`` tag, else its chunk's date."""
        return a.meta.valid_from or self.dates[i]

    def start_source(self, i: int, a: Assertion) -> str:
        return "tag:from" if a.meta.valid_from else self.date_sources[i]

    def exists_at(self, i: int, when: date) -> bool:
        """False only when the chunk is known to have been written, or to take effect, after ``when``."""
        if self.date_sources[i] in WEAK_DATE_SOURCES:
            return True
        d = self.dates[i]
        if d is not None and d > when:
            return False
        starts = [self.start(i, a) for a in self.assertions[i]]
        return not (starts and all(st is not None and st > when for st in starts))

    def expired_at(self, i: int, when: date) -> bool:
        """Every fact in the chunk carries an ``until`` date before ``when``."""
        al = self.assertions[i]
        return bool(al) and all(a.meta.valid_until is not None and a.meta.valid_until < when for a in al)

    # --- supersession -----------------------------------------------------

    def links(self, cutoff: date | None) -> Links:
        """Conflicts and supersession using only facts in effect by ``cutoff`` (None: all of them)."""
        if cutoff not in self._links:
            conflicts = self._conflicts(cutoff)
            superseded_by: dict[int, list[tuple[int, str]]] = defaultdict(list)
            supersedes: dict[int, list[tuple[int, str]]] = defaultdict(list)
            for cf in conflicts:
                if not cf.resolved:
                    continue
                for loser in cf.losers:
                    superseded_by[loser].append((cf.winner, cf.key))
                    supersedes[cf.winner].append((loser, cf.key))
            self._links[cutoff] = Links(conflicts, superseded_by, supersedes)
        return self._links[cutoff]

    def _conflicts(self, cutoff: date | None = None) -> list[Conflict]:
        by_key: dict[str, list[tuple[int, Assertion]]] = defaultdict(list)
        for i, alist in enumerate(self.assertions):
            for a in alist:
                st = self.start(i, a)
                if cutoff is not None and st is not None and st > cutoff:
                    continue
                by_key[a.key].append((i, a))
        out: list[Conflict] = []
        for key, items in by_key.items():
            if len({a.value for _, a in items}) < 2:
                continue
            # The same key repeated in one file on one date is a list ("On focus: ..."), not a change.
            if len({self.chunks[i].path for i, _ in items}) == 1 and len({self.start(i, a) for i, a in items}) == 1:
                continue
            dated = [(self.start(i, a) or date.min, i, a) for i, a in items]
            dated.sort(key=lambda t: (t[0], t[1]))
            newest_date = dated[-1][0]
            newest = [t for t in dated if t[0] == newest_date]
            ranks = [AUTHORITY_RANK.get(a.meta.authority or "", 0) for _, _, a in newest]
            top = max(ranks)
            leaders = [t for t, r in zip(newest, ranks, strict=True) if r == top]
            _, winner, win_a = leaders[-1]
            # Authority settles a same-date tie only when every rival is tagged and ranks lower.
            rivals = {a.value for _, _, a in newest} - {win_a.value}
            if (
                rivals
                and top
                and len({a.value for _, _, a in leaders}) == 1
                and all(a.meta.authority for _, _, a in newest)
            ):
                rivals = set()
            reason = "same-date" if rivals else ""
            losers = sorted({i for _, i, a in dated if a.value != win_a.value and i != winner})
            # An agent's guess never silently replaces what a person said.
            if (
                not reason
                and win_a.meta.authority == "inferred"
                and any(a.meta.authority == "explicit" and a.value != win_a.value for _, _, a in dated)
            ):
                reason = "inferred-over-explicit"
            values = {i: a.raw_value for _, i, a in dated}
            out.append(Conflict(key, items[0][1].label, winner, losers, values, not reason, reason))
        out.sort(key=lambda c: c.key)
        return out

    # --- search -----------------------------------------------------------

    def _hit(self, i: int, score: float, now: date, fresh: bool, links: Links | None = None) -> Hit:
        links = links or self.links(None)
        return Hit(
            chunk=self.chunks[i],
            score=score,
            freshness=assess(self.chunks[i], self.doc_of[i], now, self.cfg) if fresh else None,
            superseded_by=[self.chunks[j] for j, _ in links.superseded_by.get(i, [])] if fresh else [],
            supersedes=[self.chunks[j] for j, _ in links.supersedes.get(i, [])] if fresh else [],
            keys=sorted({k for _, k in links.superseded_by.get(i, [])} | {k for _, k in links.supersedes.get(i, [])}),
            facts=list(self.assertions[i]),
            expired=fresh and self.expired_at(i, now),
        )

    def search(
        self, query: str, k: int = 5, now: date | None = None, mode: str = "full", as_of: date | None = None
    ) -> list[Hit]:
        """Rank chunks for a query.

        mode="bm25" is plain BM25. mode="full" adds time decay, demotes
        superseded chunks and lifts the chunk that superseded them above them.
        ``as_of`` answers as of a past date: chunks known to be written or to take
        effect later are dropped, supersession uses only facts in effect by then,
        and ages are measured from that date. Chunks dated only by file mtime are
        kept, since their real date is unknown.
        """
        if mode not in ("full", "bm25"):
            raise ValueError(f"unknown mode {mode!r}")
        now = as_of or now or date.today()
        q = tokenize(query, stem=self.stem)
        raw = self.bm25.scores(q)
        if as_of is not None:
            raw = {i: s for i, s in raw.items() if self.exists_at(i, as_of)}
        if not raw:
            return []
        if mode == "bm25":
            ranked = sorted(raw.items(), key=lambda t: (-t[1], t[0]))[:k]
            return [self._hit(i, s, now, fresh=False) for i, s in ranked]
        return self.rerank(raw, set(q), k, now, as_of=as_of)

    def rerank(
        self, raw: dict[int, float], query_terms: set[str], k: int, now: date, as_of: date | None = None
    ) -> list[Hit]:
        """Apply time decay and supersession to any first-stage scores (BM25, embeddings, ...).

        ``raw`` maps chunk index to a non-negative relevance score. ``query_terms`` are
        stemmed query tokens, used to decide whether a superseding chunk is on topic.
        """
        links = self.links(as_of)
        w = self.rank.freshness_weight
        scored: dict[int, float] = {}
        for i, s in raw.items():
            f = assess(self.chunks[i], self.doc_of[i], now, self.cfg)
            s = s * ((1 - w) + w * f.decay)
            if i in links.superseded_by or self.expired_at(i, now):
                s *= self.rank.superseded_penalty
            scored[i] = s
        order = [i for i, _ in sorted(scored.items(), key=lambda t: (-t[1], t[0]))]
        if self.rank.promote_superseding:
            order = self._promote(order, query_terms, k, links)
        return [self._hit(i, scored.get(i, 0.0), now, fresh=True, links=links) for i in order[:k]]

    def _promote(self, order: list[int], qset: set[str], k: int, links: Links) -> list[int]:
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
            for j, key in links.supersedes.get(i, []):
                if j in in_window and set(key.split()) & qset:
                    put(j)

        for i in window:
            if i in placed:
                continue
            for j, key in links.superseded_by.get(i, []):
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
