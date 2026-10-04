"""The library on disk: one SQLite file with sources, passages, an FTS5 index
over normalised passage text, and quantised embeddings.

Readers never block the crawler (WAL); one writer at a time."""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .. import text as tx

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sources(
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    doc_url TEXT,
    final_url TEXT,
    title TEXT,
    kind TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    http_status INTEGER,
    detail TEXT,
    fetched_at REAL,
    checked_at REAL,
    etag TEXT,
    last_modified TEXT,
    sha256 TEXT,
    pages INTEGER,
    chars INTEGER,
    chunks INTEGER DEFAULT 0,
    partial INTEGER DEFAULT 0,
    entry_ids TEXT,
    sections TEXT,
    attempts INTEGER DEFAULT 0,
    next_try REAL DEFAULT 0,
    extract_version INTEGER
);
CREATE TABLE IF NOT EXISTS chunks(
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    page INTEGER,
    heading TEXT,
    text TEXT NOT NULL,
    normv INTEGER
);
CREATE INDEX IF NOT EXISTS chunks_by_source ON chunks(source_id, ord);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(norm, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS vectors(chunk_id INTEGER PRIMARY KEY, vec BLOB NOT NULL);
"""

STEM_PREFIX = "zz"  # stems ride in the same FTS column with a prefix unicode61 keeps

# Columns added after the first schema; old files gain them in place.
MIGRATIONS = (
    ("sources", "extract_version", "INTEGER"),
    ("chunks", "normv", "INTEGER"),
)


def default_data_dir() -> Path:
    env = os.environ.get("CPU_PERF_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "cpu-perf"


def normalise(text: str) -> str:
    toks = tx.tokens(text)
    stems = {STEM_PREFIX + tx.stem(t) for t in toks if t.isalpha()}
    return " ".join(toks) + " " + " ".join(sorted(stems))


@dataclass
class SourceRow:
    id: int
    url: str
    doc_url: str | None
    final_url: str | None
    title: str | None
    kind: str | None
    status: str
    http_status: int | None
    detail: str | None
    fetched_at: float | None
    checked_at: float | None
    etag: str | None
    last_modified: str | None
    sha256: str | None
    pages: int | None
    chars: int | None
    chunks: int
    partial: int
    entry_ids: list[str]
    sections: list[int]
    attempts: int
    next_try: float
    extract_version: int | None = None


def _retry_locked(step, seconds: float = 30.0):
    """Run an idempotent setup step, again if SQLite reports a lock.

    Opening a new library from several processes at once (two MCP clients
    starting together) races on creating the file and switching it to WAL;
    there SQLite answers "database is locked" at once instead of waiting out
    the busy timeout, so the step is retried with a short random backoff."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            return step()
        except sqlite3.OperationalError as exc:
            if not any(w in str(exc) for w in ("locked", "busy")) or time.monotonic() > deadline:
                raise
            time.sleep(0.02 + random.random() * 0.08)


class Store:
    def __init__(self, path: Path | str, *, readonly: bool = False):
        """readonly opens an existing file as immutable (for evaluation and
        inspection): nothing is written, not even the WAL index."""
        self.path = Path(path)
        self.readonly = readonly
        self._write_lock = threading.Lock()
        self._local = threading.local()
        if not readonly:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _retry_locked(self._create)
        self._vectors = None  # {"ids", "mat", "epoch", "loaded_at", "checked"}
        self.vector_loads = 0  # full reloads of the matrix (a counter, not a clock: Windows ticks coarsely)
        self._vec_lock = threading.Lock()

    def _create(self) -> None:
        """The schema and its migrations; every statement is safe to run twice."""
        con = self._conn()
        con.executescript(SCHEMA)
        con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema', ?)", (SCHEMA_VERSION,))
        for table, col, typ in MIGRATIONS:
            have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            if col not in have:
                try:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc):
                        raise  # a lock is retried by _retry_locked; another process adding it first is fine

    # ----- connections --------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            if self.readonly:
                uri = self.path.resolve().as_uri() + "?immutable=1"
                con = sqlite3.connect(uri, uri=True, check_same_thread=False)
            else:
                con = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
                _retry_locked(lambda: con.execute("PRAGMA journal_mode=WAL"))
                con.execute("PRAGMA synchronous=NORMAL")
                con.execute("PRAGMA foreign_keys=ON")
            con.row_factory = sqlite3.Row
            self._local.con = con
        return con

    def close(self) -> None:
        con = getattr(self._local, "con", None)
        if con is not None:
            con.close()
            self._local.con = None

    # ----- meta ----------------------------------------------------------------

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._write_lock:
            self._conn().execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))

    def generation(self) -> int:
        """Bumped by every write to sources, passages or vectors, in any process."""
        return int(self.get_meta("gen", "0") or 0)

    @staticmethod
    def _bump(con: sqlite3.Connection, key: str = "gen") -> None:
        con.execute(
            "INSERT INTO meta(key, value) VALUES(?, '1') "
            "ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(value AS INTEGER) + 1 AS TEXT)",
            (key,),
        )

    # ----- sources ---------------------------------------------------------------

    def _row(self, r: sqlite3.Row) -> SourceRow:
        return SourceRow(
            id=r["id"],
            url=r["url"],
            doc_url=r["doc_url"],
            final_url=r["final_url"],
            title=r["title"],
            kind=r["kind"],
            status=r["status"],
            http_status=r["http_status"],
            detail=r["detail"],
            fetched_at=r["fetched_at"],
            checked_at=r["checked_at"],
            etag=r["etag"],
            last_modified=r["last_modified"],
            sha256=r["sha256"],
            pages=r["pages"],
            chars=r["chars"],
            chunks=r["chunks"] or 0,
            partial=r["partial"] or 0,
            entry_ids=json.loads(r["entry_ids"] or "[]"),
            sections=json.loads(r["sections"] or "[]"),
            attempts=r["attempts"] or 0,
            next_try=r["next_try"] or 0,
            extract_version=r["extract_version"] if "extract_version" in r.keys() else None,
        )

    def ensure_sources(self, targets) -> None:
        """Register crawl targets (corpus.CrawlTarget) without touching fetched state."""
        with self._write_lock:
            con = self._conn()
            con.execute("BEGIN")
            for t in targets:
                con.execute(
                    "INSERT INTO sources(url, title, entry_ids, sections) VALUES(?,?,?,?) "
                    "ON CONFLICT(url) DO UPDATE SET entry_ids=excluded.entry_ids, sections=excluded.sections, "
                    "title=COALESCE(sources.title, excluded.title)",
                    (t.url, t.title, json.dumps(t.entry_ids), json.dumps(t.sections)),
                )
            self._bump(con)
            con.execute("COMMIT")

    def source(self, url: str) -> SourceRow | None:
        r = self._conn().execute("SELECT * FROM sources WHERE url=?", (url,)).fetchone()
        return self._row(r) if r else None

    def source_by_id(self, sid: int) -> SourceRow | None:
        r = self._conn().execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
        return self._row(r) if r else None

    def sources(self) -> list[SourceRow]:
        return [self._row(r) for r in self._conn().execute("SELECT * FROM sources ORDER BY id")]

    def update_source(self, url: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._write_lock:
            con = self._conn()
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(f"UPDATE sources SET {cols} WHERE url=?", (*fields.values(), url))
                self._bump(con)
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise

    def replace_chunks(self, url: str, chunks, vectors=None, embedder_name: str | None = None, **fields) -> int:
        """Swap in a source's passages, FTS rows and vectors in one transaction."""
        with self._write_lock:
            con = self._conn()
            con.execute("BEGIN IMMEDIATE")
            try:
                row = con.execute("SELECT id FROM sources WHERE url=?", (url,)).fetchone()
                if row is None:
                    cur = con.execute("INSERT INTO sources(url) VALUES(?)", (url,))
                    sid = cur.lastrowid
                else:
                    sid = row["id"]
                old = [r["id"] for r in con.execute("SELECT id FROM chunks WHERE source_id=?", (sid,))]
                if old:
                    marks = ",".join("?" * len(old))
                    con.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({marks})", old)
                    gone = con.execute(f"DELETE FROM vectors WHERE chunk_id IN ({marks})", old).rowcount
                    con.execute("DELETE FROM chunks WHERE source_id=?", (sid,))
                    if gone:
                        self._bump(con, "vec_epoch")
                # Passage ids only ever grow, so an id a client holds never
                # names another document's passage, and one source's ids are
                # contiguous (source-scoped search uses the range).
                seq = int(self.get_meta_in(con, "chunk_seq") or 0)
                top = con.execute("SELECT COALESCE(MAX(id), 0) FROM chunks").fetchone()[0]
                next_id = max(seq, top) + 1
                ids = []
                for ch in chunks:
                    cid = next_id
                    next_id += 1
                    con.execute(
                        "INSERT INTO chunks(id, source_id, ord, page, heading, text, normv) VALUES(?,?,?,?,?,?,?)",
                        (cid, sid, ch.ord, ch.page, ch.heading, ch.text, tx.NORMALISER_VERSION),
                    )
                    ids.append(cid)
                    con.execute(
                        "INSERT INTO chunks_fts(rowid, norm) VALUES(?, ?)",
                        (cid, normalise(f"{ch.heading or ''} {ch.text}")),
                    )
                con.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES('chunk_seq', ?)", (str(next_id - 1),)
                )
                if vectors is not None and len(ids):
                    q = _quantise(vectors)
                    con.executemany(
                        "INSERT INTO vectors(chunk_id, vec) VALUES(?, ?)",
                        [(cid, q[i].tobytes()) for i, cid in enumerate(ids)],
                    )
                fields["chunks"] = len(ids)
                cols = ", ".join(f"{k}=?" for k in fields)
                con.execute(f"UPDATE sources SET {cols} WHERE id=?", (*fields.values(), sid))
                if embedder_name and vectors is not None:
                    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('embedder', ?)", (embedder_name,))
                con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('changed_at', ?)", (str(time.time()),))
                self._bump(con)
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        return len(ids)

    @staticmethod
    def get_meta_in(con: sqlite3.Connection, key: str) -> str | None:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def tidy(self) -> None:
        """After a pass that changed the library: merge FTS segments and fold the WAL back."""
        with self._write_lock:
            con = self._conn()
            try:
                con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('optimize')")
            except sqlite3.OperationalError:
                pass
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.OperationalError:
                pass  # readers in other processes; the next pass tries again

    def stale_normalisation(self) -> int:
        """Passages indexed by an older tokenizer, still to be re-normalised."""
        return self._conn().execute(
            "SELECT COUNT(*) FROM chunks WHERE normv IS NULL OR normv < ?", (tx.NORMALISER_VERSION,)
        ).fetchone()[0]

    def renormalise_batch(self, limit: int = 500) -> int:
        """Rebuild the FTS text of up to `limit` passages from their stored
        text with the current tokenizer. No fetching; safe to interrupt."""
        with self._write_lock:
            con = self._conn()
            con.execute("BEGIN IMMEDIATE")
            try:
                rows = con.execute(
                    "SELECT id, heading, text FROM chunks WHERE normv IS NULL OR normv < ? LIMIT ?",
                    (tx.NORMALISER_VERSION, limit),
                ).fetchall()
                for r in rows:
                    con.execute(
                        "UPDATE chunks_fts SET norm=? WHERE rowid=?", (normalise(f"{r['heading'] or ''} {r['text']}"), r["id"])
                    )
                con.executemany(
                    "UPDATE chunks SET normv=? WHERE id=?", [(tx.NORMALISER_VERSION, r["id"]) for r in rows]
                )
                if rows:
                    self._bump(con)
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        return len(rows)

    def add_vectors(self, pairs, embedder_name: str) -> None:
        with self._write_lock:
            con = self._conn()
            con.execute("BEGIN IMMEDIATE")
            con.executemany("INSERT OR REPLACE INTO vectors(chunk_id, vec) VALUES(?, ?)", pairs)
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('embedder', ?)", (embedder_name,))
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('changed_at', ?)", (str(time.time()),))
            # backfilled ids can sit below ones already loaded: readers reload
            self._bump(con, "vec_epoch")
            self._bump(con)
            con.execute("COMMIT")

    def clear_vectors(self) -> None:
        with self._write_lock:
            con = self._conn()
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM vectors")
            self._bump(con, "vec_epoch")
            self._bump(con)
            con.execute("COMMIT")

    def chunks_without_vectors(self, limit: int = 2000) -> list[tuple[int, str, str | None]]:
        rows = self._conn().execute(
            "SELECT c.id, c.text, c.heading FROM chunks c LEFT JOIN vectors v ON v.chunk_id=c.id "
            "WHERE v.chunk_id IS NULL LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r["id"], r["text"], r["heading"]) for r in rows]

    # ----- reads ---------------------------------------------------------------

    def chunk_rows(self, ids: list[int]) -> dict[int, sqlite3.Row]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self._conn().execute(
            f"SELECT c.id, c.source_id, c.ord, c.page, c.heading, c.text, s.url, s.doc_url, s.title, s.kind, "
            f"s.entry_ids, s.sections, s.status, f.norm FROM chunks c JOIN sources s ON s.id=c.source_id "
            f"LEFT JOIN chunks_fts f ON f.rowid=c.id WHERE c.id IN ({marks})",
            ids,
        ).fetchall()
        return {r["id"]: r for r in rows}

    def source_chunks(self, source_id: int, start_ord: int = 0, limit: int = 100_000) -> list[sqlite3.Row]:
        return self._conn().execute(
            "SELECT id, ord, page, heading, text FROM chunks WHERE source_id=? AND ord>=? ORDER BY ord LIMIT ?",
            (source_id, start_ord, limit),
        ).fetchall()

    def source_chunks_from_page(self, source_id: int, page: int, limit: int) -> list[sqlite3.Row]:
        return self._conn().execute(
            "SELECT id, ord, page, heading, text FROM chunks WHERE source_id=? AND page>=? ORDER BY ord LIMIT ?",
            (source_id, page, limit),
        ).fetchall()

    def source_pages(self, source_id: int) -> set[int]:
        return {
            r[0]
            for r in self._conn().execute("SELECT DISTINCT page FROM chunks WHERE source_id=? AND page IS NOT NULL", (source_id,))
        }

    def chunk_span(self, source_id: int) -> tuple[int, int] | None:
        r = self._conn().execute("SELECT MIN(id), MAX(id) FROM chunks WHERE source_id=?", (source_id,)).fetchone()
        return (r[0], r[1]) if r and r[0] is not None else None

    def chunk_with_neighbours(self, chunk_id: int, around: int = 1) -> tuple[int, list[sqlite3.Row]] | None:
        """(source id, the passage and its neighbours in document order)."""
        con = self._conn()
        row = con.execute("SELECT source_id, ord FROM chunks WHERE id=?", (chunk_id,)).fetchone()
        if row is None:
            return None
        rows = con.execute(
            "SELECT id, ord, page, heading, text FROM chunks WHERE source_id=? AND ord BETWEEN ? AND ? ORDER BY ord",
            (row["source_id"], row["ord"] - around, row["ord"] + around),
        ).fetchall()
        return row["source_id"], rows

    def fts_query(
        self,
        expr: str,
        *,
        limit: int = 60,
        span: tuple[int, int] | None = None,
        source_ids: list[int] | None = None,
    ) -> list[tuple[int, float]]:
        """(passage id, bm25 score, higher is better) for an FTS5 expression,
        optionally inside one source's id range or a set of sources."""
        if not expr:
            return []
        sql = "SELECT rowid, bm25(chunks_fts) AS s FROM chunks_fts WHERE chunks_fts MATCH ?"
        args: list = [expr]
        if span is not None:
            sql += " AND rowid BETWEEN ? AND ?"
            args += [span[0], span[1]]
        if source_ids is not None:
            if not source_ids:
                return []
            sql += f" AND rowid IN (SELECT id FROM chunks WHERE source_id IN ({','.join('?' * len(source_ids))}))"
            args += list(source_ids)
        sql += " ORDER BY s LIMIT ?"
        args.append(limit)
        try:
            rows = self._conn().execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return []
        return [(r["rowid"], -r["s"]) for r in rows]

    def term_df(self, terms: list[str]) -> dict[str, int]:
        """How many passages contain each term, from FTS5's own vocabulary."""
        if not terms:
            return {}
        con = self._conn()
        if not getattr(self._local, "vocab", False):
            try:
                con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.chunks_vocab USING fts5vocab(main, chunks_fts, row)")
                self._local.vocab = True
            except sqlite3.OperationalError:
                return {}
        marks = ",".join("?" * len(terms))
        try:
            rows = con.execute(f"SELECT term, doc FROM temp.chunks_vocab WHERE term IN ({marks})", terms).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {r[0]: r[1] for r in rows}

    def chunk_count(self) -> int:
        gen = self.generation()
        cached = getattr(self, "_count_cache", None)
        if cached and cached[0] == gen:
            return cached[1]
        n = self._conn().execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        self._count_cache = (gen, n)
        return n

    FULL_RELOAD_GAP = 30.0  # seconds between full vector reloads while a crawl rewrites the library
    APPEND_CHECK = 1.0  # seconds between looks for newly stored vectors

    def vector_matrix(self):
        """(chunk ids, int8 matrix) for every stored vector.

        New passages are appended as they arrive; a full reload happens only
        when vectors were deleted or backfilled (vec_epoch), at most every
        FULL_RELOAD_GAP seconds. Kept as int8: a quarter of the memory of
        float32 in every client process."""
        import numpy as np

        with self._vec_lock:
            epoch = self.get_meta("vec_epoch", "0")
            cur = self._vectors
            now = time.time()
            full = cur is None or (cur["epoch"] != epoch and now - cur["loaded_at"] >= self.FULL_RELOAD_GAP)
            if full:
                rows = self._conn().execute("SELECT chunk_id, vec FROM vectors ORDER BY chunk_id").fetchall()
                if not rows:
                    self._vectors = None
                    return None
                ids = np.fromiter((r["chunk_id"] for r in rows), dtype=np.int64, count=len(rows))
                mat = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.int8).reshape(len(rows), -1)
                self._vectors = cur = {"ids": ids, "mat": mat, "epoch": epoch, "loaded_at": now, "checked": now}
                self.vector_loads += 1
            elif now - cur["checked"] >= self.APPEND_CHECK:
                cur["checked"] = now
                top = int(cur["ids"][-1])
                rows = self._conn().execute(
                    "SELECT chunk_id, vec FROM vectors WHERE chunk_id > ? ORDER BY chunk_id", (top,)
                ).fetchall()
                if rows:
                    ids = np.fromiter((r["chunk_id"] for r in rows), dtype=np.int64, count=len(rows))
                    mat = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.int8).reshape(len(rows), -1)
                    if mat.shape[1] == cur["mat"].shape[1]:
                        cur["ids"] = np.concatenate([cur["ids"], ids])
                        cur["mat"] = np.concatenate([cur["mat"], mat])
            return cur["ids"], cur["mat"]

    @staticmethod
    def similarities(mat, q, block: int = 16384):
        """Cosine-like scores of an int8 matrix against a float query, in blocks."""
        import numpy as np

        q = np.asarray(q, dtype=np.float32)
        out = np.empty(len(mat), dtype=np.float32)
        for i in range(0, len(mat), block):
            out[i : i + block] = mat[i : i + block].astype(np.float32) @ q
        return out / 127.0

    def counts(self) -> dict:
        con = self._conn()
        by_status = {r["status"]: r["n"] for r in con.execute("SELECT status, COUNT(*) AS n FROM sources GROUP BY status")}
        total_chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        vectors = con.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        last = con.execute("SELECT MAX(fetched_at) FROM sources").fetchone()[0]
        size = 0
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                size += p.stat().st_size
        return {
            "sources": sum(by_status.values()),
            "by_status": by_status,
            "chunks": total_chunks,
            "vectors": vectors,
            "last_fetch": last,
            "bytes": size,
            "embedder": self.get_meta("embedder"),
        }


def _quantise(vectors):
    import numpy as np

    v = np.asarray(vectors, dtype=np.float32)
    return np.clip(np.round(v * 127.0), -127, 127).astype(np.int8)
