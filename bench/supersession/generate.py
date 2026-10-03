"""Generate the supersession benchmark: one base fact per case, one later note, one question.

Each case owns one entity. Its file (``projects/<name>.md``) lists 4 to 6 facts, including the asked
attribute (except in category G) and at least one other attribute of the same kind, so the right
target is never the only plausible one. Later notes are written to ``log.md`` by the runner, in date
order, through whichever consolidation arm is being measured.

Categories (gold verdict in brackets):

  A explicit        [supersedes]    "Dana is no longer the Orion project lead. Sam is."
  B direct          [supersedes]    "Sam took over from Dana on Orion."            (names the old value)
  C indirect        [supersedes]    "Sam took over Orion."                         (no old value)
  D event           [supersedes]    "Orion changed hands after Dana left; Sam runs it now."
  E similar         [unrelated]     "Sam joined the Orion team."                   (must not supersede)
  F ambiguous       [insufficient]  "Sam has been running Orion lately."           (must not supersede)
  G abstain         [unrelated]     like E, but the asked attribute was never recorded:
                                    the right answer is that there is no evidence of a current value

Split rule (frozen before any system runs): case ids of each category are shuffled with
``random.Random(seed + 1)`` and 30% are held out. Wording: each (attribute, category) has several
templates; the last one is reserved for held-out cases, which draw from all of them, so part of the
held-out set uses wording nobody tuned on. ``wording`` on each case says which.

    python bench/supersession/generate.py --cases 300 --seed 2026 --out /tmp/supersession
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from synth import FIRST, LAST, PROJECTS  # noqa: E402

NOW = date(2026, 10, 1)
SPLIT_SEED_OFFSET = 1
HELDOUT_FRACTION = 0.30
MIX = {"A": 12, "B": 16, "C": 16, "D": 14, "E": 16, "F": 14, "G": 12}
GOLD = {"A": "supersedes", "B": "supersedes", "C": "supersedes", "D": "supersedes",
        "E": "unrelated", "F": "insufficient", "G": "unrelated"}  # fmt: skip
NAMES = {"A": "explicit", "B": "direct implicit", "C": "indirect implicit", "D": "event-based",
         "E": "unrelated but similar", "F": "ambiguous", "G": "abstention"}  # fmt: skip

SUFFIXES = ["Ridge", "Forge", "Works", "Labs", "Gate", "Hub", "Bay", "Peak", "Field", "Point", "Stack", "Yard"]
REGIONS = ["us-east-1", "us-east-2", "us-west-2", "eu-west-1", "eu-west-2", "eu-central-1", "ap-south-1",
           "ap-southeast-2", "ca-central-1", "sa-east-1"]  # fmt: skip
DBS = ["Postgres 16", "MySQL 8", "MariaDB 10", "CockroachDB", "ScyllaDB", "MongoDB 7", "DynamoDB", "ClickHouse"]
CIS = ["GitHub Actions", "CircleCI", "Buildkite", "Jenkins", "GitLab CI", "TeamCity", "Azure Pipelines"]
CO_A = ["Northwind", "Brightwater", "Calloway", "Dunmere", "Ellison", "Fairhaven", "Hollis", "Kellmark"]
CO_B = ["Freight", "Systems", "Logistics", "Partners", "Networks", "Industries"]

# attribute -> kind; the first eight are asked about, the rest are distractor facts only
KINDS = {
    "project lead": "person", "on-call engineer": "person", "budget owner": "person", "design reviewer": "person",
    "deploy region": "region", "primary database": "db", "CI provider": "ci", "vendor": "company",
    "staging lead": "person", "budget ceiling": "amount", "release date": "date", "team size": "num",
    "backup region": "region", "replica database": "db", "CD provider": "ci", "backup vendor": "company",
}  # fmt: skip
ASKED = list(KINDS)[:8]

# Per asked attribute and category: templates; the LAST one is reserved for held-out cases.
# {E} entity, {old} value on file, {new} value in the note.
T: dict[str, dict[str, list[str]]] = {
    "project lead": {
        "B": ["{new} took over from {old} on {E}.", "{old} handed {E} over to {new}.",
              "{new} replaced {old} at the helm of {E}."],
        "C": ["{new} took over {E}.", "{new} is running {E} from now on.", "{E} answers to {new} these days."],
        "D": ["{E} changed hands after {old} left; {new} runs it now.",
              "After the reorg {old} moved to another org and {new} owns {E}.",
              "{old} went on long leave in March, so {new} has been in charge of {E} since."],
        "E": ["{new} joined the {E} team.", "{new} reviewed the {E} roadmap.", "{new} gave a talk about {E}."],
        "F": ["{new} has been running {E} lately.", "{new} might take over {E}.",
              "{new} sat in for {old} at a couple of {E} meetings."],
    },
    "on-call engineer": {
        "B": ["{new} took the pager from {old} for {E}.", "{old} passed the {E} pager to {new}.",
              "{new} relieved {old} of {E} on-call duty."],
        "C": ["{new} carries the {E} pager now.", "{E} pages go to {new} from now on.",
              "{new} is who gets woken up when {E} breaks."],
        "D": ["After {old} rotated off, {E} pages go to {new}.",
              "{old} burned out on nights; {new} owns the {E} pager now.",
              "The {E} rotation was rebuilt after {old} left and {new} holds it."],
        "E": ["{new} fixed a flaky {E} alert.", "{new} wrote the {E} runbook.", "{new} shadowed an {E} incident."],
        "F": ["{new} might be covering {E} pages this week.", "{new} has picked up a few {E} pages.",
              "{new} may end up holding the {E} pager."],
    },
    "budget owner": {
        "B": ["{new} replaced {old} as the one who signs off on {E} spend.",
              "{old} handed {E} spend approval to {new}.", "Spend sign-off for {E} moved from {old} to {new}."],
        "C": ["{new} signs off on {E} spend now.", "{E} purchases need {new}'s approval from now on.",
              "{new} holds the purse strings for {E}."],
        "D": ["Finance reshuffled after {old} moved teams; {E} spend approvals sit with {new}.",
              "{old} left the company, so {new} approves {E} purchases.",
              "With {old} out, every {E} invoice lands on {new}'s desk."],
        "E": ["{new} reviewed the {E} budget.", "{new} asked about {E} costs.", "{new} filed an {E} expense report."],
        "F": ["{new} has been looking at {E} spend lately.", "{new} may take over {E} approvals.",
              "{new} co-signed one {E} invoice."],
    },
    "design reviewer": {
        "B": ["{new} took over mockup reviews from {old} on {E}.", "{old} passed {E} design reviews to {new}.",
              "{new} replaced {old} as the {E} design gatekeeper."],
        "C": ["{new} reviews all {E} mockups now.", "{E} mockups go through {new} from now on.",
              "Every {E} screen needs {new}'s sign-off."],
        "D": ["{old} stepped back from design work; {E} mockups go through {new}.",
              "After {old} moved to research, {new} owns {E} design review.",
              "{old} is out of the loop since the redesign and {new} approves {E} visuals."],
        "E": ["{new} shared a mockup for {E}.", "{new} left comments on an {E} wireframe.",
              "{new} presented {E} icons at the design sync."],
        "F": ["{new} has commented on a few {E} mockups.", "{new} might review {E} designs going forward.",
              "{new} looked at one {E} mockup while {old} was out."],
    },
    "deploy region": {
        "B": ["{E} moved off {old} onto {new}.", "{E} was migrated from {old} to {new}.",
              "{E} left {old} for {new}."],
        "C": ["{E} now runs out of {new}.", "{E} serves from {new} these days.", "{E} lives in {new}."],
        "D": ["After the {old} outage, {E} was relocated; it serves from {new} now.",
              "{old} got too expensive, so {E} traffic is in {new}.",
              "The {old} capacity crunch pushed {E} over to {new} for good."],
        "E": ["{E} added a read replica in {new}.", "{E} ran a load test in {new}.", "{E} keeps backups in {new}."],
        "F": ["{E} is probably moving to {new} at some point.", "{E} may run out of {new} soon.",
              "Part of {E} traffic is being tried in {new}."],
    },
    "primary database": {
        "B": ["{E} was migrated from {old} to {new}.", "{E} dropped {old} for {new}.",
              "{E} replaced {old} with {new} for its records."],
        "C": ["{E} runs on {new} these days.", "{E} stores its records in {new} from now on.",
              "{E} data lives in {new}."],
        "D": ["The {old} cluster for {E} was retired after the cutover to {new}.",
              "{old} kept falling over, so {E} was moved onto {new}.",
              "Once {old} hit its limits, {E} records went to {new} for good."],
        "E": ["{E} added {new} for analytics.", "{E} exports a nightly dump to {new}.",
              "{E} benchmarked {new} for a report."],
        "F": ["The {E} team is evaluating {new}.", "{E} may move to {new}.",
              "Someone prototyped {E} on {new}."],
    },
    "CI provider": {
        "B": ["{E} dropped {old} for {new}.", "{E} builds moved from {old} to {new}.",
              "{E} switched from {old} to {new} for its pipelines."],
        "C": ["{E} builds run on {new} from now on.", "{E} pipelines live on {new} now.",
              "{E} ships through {new}."],
        "D": ["Once the {old} contract lapsed, {E} pipelines moved to {new}.",
              "{old} kept timing out, so {E} builds run on {new}.",
              "{old} was shut down for {E} after the cost review; {new} does the builds."],
        "E": ["{E} tried {new} for a side job.", "{new} sent {E} a sales pitch.",
              "{E} used {new} for one hackathon demo."],
        "F": ["Someone suggested moving {E} builds to {new}.", "{E} may switch to {new}.",
              "A few {E} jobs are being trialled on {new}."],
    },
    "vendor": {
        "B": ["{E} switched suppliers from {old} to {new}.", "{E} replaced {old} with {new} as supplier.",
              "{E} stopped buying from {old} and buys from {new}."],
        "C": ["{E} buys from {new} these days.", "{E} sources its tooling from {new} from now on.",
              "{E} gets its supplies from {new}."],
        "D": ["After the {old} deal fell through, {E} signed with {new}.",
              "{old} raised prices, so {E} went with {new}.",
              "{old} went bankrupt in the spring; {E} orders from {new}."],
        "E": ["{new} pitched {E} last week.", "{E} met {new} at a trade show.", "{E} got a quote from {new}."],
        "F": ["{E} may sign with {new}.", "{E} is talking to {new}.", "{E} ordered a sample from {new}."],
    },
}  # fmt: skip
A_TEMPLATES = ["{old} is no longer the {E} {a}. {new} is.", "The {E} {a} changed from {old} to {new}.",
               "{E} {a} update: {new} replaces {old}."]  # fmt: skip


@dataclass
class Case:
    id: str
    category: str
    split: str
    wording: str  # "seen" (dev templates) or "reserved" (held-out-only template)
    entity: str
    attribute: str
    gold: str  # supersedes / unrelated / insufficient
    gold_target: str | None  # "<Entity> <Attribute>" for supersedes
    old: str | None
    new: str
    note: str
    note_date: str
    question: str
    expect: str  # "new" | "old" | "abstain"
    base_cite: str | None


def _gen(kind: str, rng: random.Random) -> str:
    if kind == "person":
        return f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    if kind == "region":
        return rng.choice(REGIONS)
    if kind == "db":
        return rng.choice(DBS)
    if kind == "ci":
        return rng.choice(CIS)
    if kind == "company":
        return f"{rng.choice(CO_A)} {rng.choice(CO_B)}"
    if kind == "amount":
        return f"${rng.randint(12, 480)}k"
    if kind == "date":
        return (date(2026, 11, 1) + timedelta(days=rng.randint(0, 150))).isoformat()
    if kind == "num":
        return str(rng.randint(2, 40))
    raise ValueError(kind)


def _two(kind: str, rng: random.Random) -> tuple[str, str]:
    a = _gen(kind, rng)
    b = _gen(kind, rng)
    while b == a or set(a.split()) & set(b.split()):
        b = _gen(kind, rng)
    return a, b


def _targets(n: int) -> dict[str, int]:
    exact = {c: n * p / 100 for c, p in MIX.items()}
    counts = {c: int(v) for c, v in exact.items()}
    for c in sorted(MIX, key=lambda c: (-(exact[c] - counts[c]), c))[: n - sum(counts.values())]:
        counts[c] += 1
    return counts


def generate(n_cases: int, seed: int) -> tuple[dict[str, str], list[Case], list[tuple[str, str]]]:
    """(entity files, cases, noise notes as (date, text))."""
    rng = random.Random(seed)
    cats = [c for c, k in _targets(n_cases).items() for _ in range(k)]
    rng.shuffle(cats)
    ids = [f"s{i + 1:04d}" for i in range(len(cats))]

    # split first, so wording can depend on it
    srng = random.Random(seed + SPLIT_SEED_OFFSET)
    held: set[str] = set()
    for c in sorted(MIX):
        mine = [i for i, x in zip(ids, cats, strict=True) if x == c]
        srng.shuffle(mine)
        held |= set(mine[: round(HELDOUT_FRACTION * len(mine))])

    pool = [f"{p}{s}" for s in SUFFIXES for p in PROJECTS]
    names = rng.sample(pool, n_cases + n_cases // 5)
    files: dict[str, str] = {}
    cases: list[Case] = []
    for cid, cat, ent in zip(ids, cats, names, strict=False):
        split = "heldout" if cid in held else "dev"
        attr = rng.choice(ASKED)
        kind = KINDS[attr]
        old, new = _two(kind, rng)
        # entity file: the asked attribute (not in G), one sibling of the same kind, 2-4 others
        same = [a for a in KINDS if a != attr and KINDS[a] == kind]
        others = [a for a in KINDS if a != attr and KINDS[a] != kind]
        chosen = rng.sample(same, 1) + rng.sample(others, rng.randint(2, 4))
        if cat != "G":
            chosen.append(attr)
        rng.shuffle(chosen)
        d0 = date(2025, 10, 1) + timedelta(days=rng.randint(0, 90))
        lines = ["---", f"entity: {ent}", f"updated: {d0.isoformat()}", "---", f"# {ent}", ""]
        base_cite = None
        for a in chosen:
            v = old if a == attr else _gen(KINDS[a], rng)
            while a != attr and v in (new, old):
                v = _gen(KINDS[a], rng)
            lines.append(f"- {a[0].upper() + a[1:]}: {v}")
            if a == attr:
                base_cite = f"projects/{ent.lower()}.md:{len(lines)}"
        files[f"projects/{ent.lower()}.md"] = "\n".join(lines) + "\n"

        tcat = "E" if cat == "G" else cat
        options = A_TEMPLATES if cat == "A" else T[attr][tcat]
        k = rng.randrange(len(options)) if split == "heldout" else rng.randrange(len(options) - 1)
        wording = "reserved" if k == len(options) - 1 else "seen"
        note = options[k].format(E=ent, old=old, new=new, a=attr)
        note = note[0].upper() + note[1:]
        when = date(2026, 1, 5) + timedelta(days=rng.randint(0, 260))
        wh = "Who" if kind == "person" else "What"
        question = rng.choice(["{Wh} is the {E} {a}?", "{Wh} is {E}'s {a}?"]).format(Wh=wh, E=ent, a=attr)
        gold = GOLD[cat]
        cases.append(
            Case(cid, cat, split, wording, ent, attr, gold, f"{ent} {attr}" if gold == "supersedes" else None,
                 None if cat == "G" else old, new, note, when.isoformat(), question,
                 {"supersedes": "new", "unrelated": "old", "insufficient": "old"}[gold] if cat != "G" else "abstain",
                 base_cite)  # fmt: skip
        )

    noise_t = ["Standup for {E} ran long today.", "Sent the {E} newsletter draft around.",
               "Booked a room for the {E} retro.", "{E} demo went fine, no blockers.",
               "TODO: archive old {E} tickets.", "Collected feedback from {E} users; mostly positive."]  # fmt: skip
    noise = []
    for _ in range(n_cases // 2):
        d = date(2026, 1, 5) + timedelta(days=rng.randint(0, 260))
        noise.append((d.isoformat(), rng.choice(noise_t).format(E=rng.choice(names))))
    for n in names[n_cases:]:  # entities with no case, so not every entity in the corpus is under test
        attrs = rng.sample(list(KINDS), 4)
        body = "".join(f"- {a[0].upper() + a[1:]}: {_gen(KINDS[a], rng)}\n" for a in attrs)
        files[f"projects/{n.lower()}.md"] = f"---\nentity: {n}\nupdated: 2025-11-15\n---\n# {n}\n\n{body}"
    return files, cases, noise


def cases_sha(cases: list[Case]) -> str:
    body = "".join(json.dumps(asdict(c), sort_keys=True) + "\n" for c in cases)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", required=True)
    ap.add_argument("--freeze", action="store_true", help="write split.json next to this script")
    a = ap.parse_args()
    files, cases, noise = generate(a.cases, a.seed)
    out = Path(a.out)
    for rel, text in files.items():
        p = out / "notes" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (out / "cases.jsonl").write_text("".join(json.dumps(asdict(c)) + "\n" for c in cases), encoding="utf-8")
    (out / "noise.json").write_text(json.dumps(noise, indent=1) + "\n", encoding="utf-8")
    if a.freeze:
        split = {
            "seed": a.seed,
            "n_cases": a.cases,
            "heldout_fraction": HELDOUT_FRACTION,
            "heldout": sorted(c.id for c in cases if c.split == "heldout"),
            "cases_sha256": cases_sha(cases),
        }
        (Path(__file__).resolve().parent / "split.json").write_text(json.dumps(split, indent=1) + "\n")
    print(f"wrote {len(files)} files, {len(cases)} cases, {len(noise)} noise notes to {out}")


if __name__ == "__main__":
    main()
