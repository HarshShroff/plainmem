"""The write path: an append-only, dated session log with rotation.

Writers take an atomic ``mkdir`` lock. ``mkdir`` either creates the directory
or fails, in one syscall, so two processes can never both think they hold it
(a check-then-create file lock has exactly that race). A lock older than
``stale_after`` seconds is treated as left behind by a crashed writer and broken.

Rotation moves whole dated sections older than ``keep_days`` into
``archive/<log>-YYYY-MM.md`` verbatim. The archive is written and fsynced
before the log is rewritten, and a section already present in the archive is
not appended twice, so a crash at any point can duplicate nothing and lose
nothing.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .markdown import parse_date

LOCK_NAME = ".plainmem.lock"
_SECTION_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b.*$", re.MULTILINE)


class LockTimeout(RuntimeError):
    pass


@contextmanager
def lock(directory: Path, timeout: float = 10.0, stale_after: float = 60.0, poll: float = 0.02) -> Iterator[Path]:
    """Hold an exclusive mkdir lock inside ``directory`` for the duration of the block."""
    lockdir = directory / LOCK_NAME
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.mkdir(lockdir)
            break
        except FileExistsError:
            try:
                age = time.time() - lockdir.stat().st_mtime
            except FileNotFoundError:
                continue  # released between our mkdir and stat; retry at once
            if age > stale_after:
                with suppress(OSError):
                    os.rmdir(lockdir)
                continue
            if time.monotonic() >= deadline:
                raise LockTimeout(f"{lockdir} held by another writer for {age:.1f}s") from None
            time.sleep(poll)
    try:
        yield lockdir
    finally:
        with suppress(FileNotFoundError):
            os.rmdir(lockdir)


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _format_entry(text: str) -> str:
    lines = [ln.rstrip() for ln in text.strip().splitlines()] or [""]
    return "- " + lines[0] + "".join("\n  " + ln if ln else "\n" for ln in lines[1:]) + "\n"


def _last_section_date(text: str) -> date | None:
    found = _SECTION_RE.findall(text)
    return parse_date(found[-1]) if found else None


def append(
    root: Path,
    text: str,
    when: date | datetime | None = None,
    logfile: str = "log.md",
    timeout: float = 10.0,
) -> Path:
    """Append one entry under today's ``## YYYY-MM-DD`` heading, creating it if needed."""
    if not text or not text.strip():
        raise ValueError("empty entry")
    if isinstance(when, datetime):
        day = (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date()
    else:
        day = when or datetime.now(timezone.utc).date()
    root.mkdir(parents=True, exist_ok=True)
    path = root / logfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with lock(path.parent, timeout=timeout):
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        chunk = ""
        if not existing:
            chunk += "# Log\n"
        if _last_section_date(existing) != day:
            chunk += ("" if existing.endswith("\n\n") or not existing else "\n") + f"\n## {day.isoformat()}\n\n"
        elif existing and not existing.endswith("\n"):
            chunk += "\n"
        chunk += _format_entry(text)
        with open(path, "a", encoding="utf-8") as f:
            f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
    return path


@dataclass
class Section:
    day: date
    text: str


def split_sections(text: str) -> tuple[str, list[Section]]:
    """Preamble plus dated sections, each section's text verbatim."""
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return text, []
    preamble = text[: matches[0].start()]
    sections = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        d = parse_date(m.group(1))
        sections.append(Section(d or date.min, text[m.start() : end]))
    return preamble, sections


def rotate(root: Path, keep_days: int, now: date | None = None, logfile: str = "log.md") -> dict:
    """Move sections older than ``keep_days`` to monthly archive files. Returns counts."""
    now = now or datetime.now(timezone.utc).date()
    cutoff = now - timedelta(days=keep_days)
    path = root / logfile
    if not path.exists():
        return {"archived": 0, "kept": 0, "files": []}
    stem = Path(logfile).stem
    with lock(path.parent):
        text = path.read_text(encoding="utf-8")
        preamble, sections = split_sections(text)
        old = [s for s in sections if s.day < cutoff and s.day != date.min]
        keep = [s for s in sections if s not in old]
        if not old:
            return {"archived": 0, "kept": len(keep), "files": []}
        archive_dir = path.parent / "archive"
        archive_dir.mkdir(exist_ok=True)
        touched: list[str] = []
        by_month: dict[str, list[Section]] = {}
        for s in old:
            by_month.setdefault(f"{s.day:%Y-%m}", []).append(s)
        for month, secs in sorted(by_month.items()):
            ap = archive_dir / f"{stem}-{month}.md"
            current = ap.read_text(encoding="utf-8") if ap.exists() else f"# {stem} archive {month}\n\n"
            add = "".join(
                s.text if s.text.endswith("\n") else s.text + "\n" for s in secs if s.text.strip() not in current
            )
            if add:
                _atomic_write(ap, current + ("" if current.endswith("\n") else "\n") + add)
            touched.append(ap.relative_to(root).as_posix())
        _atomic_write(path, preamble + "".join(s.text for s in keep))
    return {"archived": len(old), "kept": len(keep), "files": touched}
