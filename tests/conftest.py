from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

NOW = date(2026, 9, 29)


def epoch(d: date) -> float:
    return datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc).timestamp()


def write(root: Path, rel: str, text: str, when: date | None = None) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if when:
        os.utime(p, (epoch(when), epoch(when)))
    return p


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    root = tmp_path / "notes"
    write(
        root,
        "projects/orion.md",
        "---\nverified: 2025-11-02\n---\n# Orion\n\n## People\n\n- Project lead: Dana Whit\n- Designer: Lee Park\n\n"
        "## Notes\n\nThe team is relocating the build to a new runner.\n",
    )
    write(
        root,
        "journal/2026-08-14.md",
        "# 2026-08-14\n\n- Orion project lead: Sam Okafor (took over from Dana).\n- Lunch with Lee.\n",
    )
    write(
        root,
        "places/gym.md",
        "# Brightwater Gym\n\n- A day pass currently costs $18. [verified: 2026-03-01]\n"
        "- Hours: daily 6am-10pm [verified: 2026-09-20]\n- Parking out back.\n",
        when=date(2026, 3, 1),
    )
    return root
