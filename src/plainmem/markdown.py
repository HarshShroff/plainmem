"""Split a Markdown document into citable chunks.

A chunk is one paragraph, one list item, one table row or one fenced code
block. Every chunk remembers the file lines it came from and the heading path
above it, so a search hit can be cited as ``path:line`` and read in context.

Front matter is the usual ``---`` block at the top of a file, parsed as flat
``key: value`` pairs (no nested YAML, no dependency on a YAML library).

Inline freshness tags, anywhere in a chunk:

* ``[verified: 2026-05-01]`` the fact was checked on that date
* ``[volatile]`` the fact changes over time (price, status, hours, availability)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

FRONT_MATTER_KEYS = ("verified", "updated", "date", "volatile", "entity", "title")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+")
_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
_VERIFIED_RE = re.compile(r"\[verified:\s*(\d{4}-\d{2}-\d{2})\]", re.IGNORECASE)
_VOLATILE_RE = re.compile(r"\[volatile\]", re.IGNORECASE)
_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


def parse_date(text: str) -> date | None:
    """First valid ISO date (YYYY-MM-DD) in text, or None. Invalid dates like 2026-02-30 are skipped."""
    for m in _DATE_RE.finditer(text or ""):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    return None


def is_date_heading(text: str) -> bool:
    """True when a heading is essentially just a date ('2026-03-14', '2026-03-14 Tue')."""
    d = parse_date(text)
    if d is None:
        return False
    rest = _DATE_RE.sub("", text)
    return len(re.sub(r"[\W_]", "", rest)) <= 9


@dataclass
class Chunk:
    path: str
    start_line: int  # 1-based, inclusive
    end_line: int
    text: str
    heading_path: list[str] = field(default_factory=list)
    kind: str = "paragraph"
    verified: date | None = None  # explicit inline tag, or a dated heading above it
    volatile: bool = False
    date_source: str = ""

    @property
    def cite(self) -> str:
        return f"{self.path}:{self.start_line}"

    def clean_text(self) -> str:
        """Text with inline tags removed, for display and fact extraction."""
        t = _VERIFIED_RE.sub("", self.text)
        t = _VOLATILE_RE.sub("", t)
        return re.sub(r"[ \t]+", " ", t).strip()


@dataclass
class Document:
    path: str
    text: str
    mtime: float = 0.0
    meta: dict[str, str] = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)

    @property
    def title(self) -> str:
        if self.meta.get("title"):
            return self.meta["title"]
        for c in self.chunks:
            if c.heading_path:
                return c.heading_path[0]
        return ""


def split_front_matter(lines: list[str]) -> tuple[dict[str, str], int]:
    """Parse a leading --- block. Returns (meta, number of lines consumed).

    An unterminated block is treated as ordinary text rather than swallowing the file.
    """
    if not lines or lines[0].strip() != "---":
        return {}, 0
    meta: dict[str, str] = {}
    for i in range(1, min(len(lines), 200)):
        line = lines[i]
        if line.strip() in ("---", "..."):
            return meta, i + 1
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip().strip("\"'")
    return {}, 0


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("true", "yes", "1", "y", "on")


def parse(path: str, text: str, mtime: float = 0.0) -> Document:
    """Parse Markdown text into a Document with chunks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    lines = text.split("\n")
    meta, skip = split_front_matter(lines)
    doc = Document(path=path, text=text, mtime=mtime, meta=meta)

    headings: list[tuple[int, str]] = []  # (level, text)
    buf: list[str] = []
    buf_start = 0
    buf_kind = "paragraph"
    in_fence = False

    def heading_path() -> list[str]:
        return [h for _, h in headings]

    def heading_date() -> date | None:
        for _, h in reversed(headings):
            d = parse_date(h)
            if d is not None and is_date_heading(h):
                return d
        return None

    def flush(end_line: int) -> None:
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            chunk = Chunk(
                path=path,
                start_line=buf_start,
                end_line=end_line,
                text=body,
                heading_path=heading_path(),
                kind=buf_kind,
            )
            vm = _VERIFIED_RE.search(body)
            hd = heading_date()
            if vm:
                chunk.verified = parse_date(vm.group(1))
                chunk.date_source = "inline"
            elif hd is not None:
                chunk.verified = hd
                chunk.date_source = "heading"
            chunk.volatile = bool(_VOLATILE_RE.search(body))
            doc.chunks.append(chunk)
        buf = []

    for idx in range(skip, len(lines)):
        lineno = idx + 1
        line = lines[idx]
        if in_fence:
            buf.append(line)
            if _FENCE_RE.match(line):
                in_fence = False
                flush(lineno)
            continue
        if _FENCE_RE.match(line):
            flush(lineno - 1)
            in_fence, buf_start, buf_kind = True, lineno, "code"
            buf.append(line)
            continue
        hm = _HEADING_RE.match(line)
        if hm:
            flush(lineno - 1)
            level = len(hm.group(1))
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, hm.group(2).strip()))
            continue
        if not line.strip():
            flush(lineno - 1)
            continue
        if _LIST_RE.match(line) or line.lstrip().startswith("|"):
            flush(lineno - 1)
            buf_start = lineno
            buf_kind = "table" if line.lstrip().startswith("|") else "item"
            buf.append(line)
            if buf_kind == "table" and set(line.strip()) <= set("|-: "):
                buf = []  # table separator row carries no content
            continue
        if not buf:
            buf_start, buf_kind = lineno, "paragraph"
        buf.append(line)
    flush(len(lines))
    return doc
