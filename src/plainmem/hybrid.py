"""Optional hybrid retrieval: BM25 and embeddings fused with reciprocal-rank fusion.

Needs the ``embeddings`` extra (``pip install 'plainmem[embeddings]'``) unless you pass your
own ``embed`` function. The core package never imports this module. Vectors live in memory
only; the Markdown stays the source of truth and nothing new is written to disk.

The fused ranking goes through the same freshness, supersession, expiry and ``as_of`` layer
as plain BM25 (``Engine.rerank``), so hybrid changes which chunks are found, not how their
lifecycle is judged.

    from plainmem import engine_from_texts
    from plainmem.hybrid import Hybrid
    hits = Hybrid(engine).search("who heads Orion?", k=5)
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import date

from .engine import Engine, Hit
from .text import tokenize

Embed = Callable[[list[str]], Sequence[Sequence[float]]]
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def rrf(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal-rank fusion: sum of 1 / (k + rank) over every ranking an item appears in (rank from 1)."""
    out: dict[int, float] = {}
    for ranking in rankings:
        for r, i in enumerate(ranking, start=1):
            out[i] = out.get(i, 0.0) + 1.0 / (k + r)
    return out


def sentence_transformer(model: str = DEFAULT_MODEL) -> Embed:
    """An ``embed`` function backed by sentence-transformers (normalised vectors, CPU)."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:  # pragma: no cover - depends on optional install
        raise ImportError("hybrid retrieval needs the embeddings extra: pip install 'plainmem[embeddings]'") from e
    st = SentenceTransformer(model, device="cpu")

    def embed(texts: list[str]) -> Sequence[Sequence[float]]:
        return st.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False).tolist()

    return embed


def _unit(v: Sequence[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class Hybrid:
    """BM25 + embedding retrieval over an ``Engine``'s chunks, fused with RRF."""

    def __init__(self, engine: Engine, embed: Embed | None = None, depth: int = 50, rrf_k: int = 60) -> None:
        self.engine = engine
        self.embed = embed or sentence_transformer()
        self.depth = depth
        self.rrf_k = rrf_k
        texts = [" > ".join(c.heading_path) + ": " + c.clean_text() for c in engine.chunks]
        self.vectors = [_unit(v) for v in self.embed(texts)] if texts else []

    def _dense(self, query: str, allowed: set[int] | None) -> list[int]:
        q = _unit(self.embed([query])[0])
        sims = [
            (sum(a * b for a, b in zip(q, v, strict=False)), i)
            for i, v in enumerate(self.vectors)
            if allowed is None or i in allowed
        ]
        sims.sort(key=lambda t: (-t[0], t[1]))
        return [i for _, i in sims[: self.depth]]

    def search(self, query: str, k: int = 5, now: date | None = None, as_of: date | None = None) -> list[Hit]:
        eng = self.engine
        now = as_of or now or date.today()
        if as_of is not None:
            query = query.replace(as_of.isoformat(), " ")
        q = tokenize(query, stem=eng.stem)
        allowed = {i for i in range(len(eng.chunks)) if eng.exists_at(i, as_of)} if as_of else None
        sparse = sorted(
            ((i, s) for i, s in eng.bm25.scores(q).items() if allowed is None or i in allowed),
            key=lambda t: (-t[1], t[0]),
        )
        rankings = [[i for i, _ in sparse[: self.depth]], self._dense(query, allowed)]
        fused = rrf(rankings, self.rrf_k)
        if not fused:
            return []
        return eng.rerank(fused, set(q), k, now, as_of=as_of)

    def searcher(self) -> Callable[..., list[Hit]]:
        """A drop-in for ``Engine.search`` (same keyword arguments), for ``history.explain``."""

        def run(query: str, k: int = 5, now: date | None = None, mode: str = "full", as_of: date | None = None):
            return self.search(query, k=k, now=now, as_of=as_of)

        return run
