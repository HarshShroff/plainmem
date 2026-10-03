"""High level API: a directory of Markdown notes you can index, search and append to."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import history
from . import index as idx
from . import log as logmod
from .engine import Conflict, Engine, Hit, RankConfig
from .facts import display_value
from .freshness import FreshnessConfig
from .markdown import Document, parse


@dataclass
class SearchResponse:
    query: str
    searched_at: str
    index_version: str
    files_indexed: int
    chunks_indexed: int
    mode: str
    hits: list[Hit]
    as_of: date | None = None

    @property
    def no_match(self) -> bool:
        return not self.hits

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "searched_at": self.searched_at,
            "index_version": self.index_version,
            "files_indexed": self.files_indexed,
            "chunks_indexed": self.chunks_indexed,
            "mode": self.mode,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "no_match": self.no_match,
            "results": [hit_to_dict(h) for h in self.hits],
        }


def fact_to_dict(a: Any) -> dict[str, Any]:
    return {"label": a.label, "value": display_value(a.raw_value), **a.meta.to_dict()}


def hit_to_dict(h: Hit) -> dict[str, Any]:
    f = h.freshness
    facts = [fact_to_dict(a) for a in h.facts]
    tagged = next((x for x in facts if x["authority"] or x["source"] or x["valid_from"] or x["valid_until"]), None)
    return {
        "cite": h.chunk.cite,
        "path": h.chunk.path,
        "line": h.chunk.start_line,
        "end_line": h.chunk.end_line,
        "heading_path": h.chunk.heading_path,
        "text": h.chunk.clean_text(),
        "score": round(h.score, 4),
        "status": h.status,
        "age_days": f.age_days if f else None,
        "as_of": f.as_of.isoformat() if f and f.as_of else None,
        "date_source": f.source if f else None,
        "volatile": f.volatile if f else None,
        "must_reverify": h.must_reverify,
        "superseded_by": [c.cite for c in h.superseded_by],
        "supersedes": [c.cite for c in h.supersedes],
        "keys": h.keys,
        # provenance of the first tagged fact in the chunk (most chunks hold one line); every fact is in "facts"
        "authority": tagged["authority"] if tagged else None,
        "source": tagged["source"] if tagged else None,
        "valid_from": tagged["valid_from"] if tagged else None,
        "valid_until": tagged["valid_until"] if tagged else None,
        "facts": facts,
    }


def conflict_to_dict(engine: Engine, c: Conflict) -> dict[str, Any]:
    def entry(i: int) -> dict[str, Any]:
        d = engine.dates[i]
        return {"cite": engine.chunks[i].cite, "value": c.values[i], "as_of": d.isoformat() if d else None}

    return {
        "key": c.key,
        "label": c.label,
        "resolved": c.resolved,
        "unresolved_reason": c.reason or None,
        "current": entry(c.winner),
        "superseded": [entry(i) for i in c.losers],
    }


class Memory:
    """A notes directory plus its disposable index.

    ``Memory(root).search("...")`` loads the index (building it the first time),
    runs an incremental refresh unless ``refresh=False``, and returns a
    ``SearchResponse`` that records when and against which index it searched.
    """

    def __init__(
        self,
        root: str | Path,
        index_dir: str | Path | None = None,
        cfg: FreshnessConfig | None = None,
        rank: RankConfig | None = None,
        embed: Any = None,
    ) -> None:
        """``embed`` is an optional ``list[str] -> vectors`` function for mode="hybrid"
        (default: sentence-transformers, from the ``embeddings`` extra)."""
        self.embed = embed
        self._hybrid: Any = None
        self.root = Path(root).expanduser().resolve()
        self.index_file = idx.index_path(self.root, Path(index_dir) if index_dir else None)
        self.cfg = cfg or FreshnessConfig()
        self.rank = rank or RankConfig()
        self._data: idx.IndexData | None = None
        self._engine: Engine | None = None

    # --- index lifecycle -------------------------------------------------

    def index(self, rebuild: bool = False) -> dict[str, Any]:
        prev = None if rebuild else self._data
        if prev is None and not rebuild:
            try:
                prev = idx.load(self.index_file)
            except (idx.IndexMissingError, idx.IndexCorruptError):
                prev = None
        data, stats = idx.build(self.root, prev)
        stats["bytes"] = idx.save(data, self.index_file)
        stats["version"] = data.version
        stats["files"] = len(data.docs)
        stats["chunks"] = sum(len(d.chunks) for d in data.docs.values())
        self._set(data)
        return stats

    def load(self) -> idx.IndexData:
        """Load the saved index. Raises IndexMissingError / IndexCorruptError (fail closed)."""
        data = idx.load(self.index_file)
        self._set(data)
        return data

    def _set(self, data: idx.IndexData) -> None:
        self._data = data
        self._hybrid = None
        self._engine = Engine(data.ordered_docs(), self.cfg, self.rank, tokens=data.ordered_tokens())

    def ensure(self, refresh: bool = True) -> Engine:
        if self._engine is None:
            if self.index_file.exists():
                self.load()  # corrupt index raises here rather than being silently replaced
                if refresh:
                    self.index()
            else:
                self.index()
        elif refresh:
            self.index()
        assert self._engine is not None
        return self._engine

    @property
    def engine(self) -> Engine:
        return self.ensure(refresh=False)

    # --- queries ---------------------------------------------------------

    def search(
        self,
        query: str,
        k: int = 5,
        now: date | None = None,
        mode: str = "full",
        refresh: bool = True,
        as_of: date | None = None,
    ) -> SearchResponse:
        """Ranked hits. ``as_of`` searches the notes as they stood on that date (see ``Engine.search``)."""
        eng = self.ensure(refresh=refresh)
        assert self._data is not None
        if mode == "hybrid":
            hits = self.hybrid().search(query, k=k, now=now, as_of=as_of)
        else:
            hits = eng.search(query, k=k, now=now, mode=mode, as_of=as_of)
        return SearchResponse(
            query=query,
            searched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            index_version=self._data.version,
            files_indexed=len(self._data.docs),
            chunks_indexed=len(eng.chunks),
            mode=mode,
            hits=hits,
            as_of=as_of,
        )

    def hybrid(self) -> Any:
        """The BM25 + embeddings retriever (``hybrid.py``), built on first use. Needs the embeddings extra."""
        from .hybrid import Hybrid

        eng = self.ensure(refresh=False)
        if self._hybrid is None or self._hybrid.engine is not eng:
            self._hybrid = Hybrid(eng, self.embed)
        return self._hybrid

    def explain(
        self,
        question: str,
        now: date | None = None,
        refresh: bool = True,
        as_of: date | None = None,
        mode: str = "full",
    ) -> dict[str, Any]:
        """Current answer, superseded values, timeline and freshness for the fact a question is about.

        With ``as_of``, the answer is the value in effect on that date, with a ``status`` of
        known / uncertain / expired / none / unknown instead of a guess.
        """
        eng = self.ensure(refresh=refresh)
        assert self._data is not None
        searched = {
            "searched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "index_version": self._data.version,
            "files_indexed": len(self._data.docs),
            "chunks_indexed": len(eng.chunks),
        }
        search = self.hybrid().searcher() if mode == "hybrid" else None
        return history.explain(eng, question, now or date.today(), searched, as_of=as_of, search=search)

    def diff(self, since: date, until: date | None = None, refresh: bool = True) -> dict[str, Any]:
        """Facts added or updated between two dates (inclusive), by entry date."""
        return history.diff(self.ensure(refresh=refresh), since, until)

    def conflicts(self, refresh: bool = True) -> list[dict[str, Any]]:
        eng = self.ensure(refresh=refresh)
        return [conflict_to_dict(eng, c) for c in eng.conflicts]

    def stale(self, now: date | None = None, refresh: bool = True) -> list[dict[str, Any]]:
        eng = self.ensure(refresh=refresh)
        return [hit_to_dict(h) for h in eng.stale(now)]

    def stats(self, now: date | None = None, refresh: bool = True) -> dict[str, Any]:
        eng = self.ensure(refresh=refresh)
        assert self._data is not None
        hits = [h for h in eng.stale(now)]
        size = self.index_file.stat().st_size if self.index_file.exists() else 0
        return {
            "root": str(self.root),
            "index_file": str(self.index_file),
            "index_version": self._data.version,
            "built_at": self._data.built_at,
            "files": len(self._data.docs),
            "chunks": len(eng.chunks),
            "index_bytes": size,
            "conflicts": len(eng.conflicts),
            "must_reverify": len(hits),
            "skipped_files": self._data.skipped,
        }

    # --- writes ----------------------------------------------------------

    def add(self, text: str, when: date | datetime | None = None, logfile: str = "log.md") -> str:
        path = logmod.append(self.root, text, when=when, logfile=logfile)
        self.index()
        return path.relative_to(self.root).as_posix()

    def rotate(self, keep_days: int, now: date | None = None, logfile: str = "log.md") -> dict[str, Any]:
        out = logmod.rotate(self.root, keep_days, now=now, logfile=logfile)
        self.index()
        return out


def engine_from_texts(
    texts: dict[str, str],
    dates: dict[str, float] | None = None,
    cfg: FreshnessConfig | None = None,
    rank: RankConfig | None = None,
    stem: bool = True,
) -> Engine:
    """Build an engine from in-memory Markdown, no filesystem. Used by the demo and benchmark."""
    docs: list[Document] = [parse(p, t, (dates or {}).get(p, 0.0)) for p, t in sorted(texts.items())]
    return Engine(docs, cfg, rank, stem=stem)
