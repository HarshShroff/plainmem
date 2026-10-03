"""Combine results-heldout.* and results-temporal36.* into results.md and results.json.

python bench/supersession/run.py --split heldout --cache-only
python bench/supersession/temporal_rerun.py --cache-only
python bench/supersession/report.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

HEAD = """# Supersession benchmark results, run 2

Run 1 (seed 2026, generator labelling bug) is archived in `run1/`; see `run1/README.md`.

Reproduce (no model calls, replies come from `llm_cache.json`):

```bash
python bench/supersession/run.py --split heldout --cache-only
python bench/supersession/temporal_rerun.py --cache-only
python bench/supersession/report.py
```

Held-out split, 90 of 300 cases (31 with reserved wording), seed 4127, ids t0001..t0300, frozen in
`split_v2.json` before any model call, run once after dev tuning (`dev-rounds-v2.md`).
Arm B is a simulated writing agent (one model call that sees the skill file, the note and the
`candidates` output), not a measurement of a real agent. All model calls: `claude -p --model haiku`.
Pre-registered bar (README.md): implicit stale at most half of arm A's, and false supersession at most
1% of unrelated + ambiguous notes (here 0 of 38).
"""


def main() -> None:
    held = json.loads((HERE / "results-heldout.json").read_text())
    temporal = json.loads((HERE / "results-temporal36.json").read_text())
    calls = sum(1 for _ in (HERE / "llm_calls.jsonl").open())
    base = held["arms"]["baseline"]["overall"]["implicit_stale"]
    verdict = []
    for arm, r in held["arms"].items():
        if arm == "baseline":
            continue
        o = r["overall"]
        ok = o["implicit_stale"] is not None and o["implicit_stale"] <= base / 2 and o["false_supersession"] <= 0.01
        verdict.append(f"- {r['label']}: implicit stale {base} -> {o['implicit_stale']}, false supersession "
                       f"{o['false_supersession']} ({o['false_tags']} tags): "
                       f"**{'pass' if ok else 'fail'}**")  # fmt: skip
    md = [HEAD, "## Pre-registered criterion, held-out", "", *verdict, "",
          (HERE / "results-heldout.md").read_text().strip(), "",
          (HERE / "results-temporal36.md").read_text().strip(), "",
          f"Model calls over the whole experiment (run 2: dev rounds, held-out, temporal): {calls} "
          "(`llm_calls.jsonl`).", ""]  # fmt: skip
    (HERE / "results.md").write_text("\n".join(md))
    out = {"heldout": held, "temporal36": temporal, "llm_calls_total": calls}
    (HERE / "results.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    print("\n".join(verdict))


if __name__ == "__main__":
    main()
