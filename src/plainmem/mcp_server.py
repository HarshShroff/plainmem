"""MCP server exposing search, add and stale over stdio.

The tool bodies are plain functions (``tool_search`` etc.) so they can be tested
without the SDK. The MCP Python SDK (``pip install mcp``) is imported only when
the server actually starts.

    plainmem-mcp --root ~/notes
"""

from __future__ import annotations

import argparse
from typing import Any

from .memory import Memory


def tool_search(mem: Memory, query: str, k: int = 5) -> dict[str, Any]:
    """Search notes. Always returns searched_at, index_version and no_match, so a caller can
    show it actually looked before saying there is no record of something."""
    return mem.search(query, k=max(1, min(int(k), 50))).to_dict()


def tool_add(mem: Memory, text: str) -> dict[str, Any]:
    """Append a dated entry to log.md (append-only, locked)."""
    return {"appended_to": mem.add(text)}


def tool_stale(mem: Memory) -> dict[str, Any]:
    """Volatile facts past their re-verification window."""
    items = mem.stale()
    return {"count": len(items), "items": items}


def tool_explain(mem: Memory, question: str) -> dict[str, Any]:
    """Current answer, superseded values with citations, timeline and freshness for one fact."""
    return mem.explain(question)


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
    def search(query: str, k: int = 5) -> dict[str, Any]:
        """Search long-term Markdown memory. Results carry file:line citations and FRESH/AGING/STALE/SUPERSEDED
        status. Check no_match before claiming something is not recorded."""
        return tool_search(mem, query, k)

    @server.tool(
        title="Add note",
        annotations=ann(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False),
    )
    def add(text: str) -> dict[str, Any]:
        """Append a dated note to the memory log."""
        return tool_add(mem, text)

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
    def explain(question: str) -> dict[str, Any]:
        """Explain how the answer to a question changed: current value, superseded values, timeline and
        freshness, each with file:line citations. Check no_match and no_fact before claiming nothing is recorded."""
        return tool_explain(mem, question)

    return server


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - needs a live MCP client
    p = argparse.ArgumentParser(prog="plainmem-mcp")
    p.add_argument("--root", default=".")
    args = p.parse_args(argv)
    build_server(Memory(args.root)).run()


if __name__ == "__main__":  # pragma: no cover
    main()
