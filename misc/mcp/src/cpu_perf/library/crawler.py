"""Fetch, extract, chunk, embed and store every linked source.

Resumable (each source commits on its own), polite (one request per host
at a time with a gap, backing off on rate limits; robots.txt only when asked,
since it fetches just the documents the list links), and single-writer (an OS file lock, so
several MCP clients can share one library)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from ..corpus import Corpus, CrawlTarget
from ..net import Fetcher, FetchResult
from .chunk import chunk
from .extract import (
    EXTRACT_VERSIONS,
    Extracted,
    Segment,
    decode,
    extract_github_pr,
    extract_html,
    extract_pdf,
    extract_text,
    extract_outdated,
    extract_xlsx,
    sniff,
)
from .resolve import Plan, plan_for, primary_document_links
from .store import Store

log = logging.getLogger("cpu_perf.crawler")

OK_STATUSES = ("indexed", "partial", "empty")
RETRY_SOON = ("unreachable", "too_large")
DAY = 86400.0


@dataclass
class Progress:
    running: bool = False
    total: int = 0
    done: int = 0
    current: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    last_error: str | None = None
    counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "total": self.total,
            "done": self.done,
            "current": list(self.current),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "counts": dict(self.counts),
            "last_error": self.last_error,
        }


class CrawlLock:
    """One writer across every process sharing a data directory.

    An OS advisory lock (flock on POSIX, a locked byte on Windows) held on an
    open file: the kernel drops it when the holder exits or crashes, so there
    is no stale-lock guessing, and a laptop that sleeps keeps its lock. The
    file itself is never deleted, only locked."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = None
        self._mutex = threading.Lock()
        self.held = False

    @staticmethod
    def _try_lock(fh) -> bool:
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    @staticmethod
    def _unlock(fh) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

    def acquire(self) -> bool:
        with self._mutex:
            if self.held:
                return True
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self.path, "a+b")
            if not self._try_lock(fh):
                fh.close()
                return False
            try:  # who holds it, for people reading the file; not used for locking
                info = json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "since": time.time()}).encode()
                if os.name == "nt":
                    fh.seek(1)
                    fh.truncate()
                    fh.write(info)
                else:
                    fh.seek(0)
                    fh.truncate()
                    fh.write(info)
                fh.flush()
            except OSError:
                pass
            self._fh, self.held = fh, True
            return True

    def release(self) -> None:
        with self._mutex:
            if self._fh is not None:
                self._unlock(self._fh)
                self._fh.close()
            self._fh, self.held = None, False

    def held_elsewhere(self) -> bool:
        """True when another process (or another lock object) holds it now."""
        if self.held:
            return False
        if not self.path.exists():
            return False
        try:
            fh = open(self.path, "a+b")
        except OSError:
            return False
        try:
            if self._try_lock(fh):
                self._unlock(fh)
                return False
            return True
        finally:
            fh.close()


def extract_response(res: FetchResult, plan: Plan, max_pages: int) -> Extracted:
    kind = sniff(res.body, res.content_type, res.final_url)
    if kind == "json" and plan.kind == "github_pr":
        return extract_github_pr(res.body)
    if kind == "pdf":
        return extract_pdf(res.body, max_pages=max_pages)
    if kind == "xlsx":
        return extract_xlsx(res.body)
    if kind == "html":
        return extract_html(res.body, res.content_type)
    if kind in ("text", "json"):
        return extract_text(decode(res.body, res.content_type))
    return Extracted(kind="unsupported", title=None, note=f"cannot extract text from {res.content_type or 'this file'}")


class Crawler:
    def __init__(
        self,
        corpus: Corpus,
        store: Store,
        fetcher: Fetcher,
        embedder=None,
        *,
        max_pages: int = 2500,
        pdf_max_bytes: int = 80 * 1024 * 1024,
        workers: int = 6,
        refresh_days: float = 30.0,
        respect_robots: bool = False,
    ):
        self.corpus = corpus
        self.store = store
        self.fetcher = fetcher
        self.embedder = embedder
        self.max_pages = max_pages
        self.pdf_max_bytes = pdf_max_bytes
        self.workers = workers
        self.refresh_days = refresh_days
        self.respect_robots = respect_robots
        self.progress = Progress()
        self._lock = threading.Lock()
        self.yield_to = None  # called before each source: background crawls give way to live requests

    # ----- selection ------------------------------------------------------------

    def select(self, only: list[str] | None = None, refresh: bool = False) -> list[CrawlTarget]:
        targets = self.corpus.targets
        if only:
            wanted = set(only)
            targets = [t for t in targets if t.url in wanted or wanted & set(t.entry_ids)]
            return targets
        now = time.time()
        out = []
        for t in targets:
            row = self.store.source(t.url)
            if refresh or row is None or row.status == "pending":
                out.append(t)
            elif row.status in OK_STATUSES:
                if row.next_try > now:
                    continue  # its last refresh failed; the copy stays until the retry is due
                if not row.fetched_at or now - row.fetched_at > self.refresh_days * DAY:
                    out.append(t)
                elif extract_outdated(row.kind, row.extract_version):
                    out.append(t)
            elif row.next_try <= now:
                out.append(t)
        return _interleave_hosts(out)

    # ----- running ----------------------------------------------------------------

    def run(self, only: list[str] | None = None, refresh: bool = False, stop: threading.Event | None = None) -> dict:
        self.store.ensure_sources(self.corpus.targets)
        todo = self.select(only, refresh)
        p = self.progress
        p.running, p.total, p.done, p.counts = True, len(todo), 0, {}
        p.started_at, p.finished_at, p.current = time.time(), None, []
        halt = stop if stop is not None else threading.Event()
        try:
            pool = ThreadPoolExecutor(max_workers=max(1, self.workers), thread_name_prefix="crawl")
            try:
                futures = [pool.submit(self._one, t, refresh or bool(only), halt) for t in todo]
                for f in futures:
                    f.result()
            except BaseException:
                # Ctrl-C in `cpu-perf index`: drop the queue instead of crawling it all
                halt.set()
                pool.shutdown(wait=False, cancel_futures=True)
                raise
            pool.shutdown(wait=True)
            self.embed_missing()
            self.store.set_meta("last_crawl", str(time.time()))
        finally:
            p.running, p.finished_at = False, time.time()
        return p.as_dict()

    def _one(self, target: CrawlTarget, force: bool, stop: threading.Event | None) -> None:
        if stop is not None and stop.is_set():
            return
        if self.yield_to is not None:
            self.yield_to()
        with self._lock:
            self.progress.current.append(target.url)
        try:
            status = self.process(target, force=force)
        except Exception as exc:  # one bad source never stops the crawl
            log.exception("crawl failed for %s", target.url)
            status = "error"
            self.progress.last_error = f"{target.url}: {type(exc).__name__}: {exc}"
            now, why = time.time(), f"{type(exc).__name__}: {exc}"
            row = self.store.source(target.url)
            if _has_copy(row):
                self.store.update_source(target.url, detail=f"{_kept(row)}{why}", checked_at=now, next_try=now + 6 * 3600)
            else:
                self.store.update_source(target.url, status="unreachable", detail=why, checked_at=now, next_try=now + 6 * 3600)
        with self._lock:
            self.progress.done += 1
            self.progress.counts[status] = self.progress.counts.get(status, 0) + 1
            if target.url in self.progress.current:
                self.progress.current.remove(target.url)

    # ----- one source ---------------------------------------------------------------

    def process(self, target: CrawlTarget, force: bool = False) -> str:
        now = time.time()
        row = self.store.source(target.url)
        plan = plan_for(target.url)
        if plan.kind == "unsupported":
            self.store.update_source(target.url, status="unsupported", kind=plan.kind, detail=plan.note, checked_at=now)
            return "unsupported"

        conditional: dict[str, str] = {}
        outdated = bool(row) and extract_outdated(row.kind, row.extract_version)
        if row and not force and not outdated and row.status in OK_STATUSES and row.doc_url:
            if row.etag:
                conditional["If-None-Match"] = row.etag
            if row.last_modified:
                conditional["If-Modified-Since"] = row.last_modified

        res: FetchResult | None = None
        last: FetchResult | None = None
        for cand in plan.fetch:
            headers = conditional if row and cand == row.doc_url else {}
            r = self.fetcher.fetch(
                cand,
                max_bytes=self.pdf_max_bytes,
                total_timeout=180,
                headers=headers,
                use_robots=self.respect_robots,
                **({"accept": plan.accept} if plan.accept else {}),
            )
            if r.status == "not_modified":
                self.store.update_source(target.url, checked_at=now, fetched_at=now, attempts=0, next_try=0)
                return "not_modified"
            if r.ok and r.body:
                res = r
                break
            last = r
        if res is None and plan.meta_url:
            r = self.fetcher.fetch(plan.meta_url, max_bytes=12 * 1024 * 1024, total_timeout=60, use_robots=self.respect_robots)
            if r.ok:
                res = r
            else:
                last = r
        if res is None:
            return self._failed(target, plan, last, row)

        extracted = extract_response(res, plan, self.max_pages)
        doc_res = res
        note_parts: list[str] = [plan.note] if plan.note else []

        if extracted.kind == "html" and plan.kind not in ("video", "book") and (plan.kind == "landing" or extracted.chars < 3000):
            html = decode(res.body, res.content_type)
            for link in primary_document_links(res.final_url, html):
                r2 = self.fetcher.fetch(link, max_bytes=self.pdf_max_bytes, total_timeout=180, use_robots=self.respect_robots)
                if not (r2.ok and r2.body):
                    continue
                e2 = extract_response(r2, plan_for(link), self.max_pages)
                if e2.chars > extracted.chars:
                    extracted, doc_res = e2, r2
                    note_parts.append(f"main document followed from the landing page: {link}")
                    break
            else:
                if plan.kind == "landing":
                    note_parts.append("landing page only: no downloadable document was offered to an automated client")

        if plan.kind == "video":
            title = extracted.title or target.title
            body = f"{title}\n\n{extracted.description or ''}".strip()
            extracted = Extracted(kind="html", title=title, segments=[Segment(text=body)], description=extracted.description)
        elif plan.kind == "book" and extracted.description and extracted.chars < 500:
            extracted.segments.insert(0, Segment(text=extracted.description))

        if extracted.note:
            note_parts.append(extracted.note)
        chunks = chunk(extracted)
        stored_kind = extracted.kind if plan.kind in ("html", "pdf", "landing") else plan.kind
        partial = bool(extracted.partial or plan.kind in ("video", "book") or (plan.kind == "landing" and doc_res is res))
        status = "empty" if not chunks else ("partial" if partial else "indexed")
        vectors = None
        if chunks and self.embedder is not None:
            try:
                vectors = self.embedder.encode([f"{c.heading or ''}\n{c.text}" for c in chunks])
            except Exception as exc:
                log.warning("embedding failed for %s: %s", target.url, exc)
        self.store.replace_chunks(
            target.url,
            chunks,
            vectors,
            getattr(self.embedder, "name", None),
            doc_url=doc_res.url,
            final_url=doc_res.final_url,
            title=(extracted.title or target.title)[:300],
            kind=stored_kind,
            extract_version=EXTRACT_VERSIONS.get(stored_kind, 1),
            status=status,
            http_status=doc_res.http_status,
            detail="; ".join(n for n in note_parts if n) or None,
            fetched_at=now,
            checked_at=now,
            etag=doc_res.headers.get("etag"),
            last_modified=doc_res.headers.get("last-modified"),
            sha256=hashlib.sha256(doc_res.body).hexdigest(),
            pages=extracted.pages,
            chars=extracted.chars,
            partial=int(partial),
            attempts=0,
            next_try=0,
        )
        return status

    def _failed(self, target: CrawlTarget, plan: Plan, res: FetchResult | None, row) -> str:
        now = time.time()
        status = res.status if res else "unreachable"
        attempts = (row.attempts if row else 0) + 1
        if status in RETRY_SOON or (res and res.http_status == 429):
            delay = min(7 * DAY, 3600 * (2 ** min(attempts, 7)))
        elif status == "refused":
            delay = 365 * DAY
        else:
            delay = self.refresh_days * DAY
        detail = res.detail if res else "no response"
        if res and res.final_url and res.final_url != res.url:
            detail += f" (at {res.final_url})"
        if _has_copy(row) and status != "dead":
            # a refresh that failed (offline, a host that now refuses, a re-extraction): the copy
            # already in the library stays readable, and the next try is scheduled as usual
            self.store.update_source(
                target.url, detail=f"{_kept(row)}{detail}", checked_at=now, attempts=attempts, next_try=now + delay,
            )
            return status
        self.store.update_source(
            target.url,
            status=status if status in ("blocked", "dead", "unreachable", "refused", "too_large") else "unreachable",
            kind=plan.kind,
            http_status=res.http_status if res else None,
            detail=detail,
            checked_at=now,
            attempts=attempts,
            next_try=now + delay,
        )
        return status

    # ----- embeddings ---------------------------------------------------------------------

    def embed_missing(self, batch: int = 1024) -> int:
        if self.embedder is None:
            return 0
        current = self.store.get_meta("embedder")
        if current and current != self.embedder.name:
            self.store.clear_vectors()
        done = 0
        while True:
            rows = self.store.chunks_without_vectors(batch)
            if not rows:
                break
            vecs = self.embedder.encode([f"{h or ''}\n{t}" for _, t, h in rows])
            from .store import _quantise

            q = _quantise(vecs)
            self.store.add_vectors([(cid, q[i].tobytes()) for i, (cid, _, _) in enumerate(rows)], self.embedder.name)
            done += len(rows)
        return done


def _has_copy(row) -> bool:
    """The library already holds readable text for this source."""
    return row is not None and row.status in OK_STATUSES and bool(row.chunks)


def _kept(row) -> str:
    when = time.strftime("%Y-%m-%d", time.gmtime(row.fetched_at)) if row.fetched_at else "an earlier fetch"
    return f"copy from {when} kept; the last refresh failed: "


def _interleave_hosts(targets: list[CrawlTarget]) -> list[CrawlTarget]:
    """Round-robin by host so parallel workers rarely wait on one host."""
    by_host: dict[str, list[CrawlTarget]] = {}
    for t in targets:
        by_host.setdefault((urlsplit(t.url).hostname or "").lower(), []).append(t)
    out: list[CrawlTarget] = []
    queues = list(by_host.values())
    while queues:
        nxt = []
        for q in queues:
            out.append(q.pop(0))
            if q:
                nxt.append(q)
        queues = nxt
    return out
