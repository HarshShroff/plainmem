"""MCP server exposing search, explain, diff, candidates, add and stale over stdio.

The tool bodies are plain functions (``tool_search`` etc.) so they can be tested
without the SDK. The MCP Python SDK (``pip install mcp``) is imported only when
the server actually starts.

    plainmem-mcp --root ~/notes
"""

from __future__ import annotations

import argparse
from typing import Any

from .markdown import parse_date
from .memory import Memory


def _day(s: str | None) -> Any:
    """Optional YYYY-MM-DD argument. A malformed date is an error, never silently ignored."""
    if not s:
        return None
    d = parse_date(s)
    if d is None or len(s.strip()) != 10:
        raise ValueError(f"expected YYYY-MM-DD, got {s!r}")
    return d


def tool_search(mem: Memory, query: str, k: int = 5, as_of: str | None = None) -> dict[str, Any]:
    """Search notes. Always returns searched_at, index_version and no_match, so a caller can
    show it actually looked before saying there is no record of something."""
    return mem.search(query, k=max(1, min(int(k), 50)), as_of=_day(as_of)).to_dict()


def tool_add(mem: Memory, text: str, supersedes: str | None = None) -> dict[str, Any]:
    """Append a dated entry to log.md (append-only, locked). ``supersedes`` names the key it replaces."""
    return {"appended_to": mem.add(text, supersedes=supersedes or None), "supersedes": supersedes or None}


def tool_candidates(mem: Memory, text: str, k: int = 10) -> dict[str, Any]:
    """Current facts a note about to be added may replace. Read only."""
    items = mem.candidates_for(text, k=max(1, min(int(k), 50)))
    return {"count": len(items), "candidates": items}


def tool_stale(mem: Memory) -> dict[str, Any]:
    """Volatile facts past their re-verification window."""
    items = mem.stale()
    return {"count": len(items), "items": items}


def tool_explain(mem: Memory, question: str, as_of: str | None = None) -> dict[str, Any]:
    """Current answer, superseded values with citations, timeline and freshness for one fact."""
    return mem.explain(question, as_of=_day(as_of))


def tool_diff(mem: Memory, since: str, until: str | None = None) -> dict[str, Any]:
    """Facts added or updated between two dates, inclusive."""
    return mem.diff(_day(since), _day(until))


def build_server(mem: Memory) -> Any:
    try:  # MCP SDK 2.x renamed FastMCP to MCPServer; accept either.
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server
        except ImportError as e:  # pragma: no cover - depends on optional install
            raise SystemExit("plainmem-mcp needs the MCP SDK: pip install 'plainmem[mcp]'") from e

    try:
        from mcp.types import ToolAnnotations
    except ImportError:  # pragma: no cover - depends on optional install
        ToolAnnotations = None  # noqa: N806

    def ann(**kw: Any) -> Any:
        return ToolAnnotations(**kw) if ToolAnnotations else None

    server = Server("plainmem")

    @server.tool(
        title="Search memory",
        annotations=ann(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
    )
    def search(query: str, k: int = 5, as_of: str | None = None) -> dict[str, Any]:
        """Search long-term Markdown memory. Results carry file:line citations, FRESH/AGING/STALE/SUPERSEDED/EXPIRED
        status and provenance (authority, source, valid_from, valid_until) when the note is tagged. as_of
        (YYYY-MM-DD) searches the notes as they stood on that date. Check no_match before claiming something is
        not recorded."""
        return tool_search(mem, query, k, as_of)

    @server.tool(
        title="Add note",
        annotations=ann(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False),
    )
    def add(text: str, supersedes: str | None = None) -> dict[str, Any]:
        """Append a dated note to the memory log. If the note replaces a fact whose key it does not repeat,
        pass that key (as returned by candidates) in supersedes; if unsure, leave it out."""
        return tool_add(mem, text, supersedes)

    @server.tool(
        title="Candidate facts for a new note",
        annotations=ann(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
    )
    def candidates(text: str, k: int = 10) -> dict[str, Any]:
        """Before add: list current facts (key, value, citation) the new note may replace. Pass a key from this
        list as add's supersedes only when the note clearly replaces that value."""
        return tool_candidates(mem, text, k)

    @server.tool(
        title="List stale facts",
        annotations=ann(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
    )
    def stale() -> dict[str, Any]:
        """List volatile facts (prices, status, availability) that must be re-verified before asserting."""
        return tool_stale(mem)

    @server.tool(
        title="Explain a fact",
        annotations=ann(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
    )
    def explain(question: str, as_of: str | None = None) -> dict[str, Any]:
        """Explain how the answer to a question changed: current value, superseded values, timeline,
        freshness and provenance, each with file:line citations. as_of (YYYY-MM-DD) gives the value in effect on
        that date with a status of known/uncertain/expired/none/unknown. Check no_match and no_fact before
        claiming nothing is recorded."""
        return tool_explain(mem, question, as_of)

    @server.tool(
        title="Diff facts between dates",
        annotations=ann(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
    )
    def diff(since: str, until: str | None = None) -> dict[str, Any]:
        """Facts added or updated between two dates (YYYY-MM-DD, inclusive), with the previous value, citations
        and provenance."""
        return tool_diff(mem, since, until)

    return server


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - needs a live MCP client
    p = argparse.ArgumentParser(prog="plainmem-mcp")
    p.add_argument("--root", default=".")
    args = p.parse_args(argv)
    build_server(Memory(args.root)).run()


if __name__ == "__main__":  # pragma: no cover
    main()
