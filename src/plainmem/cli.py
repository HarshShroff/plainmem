"""Command line interface: index, search, add, conflicts, stale, stats, rotate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .freshness import FreshnessConfig
from .index import IndexCorruptError, IndexMissingError
from .log import LockTimeout
from .markdown import parse_date
from .memory import Memory

EXIT_OK, EXIT_NO_MATCH, EXIT_USAGE, EXIT_CORRUPT = 0, 1, 2, 3


def _date(s: str) -> date:
    d = parse_date(s)
    if d is None or len(s.strip()) != 10:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {s!r}")
    return d


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="plainmem", description="Markdown-first memory with freshness awareness.")
    p.add_argument("--version", action="version", version=f"plainmem {__version__}")
    p.add_argument("--root", default=".", help="notes directory (default: current directory)")
    p.add_argument("--index-dir", default=None, help="where to keep the index (default: <root>/.plainmem)")
    p.add_argument("--volatile-days", type=int, default=30, help="window after which volatile facts need re-checking")
    p.add_argument("--now", type=_date, default=None, help="pretend today is this date (for testing)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("index", help="build or refresh the index")
    s.add_argument("--rebuild", action="store_true", help="ignore the existing index and rebuild from scratch")

    s = sub.add_parser("search", help="ranked search with citations and freshness")
    s.add_argument("query", nargs="+")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--mode", choices=["full", "bm25"], default="full")
    s.add_argument("--json", action="store_true", help="machine readable output with searched_at and no_match")
    s.add_argument("--no-refresh", action="store_true", help="search the saved index without re-scanning files")

    s = sub.add_parser("add", help="append a dated entry to the log")
    s.add_argument("text", nargs="+")
    s.add_argument("--log", default="log.md")
    s.add_argument("--date", type=_date, default=None)

    s = sub.add_parser("conflicts", help="facts asserted with different values, newest first")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("stale", help="volatile facts past their window")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("stats", help="index size, counts and version")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("rotate", help="move old dated log sections to archive/, verbatim")
    s.add_argument("--keep-days", type=int, default=14)
    s.add_argument("--log", default="log.md")
    return p


def _print_hits(resp_dict: dict) -> None:
    print(
        f"searched {resp_dict['files_indexed']} files / {resp_dict['chunks_indexed']} chunks "
        f"(index {resp_dict['index_version']}, {resp_dict['searched_at']})"
    )
    if resp_dict["no_match"]:
        print("no match")
        return
    for r in resp_dict["results"]:
        flag = f"  [{r['status']}"
        if r["age_days"] is not None:
            flag += f", {r['age_days']}d"
        flag += "]"
        if r["must_reverify"]:
            flag += " must re-verify before asserting"
        if r["superseded_by"]:
            flag += f" superseded by {', '.join(r['superseded_by'])}"
        print(f"\n{r['cite']}{flag}")
        if r["heading_path"]:
            print("  " + " > ".join(r["heading_path"]))
        for line in r["text"].splitlines()[:6]:
            print("  " + line)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"plainmem: {root} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    mem = Memory(root, args.index_dir, cfg=FreshnessConfig(volatile_window_days=args.volatile_days))
    try:
        if args.cmd == "index":
            print(json.dumps(mem.index(rebuild=args.rebuild)))
            return EXIT_OK
        if args.cmd == "search":
            resp = mem.search(
                " ".join(args.query), k=args.k, now=args.now, mode=args.mode, refresh=not args.no_refresh
            ).to_dict()
            if args.json:
                print(json.dumps(resp, ensure_ascii=False, indent=2))
            else:
                _print_hits(resp)
            return EXIT_NO_MATCH if resp["no_match"] else EXIT_OK
        if args.cmd == "add":
            where = mem.add(" ".join(args.text), when=args.date or args.now, logfile=args.log)
            print(f"appended to {where}")
            return EXIT_OK
        if args.cmd == "conflicts":
            out = mem.conflicts()
            if args.json:
                print(json.dumps(out, ensure_ascii=False, indent=2))
            else:
                for c in out:
                    tag = "" if c["resolved"] else "  (UNRESOLVED: same date)"
                    print(f"{c['label']}{tag}")
                    print(f"  current     {c['current']['cite']}  {c['current']['value']}  ({c['current']['as_of']})")
                    for s in c["superseded"]:
                        print(f"  SUPERSEDED  {s['cite']}  {s['value']}  ({s['as_of']})")
                print(f"{len(out)} conflicting keys")
            return EXIT_OK
        if args.cmd == "stale":
            out = mem.stale(now=args.now)
            if args.json:
                print(json.dumps(out, ensure_ascii=False, indent=2))
            else:
                for r in out:
                    print(f"{r['cite']}  {r['age_days']}d  {r['text'].splitlines()[0][:100]}")
                print(f"{len(out)} volatile facts need re-verifying")
            return EXIT_OK
        if args.cmd == "stats":
            out = mem.stats(now=args.now)
            print(json.dumps(out, indent=2) if args.json else "\n".join(f"{k}: {v}" for k, v in out.items()))
            return EXIT_OK
        if args.cmd == "rotate":
            print(json.dumps(mem.rotate(args.keep_days, now=args.now, logfile=args.log)))
            return EXIT_OK
    except IndexCorruptError as e:
        print(
            f"plainmem: index is corrupt ({e}). Refusing to search it. "
            f"Run `plainmem index --rebuild`; your Markdown is untouched.",
            file=sys.stderr,
        )
        return EXIT_CORRUPT
    except IndexMissingError as e:
        print(f"plainmem: {e}", file=sys.stderr)
        return EXIT_USAGE
    except LockTimeout as e:
        print(f"plainmem: {e}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
