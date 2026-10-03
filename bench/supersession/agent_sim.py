"""Arm B of the supersession benchmark: a SIMULATED writing agent that may declare ``supersedes``.

This is a simulation, not a measurement of any real agent. One model call plays an agent that has
the plainmem skill file (``skills/plainmem-memory/SKILL.md``) as its instructions, is about to save
a note, and has just called the ``candidates`` tool. It sees only those three things: the skill
file, the note and the tool output. It never sees the category, the gold verdict or the question.
It answers with the ``supersedes`` argument it would pass to ``add`` (a key, or null).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

SKILL = (Path(__file__).resolve().parents[2] / "skills" / "plainmem-memory" / "SKILL.md").read_text(encoding="utf-8")

PROMPT = """You are an AI agent with a long-term memory tool called plainmem. These are your instructions for it:

<skill>
{skill}
</skill>

You are about to save this note with `add`:
{note}

You called `candidates` with the note. It returned:
{tool_output}

Now make the `add` call. Reply with only a JSON object: {{"supersedes": "<key>"}} or {{"supersedes": null}}"""


def build_prompt(note: str, candidates: list[dict[str, Any]]) -> str:
    # sorted by key, so the prompt does not change when scores shift slightly as the log grows
    shown = [{k: c[k] for k in ("key", "value", "cite", "as_of")} for c in sorted(candidates, key=lambda c: c["key"])]
    tool_output = json.dumps({"count": len(shown), "candidates": shown}, indent=1)
    return PROMPT.format(skill=SKILL.strip(), note=" ".join(note.split()), tool_output=tool_output)


def parse(reply: Any) -> tuple[bool, str | None]:
    """(parsed, key). Strict: one JSON object with a ``supersedes`` string or null, code fences allowed."""
    if not isinstance(reply, str):
        return False, None
    body = reply.strip()
    if body.startswith("```"):
        body = body.strip("`").removeprefix("json").strip()
    try:
        obj = json.loads(body)
    except ValueError:
        return False, None
    if not isinstance(obj, dict) or "supersedes" not in obj:
        return False, None
    key = obj["supersedes"]
    if key is not None and not isinstance(key, str):
        return False, None
    return True, (key.strip() or None) if isinstance(key, str) else None


class SimulatedAgent:
    """``(note, candidates) -> raw verdict`` so the same validator applies; counts calls and parse failures."""

    def __init__(self, complete: Callable[[str], str]) -> None:
        self.complete = complete
        self.calls = 0
        self.failures = 0

    def __call__(self, note: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        try:
            ok, key = parse(self.complete(build_prompt(note, candidates)))
        except Exception as e:  # noqa: BLE001 - a failed call is "passed nothing"
            ok, key = False, None
            err = str(e)[:200]
        else:
            err = "unparsable reply"
        if not ok:
            self.failures += 1
            return {"relation": "unrelated", "target": None, "reason": f"agent: {err}", "declared": False}
        if key is None:
            return {"relation": "unrelated", "target": None, "reason": "agent passed nothing", "declared": False}
        return {"relation": "supersedes", "target": key, "reason": "agent passed supersedes", "declared": True}
