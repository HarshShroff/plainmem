"""Re-run the 36 held-out adversarial cases of bench/temporal (n=1000) with write-path consolidation.

bench/temporal is imported, never edited. The corpus is generated exactly as there (seed 2026,
n=1000), copied to a temp dir, and each adversarial update line is passed through an arm before the
answers are graded with bench/temporal's own ``plainmem_system`` and ``grade``. A tag is appended to
the copied line only when the validated verdict is ``supersedes``.

To catch collateral damage, 40 noise lines from the same logs (fixed sample, seed 7) go through the
same arms; any tag on them is a false supersession. All 300 held-out temporal questions are then
re-graded on the modified copy.

These 36 cases were never used for tuning.

    python bench/supersession/temporal_rerun.py               # calls the model for prompts not in llm_cache.json
    python bench/supersession/temporal_rerun.py --cache-only
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "src"))

import run as srun  # noqa: E402  (bench/supersession/run.py: cached model and arms; import before the temporal modules)

from plainmem import consolidate as cons  # noqa: E402
from plainmem import engine_from_texts  # noqa: E402
from plainmem.text import tokenize  # noqa: E402

N, SEED, N_NOISE = 1000, 2026, 40
ARMS = ("baseline", "agent", "classifier", "agent+classifier")


def _load_temporal():  # type: ignore[no-untyped-def]
    import importlib.util

    def load(name: str, path: Path):  # type: ignore[no-untyped-def]
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    tdir = HERE.parent / "temporal"
    saved = sys.modules.get("generate")
    gen = load("generate", tdir / "generate.py")
    trun = load("temporal_run", tdir / "run.py")
    if saved is not None:
        sys.modules["generate"] = saved
    return gen, trun


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache-only", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--arms", nargs="+", default=list(ARMS), choices=ARMS)
    a = ap.parse_args()

    tgen, trun = _load_temporal()
    bench = tgen.generate(N, SEED)
    cases = [c for c in bench.cases if c.split == "heldout"]
    adv = [c for c in cases if c.category == "adversarial"]
    assert len(adv) == 36, len(adv)

    with tempfile.TemporaryDirectory() as tmp:
        tgen.write(bench, tmp, SEED)  # the copy; the committed benchmark is never touched
        notes = Path(tmp) / "notes"
        texts = {rel: (notes / rel).read_text(encoding="utf-8") for rel in bench.files}

    def line_date(path: str, ln: int) -> date:
        lines = texts[path].splitlines()[:ln]
        return date.fromisoformat(next(x[3:13] for x in reversed(lines) if x.startswith("## ")))

    targets = []  # (kind, id, path, line)
    for c in adv:
        p, ln = c.expected_cite.rsplit(":", 1)
        targets.append(("adversarial", c.id, p, int(ln)))
    noise_re = re.compile(
        "|".join(re.escape(t.split("{E}")[0]) for t in tgen.NOISE + tgen.UNRELATED if t.split("{E}")[0])
    )
    pool = [(p, n) for p in sorted(texts) if p.startswith("logs/")
            for n, x in enumerate(texts[p].splitlines(), 1)
            if x.startswith("- ") and noise_re.match(x[2:])]  # fmt: skip
    for p, n in random.Random(7).sample(pool, N_NOISE):
        targets.append(("noise", f"{p}:{n}", p, n))

    base = engine_from_texts(texts, bench.mtimes)
    model = srun.CachedModel(cache_only=a.cache_only)
    decide = srun.deciders(model)
    prompts = []
    for _, _, p, n in targets:
        note = texts[p].splitlines()[n - 1][2:]
        shown = [c.to_dict() for c in cons.candidates(base, note)]
        if shown:
            prompts += [srun.agent_prompt(note, shown), srun.classifier_prompt(note, shown)]
    if any(arm != "baseline" for arm in a.arms):
        model.prefetch(prompts)

    spans = {c.cite: trun._span(c) for c in base.chunks}
    out: dict = {"n": N, "seed": SEED, "arms": {}}
    for arm in a.arms:
        edited = dict(texts)
        lines_by = {p: edited[p].splitlines() for p in {t[2] for t in targets}}
        verdicts = []
        for kind, tid, p, n in targets:
            note = texts[p].splitlines()[n - 1][2:]
            cands = cons.candidates(base, note)
            if arm == "baseline" or not cands:
                verdicts.append({"kind": kind, "id": tid, "wrote": None, "relation": None, "failed_check": None})
                continue
            raw, who = decide[arm](note, [c.to_dict() for c in cands])
            v = cons.validate(raw, cands, eng=base, text=note, today=line_date(p, n))
            target = v["target"] if v["relation"] == "supersedes" else None
            if target:
                lines_by[p][n - 1] = "- " + cons.tag_text(note, target)
            verdicts.append({"kind": kind, "id": tid, "note": note, "wrote": target, "relation": v["relation"],
                             "failed_check": v["failed_check"], "who": who})  # fmt: skip
        for p, ls in lines_by.items():
            edited[p] = "\n".join(ls) + ("\n" if texts[p].endswith("\n") else "")
        eng = engine_from_texts(edited, bench.mtimes)
        system = trun.plainmem_system(eng)
        graded = {c.id: trun.grade(c, system(c), spans) for c in cases}
        cur = [c for c in cases if c.query_type == "current"]
        adv_out = [graded[c.id]["outcome"] for c in adv]
        right_target = {}
        for c, v in zip(adv, verdicts, strict=False):
            right_target[c.id] = bool(v["wrote"]) and set(tokenize(v["wrote"])) == set(
                tokenize(f"{c.entity} {c.attribute}")
            )
        out["arms"][arm] = {
            "adversarial_stale": adv_out.count("stale"),
            "adversarial_correct": adv_out.count("correct"),
            "adversarial_other": len(adv_out) - adv_out.count("stale") - adv_out.count("correct"),
            "adversarial_tags": sum(1 for v in verdicts if v["kind"] == "adversarial" and v["wrote"]),
            "adversarial_right_target": sum(right_target.values()),
            "noise_tags": sum(1 for v in verdicts if v["kind"] == "noise" and v["wrote"]),
            "heldout_current_acc": round(sum(graded[c.id]["right"] for c in cur) / len(cur), 3),
            "heldout_stale_rate": round(sum(graded[c.id]["stale"] for c in cur) / len(cur), 3),
            "verdicts": verdicts,
        }
    out["llm"] = {"real_calls_this_run": model.real, "cache_hits": model.hits}
    model.save()
    out["llm_calls_total_ledger"] = srun.ledger_calls()

    rows = ["| arm | stale (of 36) | correct | other | tags on the 36 | right target | tags on 40 noise lines | "
            "all held-out current_acc | all held-out stale_rate |",
            "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for arm, r in out["arms"].items():
        rows.append(f"| {srun.LABELS[arm]} | {r['adversarial_stale']} | {r['adversarial_correct']} | "
                    f"{r['adversarial_other']} | {r['adversarial_tags']} | {r['adversarial_right_target']} | "
                    f"{r['noise_tags']} | {r['heldout_current_acc']} | {r['heldout_stale_rate']} |")  # fmt: skip
    text = "\n".join(["## bench/temporal held-out adversarial cases (n=1000), before and after", "", *rows, "",
                      f"Model calls: {json.dumps(out['llm'])}", ""])  # fmt: skip
    print(text)
    for arm, r in out["arms"].items():
        for v in r["verdicts"]:
            if v["kind"] == "noise" and v["wrote"]:
                print(f"[{arm}] noise tagged: {v['note']} -> {v['wrote']}")
    if not a.no_write:
        (HERE / "results-temporal36.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
        (HERE / "results-temporal36.md").write_text(text)


if __name__ == "__main__":
    main()
