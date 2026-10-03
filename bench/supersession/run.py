"""Run the supersession benchmark and write bench/supersession/results.{json,md}.

    python bench/supersession/run.py --split dev --no-write --show-failures 5   # what tuning may look at
    python bench/supersession/run.py --split heldout                           # the reported run (once)
    python bench/supersession/run.py --split heldout --cache-only              # reproduce from llm_cache.json

Arms. Each one writes the same notes, in date order, into a fresh copy of the generated corpus:

  A baseline          plain ``Memory.add``: current plainmem, no consolidation
  B agent             SIMULATED writing agent (``agent_sim.py``): sees the skill file, the note and the
                      ``candidates`` output, and passes ``supersedes`` or nothing
  C classifier        the constrained JSON classifier (``consolidate_llm.LLMClassifier``) alone
  D agent+classifier  B first; C only when the agent passed nothing

B, C and D all go through the same validator (``consolidate.validate``) before a tag is written. All
model calls are ``claude -p --model haiku``. Only the notes of cases in the chosen split are
consolidated; the other split's notes and the noise notes are written with plain ``add`` (they are
about other entities).

Model replies are cached in ``llm_cache.json`` by prompt hash, so a re-run with unchanged prompts
makes no calls and gives the same verdicts; ``llm_calls.jsonl`` logs every real call.

Metrics (gold "supersedes" = categories A-D, negatives = E-G):
  precision           tags written with the right target / tags written
  recall              A-D notes tagged with the right target / A-D notes
  false_supersession  E-G notes that got any tag / E-G notes   (pre-registered bar: <= 0.01)
  abstention_rate     verdicts of "insufficient" / all notes
  stale_rate          A-D questions answered from the old line; implicit_stale: the same on B-D only
  current_acc         A-F questions whose answer cites the right line (the note for A-D, the original
                      fact for E-F)
  g_abstained         G questions (attribute never recorded) where explain reports no current value
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import shutil
import statistics
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "src"))

from agent_sim import SimulatedAgent  # noqa: E402
from agent_sim import build_prompt as agent_prompt  # noqa: E402
from generate import NAMES, NOW, Case, cases_sha, generate  # noqa: E402

from plainmem import Memory  # noqa: E402
from plainmem import consolidate as cons  # noqa: E402
from plainmem.consolidate_llm import LLMClassifier, claude_cli  # noqa: E402
from plainmem.consolidate_llm import build_prompt as classifier_prompt  # noqa: E402
from plainmem.text import tokenize  # noqa: E402

SEED = 2026
N_CASES = 300
ARMS = ("baseline", "agent", "classifier", "agent+classifier")
LABELS = {"baseline": "A current plainmem", "agent": "B agent-declared (simulated)",
          "classifier": "C classifier", "agent+classifier": "D agent, then classifier"}  # fmt: skip
CACHE = HERE / "llm_cache.json"
LEDGER = HERE / "llm_calls.jsonl"


class CachedModel:
    """``complete(prompt)`` with a prompt-hash cache; counts real calls."""

    def __init__(self, cache_only: bool = False, model: str = "haiku") -> None:
        self.cache: dict[str, str] = json.loads(CACHE.read_text()) if CACHE.exists() else {}
        self.model = model
        self.live = None if cache_only else claude_cli(model)
        self.real = 0
        self.hits = 0
        self.seconds: list[float] = []

    @staticmethod
    def key(prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def __call__(self, prompt: str) -> str:
        k = self.key(prompt)
        if k in self.cache:
            self.hits += 1
            return self.cache[k]
        if self.live is None:
            raise RuntimeError("not in llm_cache.json and --cache-only is set")
        t = time.perf_counter()
        reply = self.live(prompt)
        self.seconds.append(time.perf_counter() - t)
        self.real += 1
        self.cache[k] = reply
        with LEDGER.open("a") as f:
            f.write(json.dumps({"key": k, "model": self.model, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        return reply

    def prefetch(self, prompts: list[str], workers: int = 8) -> None:
        todo = sorted({p for p in prompts if self.key(p) not in self.cache})
        if todo and self.live is not None:
            with ThreadPoolExecutor(workers) as ex:
                list(ex.map(self._safe, todo))
        self.hits = 0  # count hits from the real pass only

    def _safe(self, prompt: str) -> None:
        with contextlib.suppress(Exception):  # retried in the real pass, where a second failure is counted
            self(prompt)

    def save(self) -> None:
        if self.real:
            CACHE.write_text(json.dumps(self.cache, indent=0, sort_keys=True) + "\n")


def _canon(key: str | None) -> frozenset[str]:
    return frozenset(tokenize(key or ""))


def deciders(model: CachedModel | None):  # type: ignore[no-untyped-def]
    """arm -> decide(note, shown) -> (raw verdict, who decided)."""
    if model is None:
        return {}
    agent, clf = SimulatedAgent(model), LLMClassifier(model)

    def both(note, shown):  # type: ignore[no-untyped-def]
        raw = agent(note, shown)
        return (raw, "agent") if raw.get("declared") else (clf(note, shown), "classifier")

    return {
        "agent": lambda note, shown: (agent(note, shown), "agent"),
        "classifier": lambda note, shown: (clf(note, shown), "classifier"),
        "agent+classifier": both,
        "_counters": (agent, clf),
    }


def play(arm, files, cases, noise, split, decide, workdir: Path):  # type: ignore[no-untyped-def]
    """Write every note in date order through the arm. Returns (memory, records by case id, judge ms)."""
    root = workdir / arm
    if root.exists():
        shutil.rmtree(root)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    mem = Memory(root, index_dir=workdir / f"{arm}-index")
    mem.index(rebuild=True)
    events = [(c.note_date, 0, c.id, c) for c in cases] + [(d, 1, f"n{i:04d}", t) for i, (d, t) in enumerate(noise)]
    events.sort(key=lambda e: e[:3])
    out: dict[str, dict] = {}
    cand_ms: list[float] = []
    for d, kind, _, item in events:
        when = date.fromisoformat(d)
        if kind == 1 or decide is None or item.split != split:
            mem.add(item if kind == 1 else item.note, when=when)
            continue
        eng = mem.engine
        t = time.perf_counter()
        cands = cons.candidates(eng, item.note)
        cand_ms.append((time.perf_counter() - t) * 1000)
        shown = [c.to_dict() for c in cands]
        if not cands:
            raw, who = None, "none"
            v = {"relation": "unrelated", "target": None, "valid": True, "failed_check": None, "reason": "",
                 "note": "no candidates"}  # fmt: skip
        else:
            raw, who = decide(item.note, shown)
            v = cons.validate(raw, cands, eng=eng, text=item.note, today=when)
        target = v["target"] if v["relation"] == "supersedes" else None
        mem.add(item.note, when=when, supersedes=target)
        out[item.id] = {"relation": v["relation"], "target": v["target"], "wrote": target, "who": who,
                        "failed_check": v["failed_check"], "raw": raw, "reason": v["reason"],
                        "n_candidates": len(cands),
                        "gold_in_candidates": any(_canon(c.key) == _canon(item.gold_target)
                                                  for c in cands)}  # fmt: skip
    return mem, out, cand_ms


def note_cites(mem: Memory, cases: list[Case]) -> dict[str, str]:
    lines = (mem.root / "log.md").read_text(encoding="utf-8").splitlines()
    want = {"- " + c.note: c.id for c in cases}
    where: dict[str, str] = {}
    for n, ln in enumerate(lines, start=1):
        for prefix, cid in want.items():
            if cid not in where and ln.startswith(prefix):
                where[cid] = f"log.md:{n}"
    return where


def evaluate(mem: Memory, cases: list[Case], records: dict[str, dict]) -> list[dict]:
    cites = note_cites(mem, cases)
    rows = []
    for c in cases:
        r = mem.explain(c.question, now=NOW, refresh=False)
        f = r.get("fact")
        cur = f.get("current") if f else None
        cite = cur["cite"] if cur else None
        v = records.get(c.id, {"relation": None, "target": None, "wrote": None, "failed_check": None})
        right_target = v["wrote"] is not None and _canon(v["wrote"]) == _canon(c.gold_target)
        if c.expect == "abstain":
            outcome = (
                "abstained" if cur is None else ("answered_with_note" if cite == cites[c.id] else "answered_other")
            )
        elif cite is None:
            outcome = "no_answer"
        elif cite == (cites[c.id] if c.expect == "new" else c.base_cite):
            outcome = "correct"
        elif c.expect == "new" and cite == c.base_cite:
            outcome = "stale"
        elif c.expect == "old" and cite == cites[c.id]:
            outcome = "overridden"
        else:
            outcome = "wrong"
        rows.append({"id": c.id, "category": c.category, "wording": c.wording, "gold": c.gold,
                     "relation": v["relation"], "wrote": v["wrote"], "right_target": right_target,
                     "failed_check": v.get("failed_check"), "who": v.get("who"), "outcome": outcome,
                     "answer": cur["value"] if cur else None, "cite": cite, "note": c.note,
                     "question": c.question, "gold_target": c.gold_target, "record": v})  # fmt: skip
    return rows


def _rate(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def metrics(rows: list[dict]) -> dict:
    pos = [r for r in rows if r["gold"] == "supersedes"]
    neg = [r for r in rows if r["gold"] != "supersedes"]
    implicit = [r for r in pos if r["category"] in "BCD"]
    wrote = [r for r in rows if r["wrote"]]
    g = [r for r in rows if r["category"] == "G"]
    cur = [r for r in rows if r["category"] != "G"]
    judged = [r for r in rows if r["relation"] is not None]
    return {
        "n": len(rows),
        "tags_written": len(wrote),
        "precision": _rate(len([r for r in wrote if r["right_target"]]), len(wrote)),
        "recall": _rate(len([r for r in pos if r["right_target"]]), len(pos)),
        "false_supersession": _rate(len([r for r in neg if r["wrote"]]), len(neg)),
        "false_tags": len([r for r in neg if r["wrote"]]),
        "wrong_target": len([r for r in pos if r["wrote"] and not r["right_target"]]),
        "abstention_rate": _rate(len([r for r in judged if r["relation"] == "insufficient"]), len(judged)),
        "stale_rate": _rate(len([r for r in pos if r["outcome"] == "stale"]), len(pos)),
        "implicit_stale": _rate(len([r for r in implicit if r["outcome"] == "stale"]), len(implicit)),
        "current_acc": _rate(len([r for r in cur if r["outcome"] == "correct"]), len(cur)),
        "g_abstained": _rate(len([r for r in g if r["outcome"] == "abstained"]), len(g)),
        "g_answered_with_note": len([r for r in g if r["outcome"] == "answered_with_note"]),
        "overridden": len([r for r in cur if r["outcome"] == "overridden"]),
    }


def two_by_two(rows: list[dict]) -> dict:
    """True supersessions: detected / wrong target / abstained (insufficient) / rejected (other, no tag).
    Unrelated + ambiguous: rejected (no tag, not insufficient) / abstained (insufficient) / falsely tagged."""
    pos = [r for r in rows if r["gold"] == "supersedes"]
    neg = [r for r in rows if r["gold"] != "supersedes"]
    return {
        "supersession": {
            "detected": sum(r["right_target"] for r in pos),
            "wrong_target": sum(bool(r["wrote"]) and not r["right_target"] for r in pos),
            "abstained": sum(not r["wrote"] and r["relation"] == "insufficient" for r in pos),
            "rejected": sum(not r["wrote"] and r["relation"] != "insufficient" for r in pos),
        },
        "unrelated_or_ambiguous": {
            "rejected": sum(not r["wrote"] and r["relation"] != "insufficient" for r in neg),
            "abstained": sum(not r["wrote"] and r["relation"] == "insufficient" for r in neg),
            "falsely_tagged": sum(bool(r["wrote"]) for r in neg),
        },
    }


def by(rows: list[dict], field: str) -> dict[str, dict]:
    return {k: metrics([r for r in rows if r[field] == k]) for k in sorted({r[field] for r in rows})}


def run(split: str, arms: list[str], cache_only: bool, workdir: Path) -> dict:
    files, cases, noise = generate(N_CASES, SEED)
    frozen = json.loads((HERE / "split.json").read_text())
    assert frozen["cases_sha256"] == cases_sha(cases), "generated cases differ from the frozen split"
    assert sorted(c.id for c in cases if c.split == "heldout") == frozen["heldout"]
    scoped = [c for c in cases if c.split == split]
    out: dict = {"split": split, "seed": SEED, "n_cases": N_CASES, "n": len(scoped), "arms": {}}
    model = CachedModel(cache_only=cache_only) if any(a != "baseline" for a in arms) else None
    decide = deciders(model)
    if model is not None:
        # one recording pass collects the prompts the real passes will send, so they can be fetched in parallel
        prompts: list[str] = []

        def record(note, shown):  # type: ignore[no-untyped-def]
            prompts.extend([agent_prompt(note, shown), classifier_prompt(note, shown)])
            return {"relation": "unrelated"}, "record"

        play("record", files, cases, noise, split, record, workdir)
        model.prefetch(prompts)
    for arm in arms:
        t = time.perf_counter()
        mem, records, cand_ms = play(arm, files, cases, noise, split, decide.get(arm), workdir)
        rows = evaluate(mem, scoped, records)
        out["arms"][arm] = {
            "label": LABELS[arm],
            "overall": metrics(rows),
            "two_by_two": two_by_two(rows),
            "by_category": by(rows, "category"),
            "by_wording": by(rows, "wording"),
            "relations": dict(Counter(f"{r['gold']} -> {r['relation']}" for r in rows)),
            "outcomes": dict(Counter(f"{r['category']}:{r['outcome']}" for r in rows)),
            "failed_checks": dict(Counter(r["failed_check"] for r in rows if r["failed_check"])),
            "decided_by": dict(Counter(r["who"] for r in rows if r["who"])),
            "gold_in_candidates": _rate(
                sum(1 for r in rows if r["record"].get("gold_in_candidates")),
                sum(1 for r in rows if r["gold"] == "supersedes"),
            ),  # fmt: skip
            "candidates_ms_median": round(statistics.median(cand_ms), 2) if cand_ms else None,
            "seconds": round(time.perf_counter() - t, 1),
            "failures": [r for r in rows if not _ok(r)],
        }
    if model is not None:
        agent, clf = decide["_counters"]
        out["llm"] = {"model": model.model, "real_calls_this_run": model.real, "cache_hits": model.hits,
                      "agent_parse_failures": agent.failures, "classifier_parse_failures": clf.failures,
                      "seconds_per_call_median": round(statistics.median(model.seconds), 2)
                      if model.seconds else None}  # fmt: skip
        model.save()
    return out


def _ok(r: dict) -> bool:
    if r["gold"] == "supersedes":
        return r["right_target"] and r["outcome"] == "correct"
    return not r["wrote"] and r["outcome"] in ("correct", "abstained")


def ledger_calls() -> int:
    return sum(1 for _ in LEDGER.open()) if LEDGER.exists() else 0


COLS = ["precision", "recall", "false_supersession", "abstention_rate", "stale_rate", "implicit_stale",
        "current_acc", "g_abstained", "tags_written", "wrong_target"]  # fmt: skip


def _fmt(x: object) -> str:
    return "n/a" if x is None else str(x)


def render(res: dict) -> str:
    out = [f"## Split: {res['split']} ({res['n']} cases)", "",
           "| arm | " + " | ".join(COLS) + " |", "|---" * (len(COLS) + 1) + "|"]  # fmt: skip
    for r in res["arms"].values():
        out.append(f"| {r['label']} | " + " | ".join(_fmt(r["overall"][c]) for c in COLS) + " |")
    out += ["", "Abstention 2x2 (true supersessions: detected / wrong target / abstained / rejected; "
            "unrelated+ambiguous: rejected / abstained / falsely tagged):", "",
            "| arm | detected | wrong target | abstained | rejected | | rejected | abstained | falsely tagged |",
            "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in res["arms"].values():
        s, u = r["two_by_two"]["supersession"], r["two_by_two"]["unrelated_or_ambiguous"]
        out.append(f"| {r['label']} | {s['detected']} | {s['wrong_target']} | {s['abstained']} | {s['rejected']} "
                   f"| | {u['rejected']} | {u['abstained']} | {u['falsely_tagged']} |")  # fmt: skip
    out.append("")
    for arm, r in res["arms"].items():
        out += [
            f"**{r['label']}**, by category",
            "",
            "| category | n | tags | right target | current_acc | stale | outcomes |",
            "|---|---|---|---|---|---|---|",
        ]
        for cat, m in r["by_category"].items():
            oc = ", ".join(f"{k.split(':')[1]} {v}" for k, v in sorted(r["outcomes"].items()) if k[0] == cat)
            right = "n/a" if cat in "EFG" else m["recall"]
            out.append(f"| {cat} {NAMES[cat]} | {m['n']} | {m['tags_written']} | {right} | {_fmt(m['current_acc'])} "
                       f"| {_fmt(m['stale_rate'])} | {oc} |")  # fmt: skip
        out.append("")
        if arm != "baseline":
            if r["by_wording"].keys() >= {"seen", "reserved"}:
                out.append("By wording: " + "; ".join(
                    f"{w} (n={m['n']}): precision {_fmt(m['precision'])}, recall {_fmt(m['recall'])}, "
                    f"false supersession {_fmt(m['false_supersession'])}"
                    for w, m in r["by_wording"].items()))  # fmt: skip
            out.append(
                "Verdicts (gold -> validated): " + ", ".join(f"{k} {v}" for k, v in sorted(r["relations"].items()))
            )
            out.append(f"Failed validator checks: {r['failed_checks'] or 'none'}; decided by: {r['decided_by']}; "
                       f"gold key among candidates: {r['gold_in_candidates']}")  # fmt: skip
            out.append("")
    if "llm" in res:
        out += [f"Model calls: {json.dumps(res['llm'])}", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--split", choices=["dev", "heldout"], default="heldout")
    ap.add_argument("--arms", nargs="+", default=list(ARMS), choices=ARMS)
    ap.add_argument("--cache-only", action="store_true", help="never call the model; use llm_cache.json")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--show-failures", type=int, default=0)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        res = run(a.split, a.arms, a.cache_only, Path(tmp))
    res["llm_calls_total_ledger"] = ledger_calls()
    text = render(res)
    print(text)
    for arm, r in res["arms"].items():
        for f in r["failures"][: a.show_failures]:
            print(f"[{arm}] {f['category']} {f['outcome']} wrote={f['wrote']!r} rel={f['relation']} "
                  f"check={f['failed_check']} | {f['note']} | gold={f['gold_target']!r} | "
                  f"raw={f['record'].get('raw')}")  # fmt: skip
    if not a.no_write:
        (HERE / f"results-{a.split}.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
        (HERE / f"results-{a.split}.md").write_text(text + "\n")


if __name__ == "__main__":
    main()
