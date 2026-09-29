"""Run the retrieval benchmark on the synthetic corpus and print a Markdown table.

    python bench/run.py                 # writes bench/results.json and bench/results.md
    python bench/run.py --no-embed      # skip the embedding baseline

Systems:
  grep        count of distinct query words present in the chunk (case-insensitive substring), stopwords removed
  bm25-raw    BM25, no stemming
  bm25        BM25 with Porter stemming (plainmem mode="bm25")
  plainmem    BM25 + stemming + time decay + supersession (plainmem mode="full")
  embed       sentence-transformers all-MiniLM-L6-v2 cosine similarity, if installed
  embed+layer the embedding top 50, re-ranked by plainmem's freshness and supersession layer
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from synth import NOW, Corpus, Query, generate, write  # noqa: E402

from plainmem import Memory  # noqa: E402
from plainmem.engine import Engine  # noqa: E402
from plainmem.text import STOPWORDS, tokenize, words  # noqa: E402

K = 10


@dataclass
class Ranked:
    path: str
    start: int
    end: int
    flagged: bool | None  # None = system has no notion of freshness


def contains(r: Ranked, path: str, line: int) -> bool:
    return r.path == path and r.start <= line <= r.end


def grep_system(engine: Engine) -> Callable[[str], list[Ranked]]:
    texts = [c.clean_text().lower() for c in engine.chunks]

    def run(query: str) -> list[Ranked]:
        terms = [t for t in dict.fromkeys(words(query)) if t not in STOPWORDS]
        scored = []
        for i, t in enumerate(texts):
            s = sum(1 for term in terms if term in t)
            if s:
                scored.append((-s, i))
        scored.sort()
        return [
            Ranked(engine.chunks[i].path, engine.chunks[i].start_line, engine.chunks[i].end_line, None)
            for _, i in scored[:K]
        ]

    return run


def engine_system(engine: Engine, mode: str) -> Callable[[str], list[Ranked]]:
    def run(query: str) -> list[Ranked]:
        hits = engine.search(query, k=K, now=NOW, mode=mode)
        return [
            Ranked(h.chunk.path, h.chunk.start_line, h.chunk.end_line, h.must_reverify if mode == "full" else None)
            for h in hits
        ]

    return run


def embed_system(engine: Engine) -> tuple[dict[str, Callable[[str], list[Ranked]]], dict]:
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except Exception as e:  # noqa: BLE001 - any import failure means "not available"
        return {}, {"skipped": f"sentence-transformers not importable: {e.__class__.__name__}: {e}"}
    try:
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    except Exception as e:  # noqa: BLE001
        return {}, {"skipped": f"model load failed: {e.__class__.__name__}: {e}"}
    docs = [" > ".join(c.heading_path) + ": " + c.clean_text() for c in engine.chunks]
    t0 = time.perf_counter()
    mat = model.encode(docs, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    build = time.perf_counter() - t0

    def run(query: str) -> list[Ranked]:
        qv = model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
        sims = mat @ qv
        top = np.argsort(-sims)[:K]
        return [
            Ranked(engine.chunks[i].path, engine.chunks[i].start_line, engine.chunks[i].end_line, None) for i in top
        ]

    def run_layered(query: str) -> list[Ranked]:
        qv = model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
        sims = mat @ qv
        top = np.argsort(-sims)[:50]
        raw = {int(i): float(max(sims[i], 0.0)) for i in top}
        hits = engine.rerank(raw, set(tokenize(query)), K, NOW)
        return [Ranked(h.chunk.path, h.chunk.start_line, h.chunk.end_line, h.must_reverify) for h in hits]

    return {"embed": run, "embed+layer": run_layered}, {
        "build_s": build,
        "bytes": int(mat.nbytes),
        "model": "all-MiniLM-L6-v2",
    }


def evaluate(run: Callable[[str], list[Ranked]], queries: list[Query]) -> dict:
    per_type: dict[str, dict[str, list[float]]] = {}
    lat: list[float] = []
    stale_answer: list[float] = []
    false_fresh: list[float] = []
    over_flag: list[float] = []
    for q in queries:
        t0 = time.perf_counter()
        ranked = run(q.query)
        lat.append((time.perf_counter() - t0) * 1000)
        rank = next((i + 1 for i, r in enumerate(ranked) if contains(r, q.path, q.line)), None)
        m = per_type.setdefault(q.qtype, {"r1": [], "r5": [], "mrr": []})
        m["r1"].append(1.0 if rank == 1 else 0.0)
        m["r5"].append(1.0 if rank and rank <= 5 else 0.0)
        m["mrr"].append(1.0 / rank if rank else 0.0)
        if q.qtype == "superseded":
            stale_answer.append(1.0 if ranked and contains(ranked[0], q.old_path, q.old_line) else 0.0)
        if q.qtype == "stale":
            hit = next((r for r in ranked[:5] if contains(r, q.path, q.line)), None)
            if q.expect_flag:
                false_fresh.append(1.0 if hit is not None and not hit.flagged else 0.0)
            else:
                over_flag.append(1.0 if hit is not None and hit.flagged else 0.0)
    allm = {"r1": [], "r5": [], "mrr": []}
    for m in per_type.values():
        for key in allm:
            allm[key].extend(m[key])
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None  # noqa: E731
    lat.sort()
    return {
        "overall": {k: mean(v) for k, v in allm.items()},
        "by_type": {t: {k: mean(v) for k, v in m.items()} for t, m in sorted(per_type.items())},
        "stale_answer_rate": mean(stale_answer),
        "false_fresh_rate": mean(false_fresh),
        "over_flag_rate": mean(over_flag),
        "latency_ms_p50": round(statistics.median(lat), 3),
        "latency_ms_p99": round(lat[min(len(lat) - 1, int(len(lat) * 0.99))], 3),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    corpus: Corpus = generate(a.seed)
    queries = corpus.queries
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        write(corpus, root)
        mem = Memory(root)
        t0 = time.perf_counter()
        st = mem.index(rebuild=True)
        build_s = time.perf_counter() - t0
        engine = mem.engine
        t0 = time.perf_counter()
        Memory(root).load()
        load_s = time.perf_counter() - t0
    raw_engine = Engine(engine.docs, stem=False)

    info = {
        "seed": a.seed,
        "now": NOW.isoformat(),
        "files": st["files"],
        "chunks": st["chunks"],
        "queries": len(queries),
        "queries_by_type": {t: sum(1 for q in queries if q.qtype == t) for t in sorted({q.qtype for q in queries})},
        "stale_flag_expected": sum(1 for q in queries if q.qtype == "stale" and q.expect_flag),
        "index_build_s": round(build_s, 3),
        "index_load_s": round(load_s, 3),
        "index_bytes": st["bytes"],
        "conflicts_detected": len(engine.conflicts),
    }
    systems: dict[str, Callable[[str], list[Ranked]]] = {
        "grep": grep_system(engine),
        "bm25-raw": engine_system(raw_engine, "bm25"),
        "bm25": engine_system(engine, "bm25"),
        "plainmem": engine_system(engine, "full"),
    }
    if not a.no_embed:
        extra, emb = embed_system(engine)
        info["embed"] = emb
        systems.update(extra)
    else:
        info["embed"] = {"skipped": "--no-embed"}

    results = {name: evaluate(run, queries) for name, run in systems.items()}
    out = {"info": info, "results": results}
    (HERE / "results.json").write_text(json.dumps(out, indent=2) + "\n")
    md = to_markdown(out)
    (HERE / "results.md").write_text(md)
    print(md)


def to_markdown(out: dict) -> str:
    info, res = out["info"], out["results"]
    f = lambda v: "n/a" if v is None else f"{v:.3f}"  # noqa: E731
    lines = [
        f"Corpus: {info['files']} files, {info['chunks']} chunks, {info['queries']} queries "
        f"{info['queries_by_type']}, reference date {info['now']}, seed {info['seed']}.",
        "",
        "| system | R@1 | R@5 | MRR | stale-answer rate | false-fresh rate | over-flag rate | p50 ms | p99 ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, r in res.items():
        o = r["overall"]
        lines.append(
            f"| {name} | {f(o['r1'])} | {f(o['r5'])} | {f(o['mrr'])} | {f(r['stale_answer_rate'])} | "
            f"{f(r['false_fresh_rate'])} | {f(r['over_flag_rate'])} | {r['latency_ms_p50']:.2f} | "
            f"{r['latency_ms_p99']:.2f} |"
        )
    lines += [
        "",
        "Recall@1 by query type:",
        "",
        "| system | " + " | ".join(sorted(next(iter(res.values()))["by_type"])) + " |",
        "|---|" + "---|" * len(next(iter(res.values()))["by_type"]),
    ]
    for name, r in res.items():
        lines.append(f"| {name} | " + " | ".join(f(r["by_type"][t]["r1"]) for t in sorted(r["by_type"])) + " |")
    lines += [
        "",
        f"plainmem index: build {info['index_build_s']}s, load {info['index_load_s']}s, "
        f"{info['index_bytes'] / 1024:.0f} KiB on disk; {info['conflicts_detected']} conflicting keys detected.",
    ]
    e = info.get("embed", {})
    if "skipped" in e:
        lines.append(f"Embedding baseline skipped: {e['skipped']}")
    else:
        lines.append(
            f"Embedding baseline ({e['model']}): encode {e['build_s']:.1f}s on CPU, "
            f"{e['bytes'] / 1024:.0f} KiB of vectors in memory."
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
