"""The on-disk index: a disposable JSON cache of parsed Markdown.

The Markdown files are the source of truth. The index only saves re-parsing and
re-tokenizing, and it can always be deleted and rebuilt. Because of that it
fails closed: a truncated, edited or schema-mismatched index raises
``IndexCorruptError`` instead of quietly serving partial results.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .engine import chunk_tokens
from .markdown import Chunk, Document, parse, parse_date

SCHEMA = 1
INDEX_DIRNAME = ".plainmem"
INDEX_FILENAME = "index.json"
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
SKIP_DIRS = frozenset({".git", ".plainmem", "node_modules", ".venv", "venv", "__pycache__"})


class IndexCorruptError(RuntimeError):
    """The index file exists but cannot be trusted. Rebuild it from the Markdown."""


class IndexMissingError(RuntimeError):
    """No index yet. Run `plainmem index` first."""


@dataclass
class FileEntry:
    mtime: float
    size: int
    sha1: str


@dataclass
class IndexData:
    root: str
    docs: dict[str, Document] = field(default_factory=dict)
    files: dict[str, FileEntry] = field(default_factory=dict)
    tokens: dict[str, list[list[str]]] = field(default_factory=dict)
    built_at: str = ""
    skipped: list[str] = field(default_factory=list)

    @property
    def version(self) -> str:
        """Content hash of what was indexed: same files, same version."""
        h = hashlib.sha256()
        for p in sorted(self.files):
            h.update(p.encode())
            h.update(self.files[p].sha1.encode())
        return h.hexdigest()[:12]

    def ordered_docs(self) -> list[Document]:
        return [self.docs[p] for p in sorted(self.docs)]

    def ordered_tokens(self) -> list[list[str]]:
        out: list[list[str]] = []
        for p in sorted(self.docs):
            out.extend(self.tokens.get(p, []))
        return out


def scan(root: Path) -> list[Path]:
    """Markdown files under root, skipping hidden tool dirs and symlink loops."""
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if fn.lower().endswith((".md", ".markdown")):
                out.append(Path(dirpath) / fn)
    return out


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def read_doc(root: Path, path: Path) -> tuple[Document, FileEntry]:
    data = path.read_bytes()
    st = path.stat()
    text = data.decode("utf-8", errors="replace")
    rel = path.relative_to(root).as_posix()
    doc = parse(rel, text, st.st_mtime)
    return doc, FileEntry(st.st_mtime, st.st_size, _sha1(data))


def build(root: Path, previous: IndexData | None = None, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[IndexData, dict]:
    """Build or incrementally update an index. Unchanged files (same mtime+size, or same hash) are reused."""
    root = root.resolve()
    data = IndexData(root=str(root))
    stats = {"added": 0, "updated": 0, "unchanged": 0, "removed": 0, "skipped": 0}
    prev = previous if previous and previous.root == str(root) else None
    seen: set[str] = set()
    for path in scan(root):
        rel = path.relative_to(root).as_posix()
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_size > max_bytes:
            data.skipped.append(rel)
            stats["skipped"] += 1
            continue
        seen.add(rel)
        old = prev.files.get(rel) if prev else None
        if prev and old and old.mtime == st.st_mtime and old.size == st.st_size and rel in prev.docs:
            data.docs[rel], data.files[rel], data.tokens[rel] = prev.docs[rel], old, prev.tokens[rel]
            stats["unchanged"] += 1
            continue
        doc, entry = read_doc(root, path)
        if prev and old and old.sha1 == entry.sha1 and rel in prev.docs:
            prev.docs[rel].mtime = entry.mtime
            data.docs[rel], data.files[rel], data.tokens[rel] = prev.docs[rel], entry, prev.tokens[rel]
            stats["unchanged"] += 1
            continue
        data.docs[rel], data.files[rel] = doc, entry
        data.tokens[rel] = [chunk_tokens(c) for c in doc.chunks]
        stats["updated" if old else "added"] += 1
    if prev:
        stats["removed"] = len(set(prev.files) - seen)
    data.built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return data, stats


# --- serialisation ------------------------------------------------------------


def _chunk_to_json(c: Chunk) -> dict:
    return {
        "s": c.start_line,
        "e": c.end_line,
        "t": c.text,
        "h": c.heading_path,
        "k": c.kind,
        "v": c.verified.isoformat() if c.verified else None,
        "vs": c.date_source,
        "vol": c.volatile,
    }


def _chunk_from_json(path: str, d: dict) -> Chunk:
    return Chunk(
        path=path,
        start_line=int(d["s"]),
        end_line=int(d["e"]),
        text=str(d["t"]),
        heading_path=[str(h) for h in d["h"]],
        kind=str(d["k"]),
        verified=parse_date(d["v"]) if d["v"] else None,
        date_source=str(d["vs"]),
        volatile=bool(d["vol"]),
    )


def to_json(data: IndexData) -> str:
    payload = {
        "root": data.root,
        "built_at": data.built_at,
        "skipped": data.skipped,
        "files": {p: [e.mtime, e.size, e.sha1] for p, e in sorted(data.files.items())},
        "docs": {
            p: {
                "meta": d.meta,
                "mtime": d.mtime,
                "chunks": [_chunk_to_json(c) for c in d.chunks],
                "tokens": data.tokens[p],
            }
            for p, d in sorted(data.docs.items())
        },
    }
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(body.encode()).hexdigest()
    return json.dumps({"schema": SCHEMA, "checksum": checksum, "payload": body}, ensure_ascii=False)


def from_json(text: str) -> IndexData:
    try:
        outer = json.loads(text)
        if not isinstance(outer, dict) or outer.get("schema") != SCHEMA:
            raise IndexCorruptError(
                f"index schema {outer.get('schema') if isinstance(outer, dict) else '?'} != {SCHEMA}"
            )
        body = outer["payload"]
        if hashlib.sha256(body.encode()).hexdigest() != outer["checksum"]:
            raise IndexCorruptError("index checksum mismatch")
        p = json.loads(body)
        data = IndexData(root=p["root"], built_at=p["built_at"], skipped=list(p["skipped"]))
        for path, (mtime, size, sha1) in p["files"].items():
            data.files[path] = FileEntry(float(mtime), int(size), str(sha1))
        for path, d in p["docs"].items():
            chunks = [_chunk_from_json(path, c) for c in d["chunks"]]
            data.docs[path] = Document(path=path, text="", mtime=float(d["mtime"]), meta=dict(d["meta"]), chunks=chunks)
            toks = d["tokens"]
            if len(toks) != len(chunks):
                raise IndexCorruptError(f"token/chunk count mismatch in {path}")
            data.tokens[path] = toks
        if set(data.files) != set(data.docs):
            raise IndexCorruptError("file manifest does not match documents")
        return data
    except IndexCorruptError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise IndexCorruptError(f"unreadable index: {e.__class__.__name__}: {e}") from e


def index_path(root: Path, index_dir: Path | None = None) -> Path:
    return (index_dir or (root / INDEX_DIRNAME)) / INDEX_FILENAME


def save(data: IndexData, path: Path) -> int:
    """Atomic write (temp file + rename). Returns bytes written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = to_json(data).encode()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".index-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return len(blob)


def load(path: Path) -> IndexData:
    if not path.exists():
        raise IndexMissingError(f"no index at {path}; run `plainmem index`")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise IndexCorruptError(f"index is not valid UTF-8: {e}") from e
    return from_json(text)
