"""Reference LLM classifier for write-path consolidation. Not imported by the core package.

    from plainmem.consolidate_llm import LLMClassifier, claude_cli
    clf = LLMClassifier(claude_cli(model="haiku"))
    mem.consolidate("Priya took over from Sam on Orion.", clf)

``LLMClassifier`` takes any ``complete(prompt) -> str`` function, so another model or API can be
plugged in. It builds one short prompt, parses the reply strictly and returns a verdict dict; it
never touches files. Whatever the model says, ``Memory.consolidate`` still validates it: the
target has to be one of the candidates shown, and only ``supersedes`` writes a tag.

Parsing is strict: the reply must contain one JSON object with a ``relation``. Anything else is
returned as ``unrelated`` (no change).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

SYSTEM = "You classify notes for a memory system. Reply with one JSON object and nothing else."

PROMPT = """A new note is about to be saved. Decide whether it changes one of the facts on file.

Relations:
- supersedes: the note says the fact now has a different value than the one on file (a handover, \
replacement, migration, switch, move). The change must be stated as having happened.
- refines: the note adds detail to the same value without changing it.
- contradicts: the note disagrees with the value on file but does not say it changed.
- unrelated: the note is about something else, or only mentions the same entity, person or \
thing without saying it now holds the fact.
- insufficient: it might be a change, but the note is tentative, partial, temporary, only planned \
or only implied.
If unsure between supersedes and anything else, answer insufficient.

target: the exact key from the list for supersedes, refines or contradicts; otherwise null.

New note: {note}

Facts on file (key: current value):
{facts}

Reply with only: {{"relation": "...", "target": "<key>" or null, "reason": "<at most 15 words>"}}"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def build_prompt(new_text: str, candidates: list[dict[str, Any]]) -> str:
    facts = "\n".join(f"- {c['key']}: {c['value']}" for c in candidates)
    return PROMPT.format(note=" ".join(new_text.split()), facts=facts)


def parse_verdict(text: Any) -> dict[str, Any] | None:
    """The single JSON object in a reply, or None. Code fences are allowed, prose around the object is not."""
    if not isinstance(text, str):
        return None
    body = _FENCE_RE.sub("", text.strip()).strip()
    try:
        obj = json.loads(body)
    except ValueError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("relation"), str):
        return None
    target = obj.get("target")
    if target is not None and not isinstance(target, str):
        return None
    return {"relation": obj["relation"], "target": target, "reason": str(obj.get("reason") or "")}


class LLMClassifier:
    """``classifier(new_text, candidates) -> verdict`` backed by ``complete(prompt) -> str``.

    ``calls`` counts model calls; ``failures`` counts calls that raised or returned something unparsable.
    """

    def __init__(self, complete: Callable[[str], str]) -> None:
        self.complete = complete
        self.calls = 0
        self.failures = 0

    def __call__(self, new_text: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        try:
            reply = self.complete(build_prompt(new_text, candidates))
        except Exception as e:  # noqa: BLE001 - a failed call means no change
            self.failures += 1
            return {"relation": "unrelated", "target": None, "reason": f"call failed: {e}"[:200]}
        v = parse_verdict(reply)
        if v is None:
            self.failures += 1
            return {"relation": "unrelated", "target": None, "reason": "unparsable reply"}
        return v


def find_claude() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    for p in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude", os.path.expanduser("~/.claude/local/claude")):
        if os.path.exists(p):
            return p
    return None


def claude_cli(model: str = "haiku", binary: str | None = None, timeout: float = 90.0) -> Callable[[str], str]:
    """``complete`` via ``claude -p`` (Claude Code CLI): no tools, no settings, no session saved.

    The returned function has a ``cost_usd`` attribute that adds up the reported cost.
    """
    exe = binary or find_claude()
    if not exe:
        raise FileNotFoundError("claude CLI not found")
    cmd = [exe, "-p", "--model", model, "--output-format", "json", "--tools", "", "--system-prompt", SYSTEM,
           "--no-session-persistence", "--strict-mcp-config", "--setting-sources", ""]  # fmt: skip

    def complete(prompt: str) -> str:
        r = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=tempfile.gettempdir()
        )
        if r.returncode != 0:
            raise RuntimeError(f"claude exited {r.returncode}: {r.stderr.strip()[:200]}")
        out = json.loads(r.stdout)
        complete.cost_usd += float(out.get("total_cost_usd") or 0.0)  # type: ignore[attr-defined]
        if out.get("is_error"):
            raise RuntimeError(str(out.get("result"))[:200])
        return str(out.get("result", ""))

    complete.cost_usd = 0.0  # type: ignore[attr-defined]
    return complete
