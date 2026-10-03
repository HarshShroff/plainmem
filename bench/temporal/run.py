"""Run the temporal benchmark and write bench/temporal/results.{json,md}.

    python bench/temporal/run.py                       # sizes 100 500 1000, both splits, writes results
    python bench/temporal/run.py --split dev --no-write  # dev only, print failures (what tuning may look at)

Systems (all stdlib, all answer from the same generated notes):
  bm25-raw         BM25 without stemming; the answer is the top chunk's text (reuses plainmem's BM25, stem=False)
  bm25             BM25 with stemming (plainmem mode="bm25"); answer = top chunk
  plainmem-search  plainmem's full ranker (decay + supersession demotion); answer = top chunk
  plainmem         plainmem explain: picks the fact, resolves it through the supersession chain, metadata tags
                   and as_of; answer = the reported current value (or value then), its citation and source
  plainmem+hybrid  the same explain, with candidates from BM25 + all-MiniLM-L6-v2 fused by RRF (hybrid.py).
                   Runs only when sentence-transformers is importable; otherwise recorded as skipped

The two plainmem-* rows separate "better ranking" from "lifecycle semantics": both see the same index.

Metrics (a "chunk" is one list item or paragraph; the expected chunk is the line stating the right value):
  recall@1, recall@5   expected chunk in the system's top 1 / top 5 search results (plainmem: as_of-aware search)
  current_acc          current-state questions answered with the right value
  stale_rate           current-state questions answered with a superseded value (and not the right one)
  asof_acc             "what was X on date T" answered with the value in effect on T
  provenance_acc       provenance questions: right citation, and the right source word when the line is tagged
  latency_ms           median and p95 time to answer one question (index built beforehand, not timed)
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "src"))

from generate import NOW, Case, generate  # noqa: E402

from plainmem import engine_from_texts  # noqa: E402
from plainmem.engine import Engine  # noqa: E402
from plainmem.history import explain  # noqa: E402

SEED = 2026
SIZES = (100, 500, 1000)
SYSTEMS = ("bm25-raw", "bm25", "plainmem-search", "plainmem")


@dataclass
class Answer:
    """``ranked`` is filled outside the timed part for plainmem (see ``plainmem_system``)."""

    text: str | None  # None = abstained / no answer
    cite: str | None
    source: str | None  # source word the system reports (or that is visible in the returned line)
    ranked: list[str]  # cites of the top search results, for recall


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9#]+", " ", s.lower()).strip()


def has(text: str | None, value: str) -> bool:
    return text is not None and f" {norm(value)} " in f" {norm(text)} "


def _source_in(raw: str) -> str | None:
    m = re.search(r"\{([^{}]*)\}\s*$", raw.strip())
    if not m:
        return None
    words = {w.strip() for w in m.group(1).split(",")}
    return next((s for s in ("user", "tool", "agent", "document") if s in words), None)


def chunk_system(eng: Engine, mode: str) -> Callable[[Case], Answer]:
    def run(c: Case) -> Answer:
        hits = eng.search(c.question, k=5, now=NOW, mode=mode)
        if not hits:
            return Answer(None, None, None, [])
        top = hits[0].chunk
        return Answer(top.clean_text(), top.cite, _source_in(top.text), [_span(h.chunk) for h in hits])

    return run


def _span(ch) -> str:  # type: ignore[no-untyped-def]
    return f"{ch.path}:{ch.start_line}-{ch.end_line}"


def plainmem_system(eng: Engine, search: Callable[..., list] | None = None) -> Callable[[Case], Answer]:
    find = search or eng.search

    def run(c: Case) -> Answer:
        as_of = date.fromisoformat(c.as_of) if c.as_of else None
        r = explain(eng, c.question, NOW, {}, as_of=as_of, search=search)
        f = r["fact"]
        if not f or not f.get("current"):
            return Answer(None, None, None, [])
        cur = f["current"]
        return Answer(cur["value"], cur["cite"], cur["source"], [])

    def ranked(c: Case) -> list[str]:  # recall@k uses the same as_of-aware search, untimed
        as_of = date.fromisoformat(c.as_of) if c.as_of else None
        return [_span(h.chunk) for h in find(c.question, k=5, now=NOW, as_of=as_of)]

    run.ranked = ranked  # type: ignore[attr-defined]
    return run


def in_span(span: str, cite: str) -> bool:
    path, _, rng = span.rpartition(":")
    a, b = (int(x) for x in rng.split("-"))
    cpath, _, line = cite.rpartition(":")
    return path == cpath and a <= int(line) <= b


def grade(c: Case, a: Answer, spans: dict[str, str]) -> dict[str, object]:
    r1 = any(in_span(s, c.expected_cite) for s in a.ranked[:1])
    r5 = any(in_span(s, c.expected_cite) for s in a.ranked[:5])
    right = has(a.text, c.expected)
    stale = (not right) and any(has(a.text, v) for v in c.stale_values)
    cite_ok = a.cite is not None and a.cite in spans and in_span(spans[a.cite], c.expected_cite)
    prov_ok = cite_ok and (c.expected_source is None or a.source == c.expected_source)
    if a.text is None:
        outcome = "no_answer"
    elif right:
        outcome = "correct"
    elif stale:
        outcome = "stale"
    else:
        outcome = "wrong"
    return {"r1": r1, "r5": r5, "right": right, "stale": stale, "prov": prov_ok, "outcome": outcome}


def summarize(rows: list[tuple[Case, dict[str, object], float]]) -> dict[str, object]:
    def mean(xs: list[bool]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    cur = [(c, g) for c, g, _ in rows if c.query_type == "current"]
    lat = sorted(t for _, _, t in rows)
    return {
        "n": len(rows),
        "recall@1": mean([bool(g["r1"]) for _, g, _ in rows]),
        "recall@5": mean([bool(g["r5"]) for _, g, _ in rows]),
        "current_acc": mean([bool(g["right"]) for _, g in cur]),
        "stale_rate": mean([bool(g["stale"]) for _, g in cur]),
        "asof_acc": mean([bool(g["right"]) for c, g, _ in rows if c.query_type == "as_of"]),
        "provenance_acc": mean([bool(g["prov"]) for c, g, _ in rows if c.query_type == "provenance"]),
        "latency_ms_median": round(statistics.median(lat), 2) if lat else None,
        "latency_ms_p95": round(lat[int(0.95 * (len(lat) - 1))], 2) if lat else None,
    }


def evaluate(n: int, splits: tuple[str, ...]) -> tuple[dict, list[dict]]:
    bench = generate(n, SEED)
    texts, mtimes = bench.texts(), bench.mtimes
    plain = engine_from_texts(texts, mtimes)
    raw = engine_from_texts(texts, mtimes, stem=False)
    spans = {c.cite: _span(c) for c in plain.chunks}
    systems = {
        "bm25-raw": chunk_system(raw, "bm25"),
        "bm25": chunk_system(plain, "bm25"),
        "plainmem-search": chunk_system(plain, "full"),
        "plainmem": plainmem_system(plain),
    }
    skipped: dict[str, str] = {}
    try:
        from plainmem.hybrid import Hybrid, sentence_transformer

        systems["plainmem+hybrid"] = plainmem_system(plain, Hybrid(plain, sentence_transformer()).searcher())
    except Exception as e:  # noqa: BLE001 - any failure to load the optional model means "skipped"
        skipped["plainmem+hybrid"] = f"{e.__class__.__name__}: {e}"
    cases = [c for c in bench.cases if c.split in splits]
    out: dict = {
        "cases": len(cases),
        "files": len(texts),
        "chunks": len(plain.chunks),
        "skipped": skipped,
        "systems": {},
    }
    detail: list[dict] = []
    for name, run in systems.items():
        rows = []
        for c in cases:
            t0 = time.perf_counter()
            a = run(c)
            dt = (time.perf_counter() - t0) * 1000
            if hasattr(run, "ranked"):
                a.ranked = run.ranked(c)
            g = grade(c, a, spans)
            rows.append((c, g, dt))
            detail.append(
                {
                    "size": n,
                    "system": name,
                    "id": c.id,
                    "split": c.split,
                    "category": c.category,
                    "question": c.question,
                    "as_of": c.as_of,
                    "expected": c.expected,
                    "answer": a.text,
                    "cite": a.cite,
                    **g,
                }
            )
        by_split = {s: summarize([r for r in rows if r[0].split == s]) for s in splits}
        by_cat: dict[str, dict] = {}
        for s in splits:
            groups: dict[str, list] = defaultdict(list)
            for r in rows:
                if r[0].split == s:
                    groups[r[0].category].append(r)
            by_cat[s] = {k: summarize(v) for k, v in sorted(groups.items())}
        out["systems"][name] = {"overall": by_split, "by_category": by_cat}
    return out, detail


def failures(detail: list[dict], size: int, split: str, system: str = "plainmem") -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    for d in detail:
        if d["size"] == size and d["split"] == split and d["system"] == system and d["outcome"] != "correct":
            out[d["category"]][d["outcome"] + ("" if d["r5"] else "+retrieval_miss")] += 1
    return out


def _fmt(v: object) -> str:
    return "n/a" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


COLS = ("recall@1", "recall@5", "current_acc", "stale_rate", "asof_acc", "provenance_acc", "latency_ms_median")


def table(res: dict, split: str) -> str:
    lines = ["| system | " + " | ".join(COLS) + " |", "|---|" + "---|" * len(COLS)]
    for name, s in res["systems"].items():
        o = s["overall"][split]
        lines.append(f"| {name} | " + " | ".join(_fmt(o[c]) for c in COLS) + " |")
    return "\n".join(lines)


CAT_COLS = ("n", "recall@5", "current_acc", "stale_rate", "asof_acc", "provenance_acc")


def step4(results: dict, size: str = "1000") -> tuple[str, float, float]:
    """The agreed rule on plainmem's recall@5 at the largest size. The decision is a tuning decision, so it is
    taken on the dev split; held-out is reported next to it."""
    o = results["sizes"][size]["systems"]["plainmem"]["overall"]
    return ("hybrid" if o["dev"]["recall@5"] < 0.9 else "lifecycle"), o["dev"]["recall@5"], o["heldout"]["recall@5"]


def to_markdown(results: dict, detail: list[dict]) -> str:
    sizes = list(results["sizes"])
    big = sizes[-1]
    out = [
        "# Temporal benchmark results",
        "",
        "Generated by `python bench/temporal/run.py` (seed 2026, `NOW` = " + results["now"] + "). "
        "Every number below comes from that run; `results.json` has the per-category breakdown and the "
        "held-out failure cases. The held-out split (30%, stratified by category) was frozen in "
        "`split.json` before any system was run; the two dev-split fixes are in the commit history.",
        "",
        f"## Headline: held-out split, n={big}",
    ]
    res = results["sizes"][big]
    out += [
        "",
        f"{res['systems']['plainmem']['overall']['heldout']['n']} held-out questions over "
        f"{res['files']} files / {res['chunks']} chunks.",
        "",
        table(res, "heldout"),
        "",
    ]
    for name, why in res["skipped"].items():
        out += [f"Skipped `{name}`: {why}", ""]
    branch, dev5, held5 = step4(results, big)
    out += [
        "## Step-4 rule",
        "",
        f"plainmem recall@5 at n={big}: dev {dev5:.3f}, held-out {held5:.3f}. The rule is applied on dev, "
        + (
            "which is below 0.9, so the rule says build hybrid retrieval."
            if branch == "hybrid"
            else "which is at or above 0.9, so the rule says fix lifecycle reasoning, not retrieval."
        ),
        "",
        "## Held-out, by category (n=" + big + ")",
        "",
    ]
    for sysname in ("bm25", "plainmem"):
        out += [f"**{sysname}**", "", "| category | " + " | ".join(CAT_COLS) + " |", "|---|" + "---|" * len(CAT_COLS)]
        for cat, o in res["systems"][sysname]["by_category"]["heldout"].items():
            out.append(f"| {cat} | " + " | ".join(_fmt(o[c]) for c in CAT_COLS) + " |")
        out.append("")
    out += ["## plainmem held-out failures", "", "| category | outcome | count |", "|---|---|---|"]
    for cat, cnt in sorted(failures(detail, int(big), "heldout").items()):
        for k, v in sorted(cnt.items()):
            out.append(f"| {cat} | {k} | {v} |")
    out += ["", "Examples (first three per category):", ""]
    seen: Counter = Counter()
    for d in detail:
        if (
            d["size"] == int(big)
            and d["split"] == "heldout"
            and d["system"] == "plainmem"
            and d["outcome"] != "correct"
            and seen[d["category"]] < 3
        ):
            seen[d["category"]] += 1
            when = f" (as of {d['as_of']})" if d["as_of"] else ""
            out.append(
                f"- [{d['category']}] {d['question']}{when} expected `{d['expected']}`, "
                f"got `{d['answer']}` from `{d['cite']}`; {d['outcome']}"
                + ("" if d["r5"] else ", not retrieved in top 5")
            )
    out += ["", "## All sizes", ""]
    for n in sizes:
        for s in results["splits"]:
            out += [f"n={n}, {s}:", "", table(results["sizes"][n], s), ""]
    return "\n".join(out) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    p.add_argument("--split", choices=["dev", "heldout", "both"], default="both")
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--show-failures", type=int, default=0, help="print N failing plainmem cases per category")
    args = p.parse_args()
    splits = ("dev", "heldout") if args.split == "both" else (args.split,)
    results: dict = {"seed": SEED, "now": NOW.isoformat(), "splits": list(splits), "sizes": {}}
    detail: list[dict] = []
    for n in args.sizes:
        res, det = evaluate(n, splits)
        results["sizes"][str(n)] = res
        detail += det
        for s in splits:
            print(f"\n## n={n} split={s} ({res['systems']['plainmem']['overall'][s]['n']} cases)\n")
            print(table(res, s))
            for name, why in res["skipped"].items():
                print(f"  skipped {name}: {why}")
            for cat, cnt in sorted(failures(det, n, s).items()):
                print(f"  plainmem failures {cat}: {dict(cnt)}")
            if args.show_failures:
                for d in det:
                    if d["size"] == n and d["split"] == s and d["system"] == "plainmem" and d["outcome"] != "correct":
                        print(
                            f"    [{d['category']}] {d['question']} as_of={d['as_of']} expected={d['expected']!r}"
                            f" got={d['answer']!r} ({d['cite']})"
                        )
    if not args.no_write:
        results["failures"] = {
            n: {s: {k: dict(v) for k, v in failures(detail, int(n), s).items()} for s in splits}
            for n in results["sizes"]
        }
        results["failure_examples"] = [
            d for d in detail if d["system"] == "plainmem" and d["outcome"] != "correct" and d["split"] == "heldout"
        ][:400]
        (HERE / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")
        if "heldout" in splits and "dev" in splits:
            (HERE / "results.md").write_text(to_markdown(results, detail))
        print("\nwrote bench/temporal/results.json and results.md")


if __name__ == "__main__":
    main()
