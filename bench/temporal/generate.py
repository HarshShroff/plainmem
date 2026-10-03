"""Deterministic temporal-memory benchmark generator.

One shared corpus per size: every case owns one (entity, attribute) pair, so cases never collide.
Entities live in ``projects/<slug>.md`` (front matter ``entity:`` + ``updated:`` + H1, 4-6 ``- Attr: value``
lines, one of them the case target). Later changes live in ``logs/2026-Q{1,2,3}.md`` under ascending
``## YYYY-MM-DD`` headings, each bullet naming the entity explicitly. Every file's mtime is set to NOW, so mtime
is never the deciding date. Optional trailing metadata tags use the syntax
``{authority, source, from YYYY-MM-DD}`` (authority: explicit|observed|inferred|imported;
source: user|tool|agent|document).

Categories and mix (largest-remainder rounding of the percentages, positions shuffled with the seeded rng):
  single_update 12%   base + one later log update                          (current)
  multi_update 12%    base + 2-4 sequential updates                        (current)
  contradictory 8%    two values on the SAME log date: {explicit, user} vs {inferred, agent}; explicit wins
  distractor 10%      single update plus 2-3 look-alike facts (same-entity sibling keys, other entity's same key)
  stable 8%           base value only; the log mentions the entity in unrelated bullets
  now_query 8%        multi update, question says "right now" / "currently" / "as of today"
  as_of 14%           base + 2-3 updates; question asks for the value on a date strictly between two changes.
                      About a third carry one back-dated ``{explicit, user, from D}`` update with D earlier than
                      its log heading, and the as_of date falls between D and the heading
  provenance 10%      single tagged update; asks where the value came from; expected_source is the source word
  adversarial 12%     base value in the entity file, later update worded with NO shared key words
  paraphrase 6%       single update; question shares no content word with the attribute name

Seed: everything comes from ``random.Random(seed)``; same (n_cases, seed) gives byte-identical output.

Split rule: BEFORE anyone looks at results, case ids of each category are shuffled with
``random.Random(seed + SPLIT_SEED_OFFSET)`` and ``round(HELDOUT_FRACTION * len)`` of them are marked
"heldout" (stratified by category), the rest are "dev". Tune on dev only. HEADLINE NUMBERS MUST BE REPORTED ON
THE HELDOUT SPLIT ONLY.

Extra Case fields beyond the minimum: ``timeline`` (ground truth, [[effective_date, value], ...] where a
back-dated update is effective on its ``from`` date) and ``backdated`` (bool).

Run:  python bench/temporal/generate.py --cases 100 --seed 2026 --out /tmp/temporal
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from synth import FIRST, LAST, PROJECTS  # noqa: E402

NOW = date(2026, 10, 1)
SPLIT_SEED_OFFSET = 1
HELDOUT_FRACTION = 0.30

LOG_START = date(2026, 1, 5)
LOG_END = date(2026, 9, 25)
D0_START = date(2025, 10, 1)
D0_END = date(2025, 12, 31)
MIN_GAP = 12

MIX = {
    "single_update": 12,
    "multi_update": 12,
    "contradictory": 8,
    "distractor": 10,
    "stable": 8,
    "now_query": 8,
    "as_of": 14,
    "provenance": 10,
    "adversarial": 12,
    "paraphrase": 6,
}

SUFFIXES = [
    "Ridge", "Forge", "Works", "Labs", "Gate", "Hub", "Bay", "Peak", "Field", "Point",
    "Stack", "Yard", "Loop", "Core", "Wave", "Span", "Mill", "Deck", "Reef", "Vault",
    "Grove", "Shore", "Crest", "Bridge", "Run", "Cove", "Dock", "Fold", "Glen", "Spire",
]  # fmt: skip


@dataclass
class Case:
    id: str
    category: str
    query_type: str
    question: str
    as_of: str | None
    expected: str
    stale_values: list[str]
    expected_cite: str
    expected_source: str | None
    entity: str
    attribute: str
    split: str = "dev"
    timeline: list[list[str]] = field(default_factory=list)
    backdated: bool = False


@dataclass
class Bench:
    files: dict[str, str] = field(default_factory=dict)
    mtimes: dict[str, float] = field(default_factory=dict)
    cases: list[Case] = field(default_factory=list)

    def texts(self) -> dict[str, str]:
        return dict(self.files)


@dataclass
class Event:
    when: date
    text: str
    path: str = ""
    line: int = 0


@dataclass
class Attr:
    name: str
    kind: str
    paraphrases: tuple[str, str]
    adversarial: str  # {E} {new}
    distractors: tuple[tuple[str, str], ...]

    @property
    def wh(self) -> str:
        return "Who" if self.kind == "person" else "What"


ATTRS = [
    Attr("project lead", "person", ("Who heads {E}?", "Who is in charge of {E}?"),
         "{new} took over from {old} on {E}.",
         (("staging lead", "person"), ("lead time", "days"), ("project budget", "amount"))),
    Attr("deploy region", "region", ("Which datacenter location hosts {E}?", "Where does {E} run in the cloud?"),
         "{E} now runs out of {new}.",
         (("deploy window", "window"), ("deploy owner", "person"), ("backup region", "region"))),
    Attr("primary database", "db", ("What datastore holds the records of {E}?", "Which engine stores {E}'s data?"),
         "{E} was migrated onto {new}.",
         (("primary key format", "fmt"), ("replica database", "db"), ("database owner", "person"))),
    Attr("on-call engineer", "person", ("Who gets paged when {E} breaks?", "Who carries the pager for {E}?"),
         "{new} picked up the pager for {E}.",
         (("on-call rotation", "rot"), ("backup engineer", "person"), ("engineer headcount", "num"))),
    Attr("release date", "date", ("When does {E} ship?", "When is {E} going out the door?"),
         "{E} ships on {new}.",
         (("release manager", "person"), ("code freeze date", "date"), ("release notes owner", "person"))),
    Attr("budget owner", "person", ("Who controls the money for {E}?", "Who approves spending on {E}?"),
         "{new} now signs off on spend for {E}.",
         (("budget cycle", "cycle"), ("budget ceiling", "amount"), ("asset owner", "person"))),
    Attr("vendor", "company", ("Which supplier does {E} buy from?", "What outside company supplies {E}?"),
         "{E} buys its tooling from {new} these days.",
         (("vendor contract end", "date"), ("vendor tier", "tier"), ("backup vendor", "company"))),
    Attr("design reviewer", "person", ("Who critiques the visuals for {E}?", "Who signs off on mockups for {E}?"),
         "{new} reviews all mockups for {E}.",
         (("design system", "ds"), ("code reviewer", "person"), ("design tokens version", "semver"))),
    Attr("staging cluster", "cluster",
         ("Where is {E} pre-production hosted?", "Which environment does {E} rehearse rollouts on?"),
         "{E} rehearses on {new} before any rollout.",
         (("staging lead", "person"), ("staging window", "window"), ("prod cluster", "cluster"))),
    Attr("CI provider", "ci",
         ("What service runs the pipelines for {E}?", "Which service executes {E}'s automated builds?"),
         "{E} builds run on {new} from now on.",
         (("CI minutes", "num"), ("CD provider", "ci"), ("provider contact", "person"))),
    Attr("cache layer", "cache", ("What in-memory store does {E} use?", "Which tool keeps {E}'s hot data fast?"),
         "{E} keeps hot data in {new}.",
         (("cache ttl", "ttl"), ("layer count", "num"), ("cache owner", "person"))),
    Attr("alert channel", "channel", ("Where do {E} notifications land?", "Which chat room receives warnings for {E}?"),
         "{E} pings go to {new}.",
         (("alert threshold", "pct"), ("escalation channel", "channel"), ("channel admin", "person"))),
]  # fmt: skip

REGIONS = ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "eu-west-1", "eu-west-2", "eu-central-1",
           "ap-south-1", "ap-southeast-2", "ca-central-1", "sa-east-1", "ap-northeast-1"]  # fmt: skip
DBS = ["Postgres 15", "Postgres 16", "MySQL 8", "MariaDB 10", "CockroachDB", "ScyllaDB", "MongoDB 7",
       "SQLite", "DynamoDB", "ClickHouse", "Cassandra 4", "TimescaleDB"]  # fmt: skip
CIS = ["GitHub Actions", "CircleCI", "Buildkite", "Jenkins", "GitLab CI", "Drone", "TeamCity", "Travis CI",
       "Azure Pipelines", "Bitrise"]  # fmt: skip
CACHES = ["Redis 7", "Memcached", "Valkey", "Hazelcast", "Dragonfly", "Varnish", "KeyDB", "Aerospike"]
CO_A = ["Northwind", "Brightwater", "Calloway", "Dunmere", "Ellison", "Fairhaven", "Granite", "Hollis",
        "Ironbridge", "Kellmark", "Larkspur", "Mossgate"]  # fmt: skip
CO_B = ["Freight", "Systems", "Logistics", "Supply Co", "Partners", "Dynamics", "Networks", "Industries"]
CHAN_A = ["ops", "infra", "sre", "platform", "oncall", "pager"]
CHAN_B = ["alerts", "war-room", "triage", "signals", "watch"]
WINDOWS = ["Tuesdays 14:00 UTC", "Thursdays 09:00 UTC", "Mondays 16:30 UTC", "Fridays 11:00 UTC"]
DS = ["Atlas UI", "Prism kit", "Lumen DS", "Quartz components"]
TIERS = ["gold", "silver", "bronze", "platinum"]
ROTS = ["weekly", "biweekly", "follow-the-sun", "monthly"]
CYCLES = ["quarterly", "annual", "monthly", "semiannual"]
FMTS = ["uuid", "bigint", "ulid", "composite"]


def _person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def _gen(kind: str, rng: random.Random) -> str:
    if kind == "person":
        return _person(rng)
    if kind == "region":
        return rng.choice(REGIONS)
    if kind == "db":
        return rng.choice(DBS)
    if kind == "date":
        return (date(2026, 10, 15) + timedelta(days=rng.randint(0, 170))).isoformat()
    if kind == "company":
        return f"{rng.choice(CO_A)} {rng.choice(CO_B)}"
    if kind == "cluster":
        return f"{rng.choice(['stg', 'pre', 'blue', 'green', 'canary'])}-{rng.choice(['aurora', 'delta', 'falcon', 'harbor', 'onyx'])}-{rng.randint(1, 30):02d}"  # noqa: E501
    if kind == "ci":
        return rng.choice(CIS)
    if kind == "cache":
        return rng.choice(CACHES)
    if kind == "channel":
        return f"#{rng.choice(CHAN_A)}-{rng.choice(CHAN_B)}-{rng.randint(10, 99)}"
    if kind == "days":
        return f"{rng.randint(3, 40)} days"
    if kind == "amount":
        return f"${rng.randint(12, 480)}k"
    if kind == "window":
        return rng.choice(WINDOWS)
    if kind == "num":
        return str(rng.randint(2, 60))
    if kind == "tier":
        return rng.choice(TIERS)
    if kind == "rot":
        return rng.choice(ROTS)
    if kind == "fmt":
        return rng.choice(FMTS)
    if kind == "ds":
        return rng.choice(DS)
    if kind == "semver":
        return f"{rng.randint(1, 4)}.{rng.randint(0, 9)}.{rng.randint(0, 9)}"
    if kind == "ttl":
        return f"{rng.choice([30, 60, 120, 300, 900])}s"
    if kind == "pct":
        return f"{rng.randint(50, 99)}%"
    if kind == "cycle":
        return rng.choice(CYCLES)
    raise ValueError(kind)


def _unique_values(kind: str, k: int, rng: random.Random) -> list[str]:
    out: list[str] = []
    guard = 0
    while len(out) < k:
        v = _gen(kind, rng)
        guard += 1
        if v not in out or guard > 500:
            out.append(v)
    return out


def _tag(*items: str) -> str:
    return "{" + ", ".join(items) + "}"


def _line(ent: str, key: str, value: str, rng: random.Random, tag: str | None = None) -> str:
    """One log bullet naming the entity; drops the final period when a tag is appended."""
    style = rng.randrange(5)
    if style == 0:
        s = f"{ent} {key} is now {value}."
    elif style == 1:
        s = f"{ent} {key} changed to {value}."
    elif style == 2:
        s = f"{ent} {key}: {value}"
    elif style == 3:
        s = f"{ent} {key} moved to {value}."
    else:
        s = f"{ent} {key} switched to {value}."
    if tag:
        s = s.rstrip(".") + " " + tag
    return "- " + s


def _slug(name: str) -> str:
    return name.lower()


def _targets(n: int) -> dict[str, int]:
    exact = {c: n * p / 100 for c, p in MIX.items()}
    counts = {c: int(v) for c, v in exact.items()}
    rest = n - sum(counts.values())
    order = sorted(MIX, key=lambda c: (-(exact[c] - counts[c]), c))
    for c in order[:rest]:
        counts[c] += 1
    return counts


def _entity_pool(total: int) -> list[str]:
    pool = list(PROJECTS) + [f"{p}{s}" for s in SUFFIXES for p in PROJECTS]
    seen: set[str] = set()
    uniq = [x for x in pool if not (x in seen or seen.add(x))]
    if len(uniq) < total:
        raise ValueError(f"cannot invent {total} entity names (max {len(uniq)})")
    return uniq


def _pick_dates(k: int, rng: random.Random) -> list[date]:
    span = (LOG_END - LOG_START).days + 1 - (k - 1) * MIN_GAP
    offs = sorted(rng.sample(range(span), k))
    return [LOG_START + timedelta(days=o + i * MIN_GAP) for i, o in enumerate(offs)]


def _rand_day(rng: random.Random, a: date, b: date) -> date:
    return a + timedelta(days=rng.randint(0, (b - a).days))


def _entity_file(name: str, d0: date, attrs: dict[str, str], order: list[str]) -> tuple[str, dict[str, int]]:
    lines = ["---", f"entity: {name}", f"updated: {d0.isoformat()}", "---", f"# {name}", ""]
    where: dict[str, int] = {}
    for a in order:
        lines.append(f"- {a[0].upper() + a[1:]}: {attrs[a]}")
        where[a] = len(lines)
    return "\n".join(lines) + "\n", where


def _epoch(d: date) -> float:
    return datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc).timestamp()


NOISE = [
    "Met with the {E} team about onboarding docs.",
    "TODO: write up the {E} retro notes.",
    "{E} demo went fine, no blockers.",
    "Reminder: {E} quarterly review is next month.",
    "Sync with {E} folks pushed to the afternoon.",
    "Collected feedback from users of {E}; mostly positive.",
    "TODO: archive old {E} tickets.",
    "Pairing session on {E} documentation, notes in the wiki.",
]
UNRELATED = [
    "Standup for {E} ran long today, parked two threads.",
    "Sent the {E} newsletter draft around for comments.",
    "Booked the offsite room for the {E} retro.",
    "Someone asked about {E} swag again; no budget for it this quarter.",
    "Skimmed the {E} onboarding doc, typos only.",
]
EXTRA_FACTS = [("team size", "num"), ("standup day", "weekday"), ("office city", "city"), ("mascot", "mascot")]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
CITIES = ["Lisbon", "Austin", "Gdansk", "Osaka", "Leeds", "Medellin"]
MASCOTS = ["otter", "heron", "lynx", "badger", "stoat"]


def _extra_value(kind: str, rng: random.Random) -> str:
    if kind == "weekday":
        return rng.choice(WEEKDAYS)
    if kind == "city":
        return rng.choice(CITIES)
    if kind == "mascot":
        return rng.choice(MASCOTS)
    return _gen(kind, rng)


def generate(n_cases: int, seed: int) -> Bench:
    rng = random.Random(seed)
    cats: list[str] = []
    for c, k in _targets(n_cases).items():
        cats += [c] * k
    rng.shuffle(cats)

    n_noise = max(10, n_cases // 5)
    pool = _entity_pool(n_cases + n_noise)
    names = rng.sample(pool, n_cases + n_noise)
    case_names, noise_names = names[:n_cases], names[n_cases:]
    noise_attrs: dict[str, dict[str, str]] = {n: {} for n in noise_names}

    bench = Bench()
    events: list[Event] = []
    refs: list[tuple[Case, Event | None, tuple[str, int] | None]] = []
    asof_count = 0

    def ev(when: date, text: str) -> Event:
        e = Event(when, text)
        events.append(e)
        return e

    for i, cat in enumerate(cats):
        cid = f"t{i + 1:04d}"
        ent = case_names[i]
        attr = rng.choice(ATTRS)
        d0 = _rand_day(rng, D0_START, D0_END)
        key = attr.name
        query_type = "current"
        as_of: str | None = None
        backdated = False

        k = {"single_update": 1, "distractor": 1, "provenance": 1, "adversarial": 1, "paraphrase": 1,
             "contradictory": 1, "stable": 0}.get(cat)  # fmt: skip
        if cat in ("multi_update", "now_query"):
            k = rng.randint(2, 4)
        elif cat == "as_of":
            k = rng.randint(2, 3)
        assert k is not None
        n_vals = k + 1 if cat != "contradictory" else 3
        vals = _unique_values(attr.kind, n_vals, rng)
        dates = _pick_dates(max(k, 1), rng) if cat != "stable" else []

        # entity file (base values and background facts)
        bg_names = rng.sample([a for a in ATTRS if a is not attr], rng.randint(3, 5))
        attrs_map = {attr.name: vals[0]}
        for b in bg_names:
            attrs_map[b.name] = _gen(b.kind, rng)
        order = list(attrs_map)
        rng.shuffle(order)
        text, where = _entity_file(ent, d0, attrs_map, order)
        path = f"projects/{_slug(ent)}.md"
        bench.files[path] = text
        base_cite = (path, where[attr.name])

        timeline = [[d0.isoformat(), vals[0]]]
        upd_events: list[Event] = []
        expected_event: Event | None = None
        expected_cite_override: tuple[str, int] | None = None
        expected_idx = k  # index into vals of the correct value
        source: str | None = None

        if cat in ("single_update", "multi_update", "now_query", "paraphrase"):
            for j in range(k):
                e = ev(dates[j], _line(ent, key, vals[j + 1], rng))
                upd_events.append(e)
                timeline.append([dates[j].isoformat(), vals[j + 1]])
            expected_event = upd_events[-1]
        elif cat == "distractor":
            e = ev(dates[0], _line(ent, key, vals[1], rng))
            upd_events.append(e)
            timeline.append([dates[0].isoformat(), vals[1]])
            expected_event = e
            nd = rng.randint(2, 3)
            other = rng.choice(noise_names)
            ov = _gen(attr.kind, rng)
            noise_attrs[other][key] = _gen(attr.kind, rng)
            ev(dates[0], _line(other, key, ov, rng))
            for dk, dkind in rng.sample(list(attr.distractors), nd - 1):
                dd = min(LOG_END, max(LOG_START, dates[0] + timedelta(days=rng.choice([-5, -2, 0, 0, 1, 3, 6]))))
                ev(dd, _line(ent, dk, _gen(dkind, rng), rng))
        elif cat == "stable":
            expected_idx = 0
            expected_cite_override = base_cite
            for _ in range(rng.randint(2, 3)):
                ev(_rand_day(rng, LOG_START, LOG_END), "- " + rng.choice(UNRELATED).format(E=ent))
        elif cat == "contradictory":
            h = dates[0]
            lines = [
                (vals[1], _tag("explicit", "user"), "user"),
                (vals[2], _tag("inferred", "agent"), "agent"),
            ]
            if rng.random() < 0.5:
                lines.reverse()
            for v, t, s in lines:
                e = ev(h, _line(ent, key, v, rng, t))
                if s == "user":
                    expected_event = e
                    source = "user"
            timeline.append([h.isoformat(), vals[1]])
            expected_idx = 1
        elif cat == "provenance":
            auth, src = rng.choice([("observed", "tool"), ("explicit", "user"), ("imported", "document")])
            e = ev(dates[0], _line(ent, key, vals[1], rng, _tag(auth, src)))
            expected_event, source = e, src
            timeline.append([dates[0].isoformat(), vals[1]])
            query_type = "provenance"
        elif cat == "adversarial":
            e = ev(dates[0], "- " + attr.adversarial.format(E=ent, new=vals[1], old=vals[0]))
            expected_event = e
            timeline.append([dates[0].isoformat(), vals[1]])
        elif cat == "as_of":
            query_type = "as_of"
            asof_count += 1
            backdated = asof_count % 3 == 1
            eff = [d0] + dates
            bj = rng.randint(1, k) if backdated else 0
            for j in range(k):
                h = dates[j]
                if backdated and j + 1 == bj:
                    prev = eff[j]
                    f = h - timedelta(days=rng.randint(4, min(40, (h - prev).days - 1)))
                    eff[j + 1] = f
                    e = ev(h, _line(ent, key, vals[j + 1], rng, _tag("explicit", "user", f"from {f.isoformat()}")))
                else:
                    e = ev(h, _line(ent, key, vals[j + 1], rng))
                upd_events.append(e)
                timeline.append([eff[j + 1].isoformat(), vals[j + 1]])
            if backdated:
                w = bj
                a = _rand_day(rng, eff[w] + timedelta(days=1), dates[w - 1] - timedelta(days=1))
            else:
                w = rng.randint(0, k - 1)
                lo, hi = eff[w], eff[w + 1]
                a = _rand_day(rng, lo + timedelta(days=1), hi - timedelta(days=1))
            as_of = a.isoformat()
            expected_idx = w
            if w == 0:
                expected_cite_override = base_cite
            else:
                expected_event = upd_events[w - 1]
            source = "user" if backdated else None

        # question
        E = ent
        if cat == "paraphrase":
            question = rng.choice(attr.paraphrases).format(E=E)
        elif cat == "adversarial" or cat in ("single_update", "multi_update", "distractor", "stable", "contradictory"):
            question = rng.choice(["{Wh} is the {E} {a}?", "{Wh} is {E}'s {a}?"]).format(Wh=attr.wh, E=E, a=key)
        elif cat == "now_query":
            question = rng.choice(
                [
                    "{Wh} is the {E} {a} right now?",
                    "{Wh} is {E}'s {a} currently?",
                    "As of today, {wh} is the {E} {a}?",
                ]
            ).format(Wh=attr.wh, wh=attr.wh.lower(), E=E, a=key)
        elif cat == "as_of":
            question = rng.choice(["{Wh} was the {E} {a} on {d}?", "{Wh} was {E}'s {a} as of {d}?"]).format(
                Wh=attr.wh, E=E, a=key, d=as_of
            )
        else:
            question = rng.choice(
                [
                    "Where did the {E} {a} come from?",
                    "What is the source of the {E} {a}?",
                    "Where does the current {E} {a} come from?",
                ]
            ).format(E=E, a=key)

        expected = vals[expected_idx]
        stale = [vals[2], vals[0]] if cat == "contradictory" else [v for j, v in enumerate(vals) if j != expected_idx]
        case = Case(
            id=cid,
            category=cat,
            query_type=query_type,
            question=question,
            as_of=as_of,
            expected=expected,
            stale_values=stale,
            expected_cite="",
            expected_source=source,
            entity=ent,
            attribute=key,
            timeline=timeline,
            backdated=backdated,
        )
        refs.append((case, expected_event, expected_cite_override))
        bench.cases.append(case)

        # occasional background-attribute update (never for stable cases)
        if cat != "stable" and rng.random() < 0.2:
            b = rng.choice(bg_names)
            ev(_rand_day(rng, LOG_START, LOG_END), _line(ent, b.name, _gen(b.kind, rng), rng))

    # noise entity files
    for n in noise_names:
        have = noise_attrs[n]
        extra = [a for a in ATTRS if a.name not in have]
        for a in rng.sample(extra, max(0, rng.randint(4, 6) - len(have))):
            have[a.name] = _gen(a.kind, rng)
        order = list(have)
        rng.shuffle(order)
        d0 = _rand_day(rng, D0_START, D0_END)
        bench.files[f"projects/{_slug(n)}.md"] = _entity_file(n, d0, have, order)[0]

    # background log noise
    everyone = case_names + noise_names
    for _ in range(n_cases // 2):
        ev(_rand_day(rng, LOG_START, LOG_END), "- " + rng.choice(NOISE).format(E=rng.choice(everyone)))
    for _ in range(n_cases // 4):
        k2, kind = rng.choice(EXTRA_FACTS)
        ev(_rand_day(rng, LOG_START, LOG_END), _line(rng.choice(everyone), k2, _extra_value(kind, rng), rng))

    # render logs
    quarters = {"2026-Q1": (1, 3), "2026-Q2": (4, 6), "2026-Q3": (7, 9)}
    for q, (m1, m2) in quarters.items():
        path = f"logs/{q}.md"
        lines = [f"# Engineering log {q}", ""]
        by_day: dict[date, list[Event]] = {}
        for e in events:
            if m1 <= e.when.month <= m2:
                by_day.setdefault(e.when, []).append(e)
        for d in sorted(by_day):
            lines.append(f"## {d.isoformat()}")
            for e in by_day[d]:
                lines.append(e.text)
                e.path, e.line = path, len(lines)
            lines.append("")
        bench.files[path] = "\n".join(lines)

    for case, e, override in refs:
        p, ln = override if override else (e.path, e.line)  # type: ignore[union-attr]
        case.expected_cite = f"{p}:{ln}"

    # held-out split, stratified, fixed by the seed before anyone sees results
    srng = random.Random(seed + SPLIT_SEED_OFFSET)
    for c in sorted(MIX):
        ids = [x.id for x in bench.cases if x.category == c]
        srng.shuffle(ids)
        held = set(ids[: round(HELDOUT_FRACTION * len(ids))])
        for x in bench.cases:
            if x.id in held:
                x.split = "heldout"

    bench.mtimes = {p: _epoch(NOW) for p in bench.files}
    return bench


def write(bench: Bench, out_dir: str | Path, seed: int = 0) -> Path:
    out = Path(out_dir)
    for rel, text in bench.files.items():
        p = out / "notes" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        os.utime(p, (bench.mtimes[rel], bench.mtimes[rel]))
    body = "".join(json.dumps(asdict(c), sort_keys=True) + "\n" for c in bench.cases)
    (out / "cases.jsonl").write_text(body, encoding="utf-8")
    counts: dict[str, dict[str, int]] = {}
    for c in bench.cases:
        counts.setdefault(c.category, {"dev": 0, "heldout": 0})[c.split] += 1
    manifest = {
        "seed": seed,
        "n_cases": len(bench.cases),
        "heldout_fraction": HELDOUT_FRACTION,
        "split_seed_offset": SPLIT_SEED_OFFSET,
        "counts": counts,
        "cases_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", type=int, default=100)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    b = generate(a.cases, a.seed)
    write(b, a.out, a.seed)
    print(f"wrote {len(b.files)} files and {len(b.cases)} cases to {a.out}")


if __name__ == "__main__":
    main()
