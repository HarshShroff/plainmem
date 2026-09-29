"""Generate a synthetic personal-notes corpus and labeled queries.

Everything here is invented: names are random first/last combinations, companies
and places are made up, emails use example.com and phones use the 555-01xx
fiction range. The generator is deterministic for a given seed.

Query types:
  lookup      the query reuses the words of the fact
  paraphrase  the query asks for the same fact in other words (author-written templates)
  superseded  two notes disagree; the correct answer is the NEWER one
  stale       a volatile fact (price, hours, status); correct behaviour is to return it
              and flag it if it is older than the volatile window. A third of these are
              fresh controls that must NOT be flagged.

Run:  python bench/synth.py --out /tmp/corpus   (writes files + queries.jsonl)
"""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

NOW = date(2026, 9, 29)

FIRST = [
    "Mara",
    "Theo",
    "Ines",
    "Callum",
    "Priya",
    "Joaquin",
    "Noor",
    "Elias",
    "Wren",
    "Tomasz",
    "Keiko",
    "Anders",
    "Lucia",
    "Obi",
    "Saskia",
    "Rafael",
    "Imani",
    "Bram",
    "Yusuf",
    "Clio",
    "Dario",
    "Hedda",
    "Kofi",
    "Linnea",
    "Mateo",
    "Oona",
    "Pavel",
    "Rosalind",
    "Soren",
    "Talia",
    "Ugo",
    "Vesna",
    "Wes",
    "Xiomara",
    "Yara",
    "Zeno",
    "Amara",
    "Birgit",
    "Cosmo",
    "Delphine",
    "Ezra",
    "Fenna",
    "Gideon",
    "Hana",
    "Ivo",
    "Juno",
    "Kaspar",
    "Leda",
    "Milo",
    "Nadia",
]
LAST = [
    "Quell",
    "Ashgrove",
    "Brandtley",
    "Corvane",
    "Dellamore",
    "Eastwick",
    "Fairbairn",
    "Gundry",
    "Holloway",
    "Ingleby",
    "Jarrow",
    "Kestner",
    "Lindqvist",
    "Marrow",
    "Nettleby",
    "Orsolo",
    "Pellow",
    "Quenby",
    "Rushworth",
    "Stavely",
    "Thorncombe",
    "Underhill",
    "Vantongeren",
    "Wexley",
    "Yarborough",
    "Zell",
    "Ambrose",
    "Blackwood",
    "Carrow",
    "Dunmore",
    "Everley",
    "Fenwick",
    "Garside",
    "Haverill",
    "Ivesdale",
]
PROJECTS = [
    "Orion",
    "Atlas",
    "Juniper",
    "Halcyon",
    "Meridian",
    "Tamarack",
    "Kestrel",
    "Lodestar",
    "Bramble",
    "Cinder",
    "Driftwood",
    "Ember",
    "Fathom",
    "Gossamer",
    "Harbor",
    "Isthmus",
    "Jetstream",
    "Kiln",
    "Lantern",
    "Marigold",
    "Nimbus",
    "Obsidian",
    "Pinnacle",
    "Quarry",
    "Rookery",
    "Saffron",
    "Tundra",
    "Umbra",
    "Vireo",
    "Willow",
    "Yarrow",
    "Zephyr",
    "Aster",
    "Basalt",
    "Cobalt",
    "Dune",
    "Estuary",
    "Fjord",
    "Glacier",
    "Heron",
    "Indigo",
    "Jasper",
    "Kelp",
    "Lichen",
    "Mistral",
    "Nectar",
    "Onyx",
    "Petrel",
    "Quill",
    "Rivulet",
    "Sable",
    "Thistle",
    "Upland",
    "Vesper",
    "Wharf",
    "Alder",
    "Birch",
    "Cedar",
    "Dogwood",
]
COMPANIES = """Kestrel Labs|Fernwood Bio|Northgate Analytics|Pallas Robotics|Glasshouse Studio|Tidewater Health|
Copperline Freight|Mossbank Energy|Quillon Software|Redfern Capital|Silverleaf Foods|Brightpath Learning|
Harrowgate Legal|Lumen Grid|Oakhollow Media|Stonebridge Civic""".replace("\n", "").split("|")
ROLES = [
    "staff designer",
    "engineering manager",
    "data scientist",
    "product lead",
    "research engineer",
    "operations director",
    "security engineer",
    "founder",
    "technical writer",
    "platform engineer",
]
TOOLS = [
    "Postgres",
    "SQLite",
    "DuckDB",
    "Redis",
    "Kafka",
    "GitHub Actions",
    "Buildkite",
    "Terraform",
    "Rust",
    "Go",
    "TypeScript",
    "Svelte",
    "Django",
    "FastAPI",
    "Grafana",
    "OpenTelemetry",
]
REASONS = [
    "the old runners kept timing out",
    "it cut hosting cost roughly in half",
    "the team already knew it",
    "the migration path was simpler",
    "latency on the old setup was too high",
    "licensing got expensive",
    "it removed a whole service we had to babysit",
    "on-call load was unsustainable",
]
TOPICS = [
    "roadmap review",
    "hiring loop",
    "incident retro",
    "budget check-in",
    "design crit",
    "vendor call",
    "quarterly planning",
    "demo prep",
    "security review",
    "customer interview",
]
TOWNS = ["Millbrook", "Ashford Vale", "Carrow Point", "Dunmere", "Eastlake", "Fenby", "Greywater", "Holt Crossing"]
STREETS = ["Alder St", "Birch Ave", "Canal Rd", "Dove Ln", "Elm Row", "Ferry St", "Granite Way", "Hazel Ct"]
PLACE_KINDS = [
    ("Climbing Gym", "day pass"),
    ("Coffee Roasters", "bag of house beans"),
    ("Yoga Studio", "drop-in class"),
    ("Bike Shop", "basic tune-up"),
    ("Dental Clinic", "cleaning without insurance"),
    ("Bakery", "sourdough loaf"),
    ("Coworking Space", "day desk"),
    ("Laundromat", "large load wash"),
    ("Bookshop", "used paperback"),
    ("Pool", "lap swim entry"),
]
PLACE_PREFIX = [
    "Brightwater",
    "Juniper",
    "Hollowmere",
    "Saltmarsh",
    "Larkspur",
    "Thornbury",
    "Copperfield",
    "Riverbend",
    "Oldmill",
    "Greenway",
    "Stonecrest",
    "Foxglove",
    "Westerly",
    "Pinewood",
    "Harborside",
    "Kingsfield",
    "Maplehurst",
    "Clearwell",
    "Redcliff",
    "Northfield",
]
PREFS = [
    ("prefers morning meetings, ideally before 10am", "when does {name} like to meet", "{name} meeting preference"),
    (
        "likes written updates over calls",
        "does {name} want a call or something written",
        "{name} written updates calls",
    ),
    ("is vegetarian, avoid booking steakhouses", "what food restrictions does {name} have", "{name} vegetarian"),
    (
        "hates surprise agenda changes; send the agenda a day ahead",
        "how should I prepare agendas for {name}",
        "{name} agenda ahead",
    ),
    ("replies fastest on Signal", "best way to get a quick answer from {name}", "{name} Signal replies"),
]
HOURS = [
    "Mon-Fri 7am-9pm, weekends 9am-6pm",
    "daily 6am-10pm",
    "Tue-Sun 8am-4pm, closed Mondays",
    "Mon-Sat 10am-7pm",
    "weekdays 6:30am-8pm",
]


@dataclass
class Query:
    qid: str
    qtype: str
    query: str
    path: str
    line: int
    old_path: str = ""
    old_line: int = 0
    expect_flag: bool | None = None
    note: str = ""


class FileBuilder:
    def __init__(self, path: str, when: date) -> None:
        self.path, self.when, self.lines = path, when, []

    def add(self, line: str = "") -> int:
        self.lines.append(line)
        return len(self.lines)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


@dataclass
class Corpus:
    files: dict[str, FileBuilder] = field(default_factory=dict)
    queries: list[Query] = field(default_factory=list)

    def texts(self) -> dict[str, str]:
        return {p: f.text() for p, f in self.files.items()}

    def mtimes(self) -> dict[str, float]:
        return {p: _epoch(f.when) for p, f in self.files.items()}


def _epoch(d: date) -> float:
    return datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc).timestamp()


def _slug(s: str) -> str:
    return "-".join(s.lower().replace("'", "").split())


def generate(seed: int = 7) -> Corpus:
    rng = random.Random(seed)
    c = Corpus()
    rand_day = lambda a, b: a + timedelta(days=rng.randint(0, (b - a).days))  # noqa: E731

    names: list[str] = []
    while len(names) < 130:
        n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        if n not in names:
            names.append(n)

    # ---- contacts -------------------------------------------------------------
    contact_facts: dict[str, dict[str, int]] = {}
    contact_meta: dict[str, dict[str, str]] = {}
    for n in names:
        first, last = n.split()
        when = rand_day(date(2025, 3, 1), date(2026, 6, 30))
        fb = FileBuilder(f"contacts/{_slug(n)}.md", when)
        fb.add("---")
        fb.add(f"updated: {when.isoformat()}")
        fb.add("---")
        fb.add(f"# {n}")
        fb.add()
        company, role = rng.choice(COMPANIES), rng.choice(ROLES)
        facts = {}
        facts["role"] = fb.add(f"- Role: {role}")
        facts["company"] = fb.add(f"- Company: {company}")
        facts["email"] = fb.add(f"- Email: {first.lower()}.{last.lower()}@example.com")
        facts["phone"] = fb.add(f"- Phone: 555-01{rng.randint(10, 99)}")
        town = rng.choice(TOWNS)
        facts["town"] = fb.add(f"- Lives in {town}")
        fb.add()
        fb.add("## Notes")
        fb.add()
        pref_i = rng.randrange(len(PREFS))
        facts["pref"] = fb.add(f"{first} {PREFS[pref_i][0]}.")
        fb.add()
        facts["met"] = fb.add(
            f"Met at the {rng.choice(TOPICS)} for {rng.choice(PROJECTS)} "
            f"in {when:%B %Y}; introduced by {rng.choice(names)}."
        )
        c.files[fb.path] = fb
        contact_facts[n] = facts
        contact_meta[n] = {"company": company, "role": role, "town": town, "pref": str(pref_i), "when": str(when)}

    # ---- projects -------------------------------------------------------------
    proj_facts: dict[str, dict[str, int]] = {}
    proj_meta: dict[str, dict[str, str]] = {}
    for p in PROJECTS:
        when = rand_day(date(2025, 4, 1), date(2026, 5, 31))
        fb = FileBuilder(f"projects/{_slug(p)}.md", when)
        fb.add("---")
        fb.add(f"verified: {when.isoformat()}")
        fb.add("---")
        fb.add(f"# {p}")
        fb.add()
        fb.add("## Overview")
        fb.add()
        tool = rng.choice(TOOLS)
        fb.add(
            f"{p} is an internal effort to rebuild the {rng.choice(['billing', 'search', 'reporting', 'onboarding', 'scheduling', 'inventory'])} "
            f"pipeline on {tool}. It started in {when:%B %Y} and has {rng.randint(2, 7)} people part time."
        )
        fb.add()
        fb.add("## People")
        fb.add()
        lead, designer, reviewer = rng.sample(names, 3)
        facts = {}
        facts["lead"] = fb.add(f"- Project lead: {lead}")
        facts["designer"] = fb.add(f"- Designer: {designer}")
        facts["reviewer"] = fb.add(f"- Security reviewer: {reviewer}")
        fb.add()
        fb.add("## Decisions")
        fb.add()
        dtool, reason = rng.choice(TOOLS), rng.choice(REASONS)
        d1 = when + timedelta(days=rng.randint(3, 60))
        facts["decision"] = fb.add(f"- {d1.isoformat()}: moved the {p} build pipeline to {dtool} because {reason}.")
        for _ in range(rng.randint(2, 4)):
            fb.add(
                f"- {(when + timedelta(days=rng.randint(1, 90))).isoformat()}: agreed to "
                f"{rng.choice(['drop', 'keep', 'revisit', 'pilot'])} {rng.choice(TOOLS)} for "
                f"{rng.choice(['staging', 'analytics', 'the admin UI', 'batch jobs', 'alerts'])}."
            )
        fb.add()
        fb.add("## Status")
        fb.add()
        target = when + timedelta(days=rng.randint(60, 200))
        facts["deadline"] = fb.add(f"- Launch target: {target.isoformat()}")
        facts["budget"] = fb.add(f"- Quarterly budget: {rng.randint(8, 90)}k")
        fb.add(f"- Repo lives under the {rng.choice(['platform', 'growth', 'core', 'infra'])} org.")
        c.files[fb.path] = fb
        proj_facts[p] = facts
        proj_meta[p] = {"lead": lead, "designer": designer, "tool": dtool, "reason": reason, "when": str(when)}

    # ---- places (volatile) ----------------------------------------------------
    place_facts: dict[str, dict[str, int]] = {}
    place_meta: dict[str, dict[str, str]] = {}
    places = []
    for i, prefix in enumerate(PLACE_PREFIX * 2):
        kind, item = PLACE_KINDS[(i + i // len(PLACE_PREFIX)) % len(PLACE_KINDS)]
        name = f"{prefix} {kind}"
        if name in places:
            continue
        places.append(name)
    for name in places[:40]:
        kind = next(k for k in PLACE_KINDS if name.endswith(k[0]))
        stale = rng.random() < 0.6
        verified = (
            rand_day(date(2025, 10, 1), date(2026, 7, 31)) if stale else rand_day(date(2026, 9, 5), date(2026, 9, 27))
        )
        fb = FileBuilder(f"places/{_slug(name)}.md", verified)
        fb.add(f"# {name}")
        fb.add()
        facts = {}
        facts["address"] = fb.add(f"- Address: {rng.randint(2, 480)} {rng.choice(STREETS)}, {rng.choice(TOWNS)}")
        facts["hours"] = fb.add(f"- Hours: {rng.choice(HOURS)} [verified: {verified.isoformat()}]")
        price = rng.randint(4, 140)
        facts["price"] = fb.add(f"- A {kind[1]} currently costs ${price}. [verified: {verified.isoformat()}]")
        fb.add()
        fb.add(
            f"Went {rng.randint(2, 20)} times so far. {rng.choice(['Quiet before 9.', 'Parking is tight.', 'Friendly staff.', 'Card only.'])}"
        )
        c.files[fb.path] = fb
        place_facts[name] = facts
        place_meta[name] = {"stale": str(stale), "item": kind[1], "verified": str(verified)}

    # ---- misc notes -----------------------------------------------------------
    for i in range(24):
        when = rand_day(date(2025, 3, 1), date(2026, 9, 1))
        fb = FileBuilder(f"reading/book-{i:02d}.md", when)
        fb.add(f"# Book notes {i + 1}")
        fb.add()
        for _ in range(rng.randint(4, 8)):
            fb.add(
                f"- On {rng.choice(['habits', 'focus', 'writing', 'systems', 'negotiation', 'sleep'])}: "
                f"{rng.choice(['keep the loop short', 'write it down the same day', 'defaults beat willpower', 'measure before changing things', 'small batches ship'])}."
            )
        c.files[fb.path] = fb
    for i in range(16):
        when = rand_day(date(2025, 3, 1), date(2026, 9, 1))
        fb = FileBuilder(f"recipes/recipe-{i:02d}.md", when)
        fb.add(
            f"# {rng.choice(['Lentil', 'Mushroom', 'Chickpea', 'Squash', 'Tofu', 'Spinach'])} "
            f"{rng.choice(['stew', 'curry', 'bake', 'soup', 'salad'])} {i + 1}"
        )
        fb.add()
        for _ in range(rng.randint(3, 6)):
            fb.add(
                f"- {rng.randint(1, 4)} {rng.choice(['cups', 'tbsp', 'cloves', 'handfuls'])} "
                f"{rng.choice(['onion', 'garlic', 'cumin', 'stock', 'rice', 'tomato'])}"
            )
        fb.add()
        fb.add(
            f"Cook for {rng.randint(15, 90)} minutes. {rng.choice(['Freezes well.', 'Better the next day.', 'Double the spice.'])}"
        )
        c.files[fb.path] = fb

    # ---- journal + supersession ---------------------------------------------
    days = sorted({rand_day(date(2025, 3, 1), date(2026, 9, 28)) for _ in range(190)})[:160]
    journal: dict[date, FileBuilder] = {}
    for d in days:
        fb = FileBuilder(f"journal/{d.isoformat()}.md", d)
        fb.add(f"# {d.isoformat()}")
        fb.add()
        for _ in range(rng.randint(3, 6)):
            who, proj = rng.choice(names), rng.choice(PROJECTS)
            fb.add(
                rng.choice(
                    [
                        f"- {rng.choice(TOPICS).capitalize()} with {who} on {proj}; follow-ups filed.",
                        f"- Paired with {who} on the {proj} {rng.choice(['migration', 'dashboard', 'API', 'backfill'])}.",
                        f"- {who} flagged a risk on {proj}: {rng.choice(['scope creep', 'vendor delay', 'flaky tests', 'data quality'])}.",
                        f"- Blocked most of the afternoon for {rng.choice(['deep work', 'reviews', 'writing', 'errands'])}.",
                    ]
                )
            )
        journal[d] = fb
        c.files[fb.path] = fb

    def later_day(after: date) -> FileBuilder:
        opts = [d for d in days if d > after + timedelta(days=20)]
        return journal[rng.choice(opts[-60:]) if opts else days[-1]]

    qn = 0

    def q(qtype: str, text: str, path: str, line: int, **kw) -> None:
        nonlocal qn
        qn += 1
        c.queries.append(Query(f"q{qn:03d}", qtype, text, path, line, **kw))

    # superseded: 36 facts changed later in the journal
    sup_projects = rng.sample(PROJECTS, 18)
    for p in sup_projects:
        field_, label = rng.choice([("lead", "project lead"), ("designer", "designer")])
        old = proj_meta[p][field_]
        new = rng.choice([n for n in names if n != old])
        fb = later_day(date.fromisoformat(proj_meta[p]["when"]))
        form = rng.random()
        if form < 0.5:
            line = fb.add(f"- {p} {label}: {new} (took over from {old.split()[0]}).")
        else:
            line = fb.add(f"- The {p} {label} is now {new}.")
        q(
            "superseded",
            f"who is the {p} {label}",
            fb.path,
            line,
            old_path=f"projects/{_slug(p)}.md",
            old_line=proj_facts[p][field_],
        )
    sup_people = rng.sample(names, 18)
    for n in sup_people:
        old = contact_meta[n]["company"]
        new = rng.choice([x for x in COMPANIES if x != old])
        fb = later_day(date.fromisoformat(contact_meta[n]["when"]))
        if rng.random() < 0.5:
            line = fb.add(f"- {n} company: {new}, started there last week.")
        else:
            line = fb.add(f"- Caught up with {n.split()[0]}. {n}'s company is now {new}.")
        q(
            "superseded",
            f"{n} company",
            fb.path,
            line,
            old_path=f"contacts/{_slug(n)}.md",
            old_line=contact_facts[n]["company"],
        )

    # lookup + paraphrase
    used = set(sup_people)
    pool = [n for n in names if n not in used]
    rng.shuffle(pool)
    for n in pool[:14]:
        kind = rng.choice(["email", "phone", "role"])
        text = {"email": f"{n} email", "phone": f"{n} phone number", "role": f"{n} role"}[kind]
        q("lookup", text, f"contacts/{_slug(n)}.md", contact_facts[n][kind])
    for n in pool[14:28]:
        pref = PREFS[int(contact_meta[n]["pref"])]
        q("lookup", pref[2].format(name=n), f"contacts/{_slug(n)}.md", contact_facts[n]["pref"])
    for n in pool[28:48]:
        pref = PREFS[int(contact_meta[n]["pref"])]
        q(
            "paraphrase",
            pref[1].format(name=n.split()[0] if rng.random() < 0.5 else n),
            f"contacts/{_slug(n)}.md",
            contact_facts[n]["pref"],
        )
    for n in pool[48:56]:
        q(
            "paraphrase",
            rng.choice([f"where does {n} live", f"which town is {n} based in"]),
            f"contacts/{_slug(n)}.md",
            contact_facts[n]["town"],
        )
    other = [p for p in PROJECTS if p not in sup_projects]
    rng.shuffle(other)
    for p in other[:12]:
        kind = rng.choice(["deadline", "budget", "decision"])
        text = {
            "deadline": f"{p} launch target",
            "budget": f"{p} quarterly budget",
            "decision": f"{p} build pipeline moved to {proj_meta[p]['tool']}",
        }[kind]
        q("lookup", text, f"projects/{_slug(p)}.md", proj_facts[p][kind])
    for p in other[12:26]:
        kind = rng.choice(["deadline", "decision", "reviewer"])
        text = {
            "deadline": f"when is {p} supposed to ship",
            "decision": f"why did we switch the {p} builds",
            "reviewer": f"who reviews security for {p}",
        }[kind]
        q("paraphrase", text, f"projects/{_slug(p)}.md", proj_facts[p][kind])

    # staleness: every place price/hours; flag expected iff verified > 30 days ago
    for name in places[:40]:
        meta = place_meta[name]
        age = (NOW - date.fromisoformat(meta["verified"])).days
        kind = rng.choice(["price", "hours"])
        text = f"how much is a {meta['item']} at {name}" if kind == "price" else f"{name} opening hours"
        q(
            "stale",
            text,
            f"places/{_slug(name)}.md",
            place_facts[name][kind],
            expect_flag=age > 30,
            note=f"verified {meta['verified']} ({age}d)",
        )
    return c


def write(c: Corpus, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for p, fb in c.files.items():
        fp = out / p
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(fb.text(), encoding="utf-8")
        t = _epoch(fb.when)
        os.utime(fp, (t, t))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    c = generate(a.seed)
    write(c, Path(a.out))
    with open(Path(a.out) / "queries.jsonl", "w") as f:
        for qq in c.queries:
            f.write(json.dumps(asdict(qq)) + "\n")
    print(f"{len(c.files)} files, {len(c.queries)} queries -> {a.out}")


if __name__ == "__main__":
    main()
