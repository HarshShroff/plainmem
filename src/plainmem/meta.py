"""Optional metadata tag at the end of a fact line.

A tag is a brace group at the very end of a line, comma separated, items in any order::

    - Orion project lead: Sam Okafor {explicit, user}
    - Orion deploy region: eu-west-2 {observed, tool, from 2026-08-14}
    - Orion budget freeze: yes {explicit, user, until 2026-12-31}
    - Priya took over from Sam on Orion {explicit, user, supersedes Orion project lead}

Items:

* authority, one of ``explicit`` (a person stated it), ``observed`` (read from a
  system or tool output), ``inferred`` (an agent concluded it), ``imported``
  (copied in from another document or system)
* source, one of ``user``, ``tool``, ``agent``, ``document``
* ``from YYYY-MM-DD``: the fact is true from this date (default: the line's date)
* ``until YYYY-MM-DD``: the fact is true up to and including this date
* ``supersedes <key>``: this line replaces the current value of ``<key>``, for
  updates whose wording does not repeat the key

A brace group with anything else in it is ordinary text, not a tag, so ``{x}`` in
prose is left alone. Untagged lines behave exactly as before. The vocabulary is
fixed on purpose: authority is a category, never a number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

AUTHORITIES = ("explicit", "observed", "imported", "inferred")
SOURCES = ("user", "tool", "agent", "document")
# Same-date tie-break only: a stated fact beats one read from a tool beats one copied in beats a guess.
AUTHORITY_RANK = {a: len(AUTHORITIES) - n for n, a in enumerate(AUTHORITIES)}

_TAG_RE = re.compile(r"[ \t]*\{([^{}\n]*)\}[ \t]*$", re.MULTILINE)
_DATE_ITEM_RE = re.compile(r"^(from|until)\s+(\d{4}-\d{2}-\d{2})$")
_SUPERSEDES_RE = re.compile(r"^supersedes:?\s+(\S.{0,60})$")


@dataclass(frozen=True)
class FactMeta:
    authority: str | None = None
    source: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    supersedes: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "authority": self.authority,
            "source": self.source,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "supersedes": self.supersedes,
        }


EMPTY = FactMeta()


def parse_tag(body: str) -> FactMeta | None:
    """Parse the inside of a brace group. None when it is not a valid tag."""
    fields: dict[str, object] = {}
    items = [s.strip() for s in body.split(",")]
    if not items or not all(items):
        return None
    for item in items:
        low = item.lower()
        m = _DATE_ITEM_RE.match(low)
        sm = _SUPERSEDES_RE.match(item)
        if low in AUTHORITIES:
            name, value = "authority", low
        elif low in SOURCES:
            name, value = "source", low
        elif m:
            try:
                d = date.fromisoformat(m.group(2))
            except ValueError:
                return None
            name, value = ("valid_from" if m.group(1) == "from" else "valid_until"), d
        elif sm:
            name, value = "supersedes", sm.group(1).strip()
        else:
            return None
        if name in fields:
            return None
        fields[name] = value
    meta = FactMeta(**fields)  # type: ignore[arg-type]
    if meta.valid_from and meta.valid_until and meta.valid_until < meta.valid_from:
        return None
    return meta


def split_line(line: str) -> tuple[str, FactMeta | None]:
    """A line without its trailing tag, plus the tag (None when there is none)."""
    m = _TAG_RE.search(line)
    if not m:
        return line, None
    meta = parse_tag(m.group(1))
    if meta is None:
        return line, None
    return line[: m.start()], meta


def strip_tags(text: str) -> str:
    """Remove valid trailing tags from every line, leaving any other brace text alone."""
    return _TAG_RE.sub(lambda m: "" if parse_tag(m.group(1)) is not None else m.group(0), text)
