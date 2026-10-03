"""Command line interface: index, search, explain, diff, add, conflicts, stale, stats, rotate."""

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
    s.add_argument("--as-of", type=_date, default=None, help="search the notes as they stood on this date")
    s.add_argument("--json", action="store_true", help="machine readable output with searched_at and no_match")
    s.add_argument("--no-refresh", action="store_true", help="search the saved index without re-scanning files")

    s = sub.add_parser("explain", help="current value, superseded values and timeline for one fact")
    s.add_argument("question", nargs="+")
    s.add_argument("--as-of", type=_date, default=None, help="the value in effect on this date")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-refresh", action="store_true", help="use the saved index without re-scanning files")

    s = sub.add_parser("diff", help="facts added or updated in a date window")
    s.add_argument("--since", type=_date, required=True)
    s.add_argument("--until", type=_date, default=None)
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-refresh", action="store_true", help="use the saved index without re-scanning files")

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


def _prov(d: dict) -> str:
    """'explicit, user, from 2026-08-14' style summary of a result's metadata, or ''."""
    parts = [d.get("authority"), d.get("source")]
    parts += [f"from {d['valid_from']}" if d.get("valid_from") else None]
    parts += [f"until {d['valid_until']}" if d.get("valid_until") else None]
    return ", ".join(p for p in parts if p)


def _print_hits(resp_dict: dict) -> None:
    print(
        f"searched {resp_dict['files_indexed']} files / {resp_dict['chunks_indexed']} chunks "
        f"(index {resp_dict['index_version']}, {resp_dict['searched_at']})"
        + (f", as of {resp_dict['as_of']}" if resp_dict.get("as_of") else "")
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
        if _prov(r):
            flag += f"  {{{_prov(r)}}}"
        print(f"\n{r['cite']}{flag}")
        if r["heading_path"]:
            print("  " + " > ".join(r["heading_path"]))
        for line in r["text"].splitlines()[:6]:
            print("  " + line)


def _print_explain(r: dict) -> None:
    print(
        f"searched {r['files_indexed']} files / {r['chunks_indexed']} chunks "
        f"(index {r['index_version']}, {r['searched_at']})"
    )
    if r["no_match"]:
        print("no match")
        return
    f = r["fact"]
    if f is None:
        print(f"no fact found: nothing states a value for this question. nearest: {', '.join(r['nearest'])}")
        return
    c = f["current"]
    print(f"\n{f['label']}" + (f"  (as of {r['as_of']})" if r.get("as_of") else ""))
    if c is None:
        why = "nothing recorded by then" if f["status"] == "none" else "only undated entries; cannot tell"
        print(f"  {f['status'].upper()}  {why}")
        return

    def where(e: dict) -> str:
        p = _prov(e)
        return f"({e['cite']}, {e['as_of'] or 'undated'}" + (f"; {p})" if p else ")")

    tag = ""
    if not f["resolved"]:
        tag = (
            "  (UNRESOLVED: an inferred value contradicts an explicit one)"
            if f.get("unresolved_reason") == "inferred-over-explicit"
            else "  (UNRESOLVED: same date as a different value)"
        )
    if f.get("status") not in (None, "known"):
        tag += f"  ({f['status'].upper()})"
    label = "value then  " if r.get("as_of") else "current     "
    print(f"  {label}{c['value']}  {where(c)}{tag}")
    for s in f["superseded"]:
        print(f"  superseded  {s['value']}  {where(s)}")
    for s in f.get("changed_after", []):
        print(f"  later       {s['value']}  {where(s)}")
    fr = f["freshness"]
    age = f", {fr['age_days']}d old" if fr["age_days"] is not None else ""
    print(f"  freshness   {fr['status']}{age}" + ("  must re-verify before asserting" if fr["must_reverify"] else ""))
    if len(f["timeline"]) > 1:
        print("  timeline")
        for t in f["timeline"]:
            print(f"    {t['value']}: {t['from'] or '?'} -> {'present' if t['present'] else t['to'] or '?'}")


def _print_diff(r: dict) -> None:
    print(f"changes since {r['since']}" + (f" until {r['until']}" if r["until"] else ""))
    for row in r["added"]:
        p = _prov(row)
        print(f"  ADDED    {row['label']}: {row['value']}  ({row['cite']}, {row['as_of']}" + (f"; {p})" if p else ")"))
    for row in r["updated"]:
        p = row["previous"]
        prov = _prov(row)
        print(
            f"  UPDATED  {row['label']}: {p['value']} ({p['cite']}, {p['as_of']}) "
            f"-> {row['value']} ({row['cite']}, {row['as_of']}" + (f"; {prov})" if prov else ")")
        )
    if not r["added"] and not r["updated"]:
        print("  no changes")
    if r["undated_skipped"]:
        print(f"  ({r['undated_skipped']} undated assertions skipped)")


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
                " ".join(args.query),
                k=args.k,
                now=args.now,
                mode=args.mode,
                refresh=not args.no_refresh,
                as_of=args.as_of,
            ).to_dict()
            if args.json:
                print(json.dumps(resp, ensure_ascii=False, indent=2))
            else:
                _print_hits(resp)
            return EXIT_NO_MATCH if resp["no_match"] else EXIT_OK
        if args.cmd == "explain":
            r = mem.explain(" ".join(args.question), now=args.now, refresh=not args.no_refresh, as_of=args.as_of)
            if args.json:
                print(json.dumps(r, ensure_ascii=False, indent=2))
            else:
                _print_explain(r)
            return EXIT_NO_MATCH if r["no_match"] or r["no_fact"] else EXIT_OK
        if args.cmd == "diff":
            r = mem.diff(args.since, args.until, refresh=not args.no_refresh)
            if args.json:
                print(json.dumps(r, ensure_ascii=False, indent=2))
            else:
                _print_diff(r)
            return EXIT_OK
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
