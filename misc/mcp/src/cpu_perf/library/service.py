"""The library as the server uses it: the store, the embedder loaded in the
background, an automatic crawl when the library is missing or stale, and
read_source for one document."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from pathlib import Path

from ..corpus import Corpus, CrawlTarget
from ..net import Fetcher
from .crawler import OK_STATUSES, CrawlLock, Crawler
from .embed import get_embedder
from .extract import clean_text
from .retrieve import Retriever
from .store import Store, default_data_dir

log = logging.getLogger("cpu_perf.library")


@dataclass
class SourceText:
    url: str
    doc_url: str | None
    title: str
    kind: str | None
    status: str
    detail: str | None
    pages: int | None
    partial: bool
    text: str
    offset: int
    next_offset: int | None
    total_chars: int
    from_library: bool


def _join_chunks(rows) -> str:
    """Rebuild a document's text from its passages, dropping the overlaps."""
    out: list[str] = []
    prev = ""
    last_page = None
    for r in rows:
        text = clean_text(r["text"])
        if prev:
            for k in range(min(300, len(text)), 20, -1):
                if prev.endswith(text[:k]):
                    text = text[k:].lstrip()
                    break
        if r["page"] is not None and r["page"] != last_page:
            out.append(f"\n[page {r['page']}]\n")
            last_page = r["page"]
        out.append(text)
        prev = r["text"]
    return "\n\n".join(s for s in out if s).strip()


class LibraryService:
    def __init__(
        self,
        corpus: Corpus,
        expander=None,
        *,
        data_dir: Path | str | None = None,
        embed_model: str | None = None,
        auto_index: bool = True,
        live_fetch: bool = True,
        respect_robots: bool = False,
        workers: int = 6,
        max_pages: int = 2500,
        fetcher: Fetcher | None = None,
        refresh_days: float = 30.0,
        maintenance_every: float | None = None,
    ):
        self.corpus = corpus
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.store = Store(self.data_dir / "library.sqlite")
        self.store.ensure_sources(corpus.targets)
        self.embed_model = embed_model
        self.auto_index = auto_index
        self.live_fetch = live_fetch
        self.fetcher = fetcher or Fetcher()
        self._embedder = None
        self.embedder_state = "not loaded"
        self.retriever = Retriever(self.store, lambda: self._embedder, expander)
        self.crawler = Crawler(
            corpus, self.store, self.fetcher, None, workers=workers, max_pages=max_pages,
            respect_robots=respect_robots, refresh_days=refresh_days,
        )
        live_fetcher = fetcher or Fetcher(per_host_interval=0.0)
        self.live = Crawler(corpus, self.store, live_fetcher, None, workers=1, max_pages=max_pages, respect_robots=False)
        self.lock = CrawlLock(self.data_dir / "crawl.lock")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # live fetches: one at a time per URL, a few at once overall
        self._url_locks: dict[str, threading.Lock] = {}
        self._url_locks_guard = threading.Lock()
        self._live_slots = threading.BoundedSemaphore(3)
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="live-fetch")
        self._inflight: dict = {}
        self.still_fetching: set[str] = set()
        import os

        self.live_wait = float(os.environ.get("CPU_PERF_LIVE_WAIT_SECONDS", "40"))
        # whole-document text, rebuilt only when the library changes
        self._docs: OrderedDict[tuple[int, int], str] = OrderedDict()
        self._docs_guard = threading.Lock()
        self._status_cache: tuple[int, dict] | None = None
        # maintenance: a pass every few minutes, by whichever process holds the writer lock
        import os

        self.maintenance_every = maintenance_every or float(os.environ.get("CPU_PERF_MAINTENANCE_SECONDS", "300"))
        self.on_tick = None  # called at the start of each pass (the daily list update hooks in here)
        self.passes = 0
        self._last_request = 0.0
        self.crawler.yield_to = self.wait_for_quiet

    # ----- lifecycle ------------------------------------------------------------

    def set_corpus(self, corpus: Corpus, expander=None) -> None:
        """Serve a newer list: crawl its new links, and stop citing links it
        dropped (their passages stay on disk but leave every answer)."""
        targets = {t.url for t in corpus.targets}
        self.corpus = corpus
        self.crawler.corpus = corpus
        self.live.corpus = corpus
        if expander is not None:
            self.retriever.expander = expander
        self.store.ensure_sources(corpus.targets)
        for row in self.store.sources():
            if row.url not in targets and (row.entry_ids or row.sections):
                self.store.update_source(row.url, entry_ids="[]", sections="[]")
        self._status_cache = None  # new links are crawled politely by the next maintenance pass

    def load_embedder(self) -> None:
        self.embedder_state = "loading"
        emb = get_embedder(self.embed_model)
        self._embedder = emb
        self.crawler.embedder = emb
        self.live.embedder = emb
        self.embedder_state = emb.name if emb else "off (keyword search only)"

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="library", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        try:
            self.load_embedder()
        except Exception:
            log.exception("loading the embedder failed")
        while not self._stop.is_set():
            try:
                self.maintain()
            except Exception:
                log.exception("library maintenance failed")
            self._stop.wait(self.maintenance_every)

    def touch(self) -> None:
        """A request is being served: background work yields for a moment."""
        self._last_request = time.time()

    def wait_for_quiet(self, quiet: float = 1.0, longest: float = 10.0) -> None:
        """Hold background work while requests are arriving (up to `longest` seconds)."""
        deadline = time.time() + longest
        while not self._stop.is_set() and time.time() - self._last_request < quiet and time.time() < deadline:
            self._stop.wait(0.1)

    def maintain(self) -> dict:
        """One maintenance pass. Only the process holding the writer lock does
        the work: crawl what is new, stale, failed and due, or extracted by an
        older extractor; embed what has no vector; re-normalise what an older
        tokenizer indexed; then tidy the files. Several clients share this."""
        self.passes += 1
        if self.on_tick is not None:
            try:
                self.on_tick()
            except Exception:
                log.exception("maintenance hook failed")
        pending = self.crawler.select() if self.auto_index else []
        needs_vectors = bool(self._embedder) and bool(self.store.chunks_without_vectors(1))
        stale = self.store.stale_normalisation()
        if not pending and not needs_vectors and not stale:
            return {"work": False}
        if not self.lock.acquire():
            log.info("another process is maintaining the library; serving what is indexed")
            return {"work": True, "lock": "held elsewhere"}
        try:
            gen = self.store.generation()
            self.wait_for_quiet()
            if stale:
                self.renormalise()
            if pending:
                log.info("library: %d sources to fetch", len(pending))
                self.crawler.run(stop=self._stop)
            elif needs_vectors:
                self.crawler.embed_missing()
            if self.store.generation() != gen:
                self.store.tidy()
            return {"work": True, "fetched": len(pending), "renormalised": stale}
        finally:
            self.lock.release()

    def renormalise(self, batch: int = 500, pause: float = 0.02) -> int:
        """Bring passages indexed by an older tokenizer up to date, in small
        batches so requests keep flowing. Call with the writer lock held."""
        done = 0
        while not self._stop.is_set():
            n = self.store.renormalise_batch(batch)
            done += n
            if n < batch:
                break
            self._stop.wait(pause)
        if done:
            log.info("re-normalised %d passages for the current tokenizer", done)
        return done

    def stop(self) -> None:
        self._stop.set()

    def embedder(self):
        return self._embedder

    # ----- status ----------------------------------------------------------------

    def status(self, detail: bool = False, probe_lock: bool = True) -> dict:
        gen = self.store.generation()
        cached = self._status_cache
        if not detail and cached is not None and cached[0] == gen and not self.crawler.progress.running:
            out = dict(cached[1])
            out["embedder"] = self.embedder_state
            out["lock_held_elsewhere"] = self.lock.held_elsewhere() if probe_lock else cached[1]["lock_held_elsewhere"]
            return out
        counts = self.store.counts()
        rows = self.store.sources()
        targets = {t.url for t in self.corpus.targets}
        listed = [r for r in rows if r.url in targets]
        indexed = sum(1 for r in listed if r.status in ("indexed", "partial"))
        out = {
            "data_dir": str(self.data_dir),
            "targets": len(targets),
            "indexed": indexed,
            "by_status": counts["by_status"],
            "passages": counts["chunks"],
            "vectors": counts["vectors"],
            "embedder": self.embedder_state,
            "bytes": counts["bytes"],
            "last_crawl": self.store.get_meta("last_crawl"),
            "crawl": self.crawler.progress.as_dict(),
            "lock_held_elsewhere": self.lock.held_elsewhere(),
            "auto_index": self.auto_index,
            "live_fetch": self.live_fetch,
        }
        if not detail:
            self._status_cache = (gen, dict(out))
        if detail:
            out["sources"] = [
                {
                    "url": r.url,
                    "title": r.title,
                    "status": r.status,
                    "kind": r.kind,
                    "detail": r.detail,
                    "pages": r.pages,
                    "passages": r.chunks,
                    "entry_ids": r.entry_ids,
                }
                for r in listed
            ]
        return out

    def coverage_line(self) -> str:
        s = self.status(probe_lock=False)
        building = " (still building)" if s["crawl"]["running"] else ""
        sem = "semantic + keyword" if self._embedder else "keyword only"
        return f"{s['indexed']}/{s['targets']} linked sources indexed{building}; {s['passages']} passages; {sem}"

    # ----- one document -------------------------------------------------------------

    def prefetch(self, urls: list[str]) -> None:
        """Fetch these sources soon, in the background (one worker, deduplicated):
        a listed source the reader needs that is not in the library yet."""
        if not self.live_fetch:
            return
        with self._url_locks_guard:
            if not hasattr(self, "_prefetch_q"):
                import queue

                self._prefetch_q = queue.Queue()
                self._prefetch_seen: set[str] = set()
                threading.Thread(target=self._prefetch_worker, name="prefetch", daemon=True).start()
            for u in urls:
                base = u.split("#", 1)[0]
                if base not in self._prefetch_seen:
                    self._prefetch_seen.add(base)
                    self._prefetch_q.put(base)

    def _prefetch_worker(self) -> None:
        while not self._stop.is_set():
            url = self._prefetch_q.get()
            try:
                row = self.store.source(url)
                if row is not None and row.status not in OK_STATUSES and row.next_try > time.time():
                    continue  # failed recently; the crawler retries on its own schedule
                self.ensure_fetched(url)
            except Exception:
                log.exception("prefetch failed for %s", url)
            finally:
                with self._url_locks_guard:
                    self._prefetch_seen.discard(url)

    def _url_lock(self, url: str) -> threading.Lock:
        with self._url_locks_guard:
            lock = self._url_locks.get(url)
            if lock is None:
                lock = self._url_locks[url] = threading.Lock()
            return lock

    def _fetch_now(self, base: str, entry_ids: list[str] | None) -> None:
        with self._url_lock(base), self._live_slots:
            row = self.store.source(base)
            if row is None or row.status not in OK_STATUSES:
                target = next((t for t in self.corpus.targets if t.url == base), None)
                target = target or CrawlTarget(url=base, entry_ids=entry_ids or [], sections=[], title=base)
                self.store.ensure_sources([target])
                self.live.process(target, force=True)

    def ensure_fetched(self, url: str, entry_ids: list[str] | None = None):
        """The source's row, fetching it now if it is not in the library yet.

        A large document can take minutes; hosted clients give a call about a
        minute. The fetch runs in the background and the caller waits at most
        `live_wait` seconds; after that the row says it is still fetching and
        a later call finds it in the library."""
        base = url.split("#", 1)[0]
        row = self.store.source(base)
        if (row is None or row.status not in OK_STATUSES) and self.live_fetch:
            with self._url_locks_guard:
                job = self._inflight.get(base)
                if job is None or job.done():
                    try:
                        job = self._pool.submit(self._fetch_now, base, entry_ids)
                    except RuntimeError:  # the process is exiting and its pools are shut down
                        return row
                    self._inflight[base] = job
            try:
                job.result(timeout=self.live_wait)
            except FuturesTimeout:
                self.still_fetching.add(base)
            except Exception:
                log.exception("live fetch failed for %s", base)
            else:
                self.still_fetching.discard(base)
            row = self.store.source(base)
        return row

    def state(self, url: str, entry_ids: list[str] | None = None) -> SourceText:
        """Status and metadata only, fetching if needed; no document text."""
        base = url.split("#", 1)[0]
        row = self.ensure_fetched(base, entry_ids)
        if base in self.still_fetching and (row is None or row.status not in OK_STATUSES):
            return SourceText(base, None, base, None, "fetching", "still downloading (a large document); ask again in a minute",
                              None, False, "", 0, None, 0, False)
        if row is None:
            return SourceText(base, None, base, None, "pending", "not fetched yet and live fetching is off", None, False, "", 0, None, 0, False)
        return SourceText(
            base, row.doc_url, row.title or base, row.kind, row.status, row.detail, row.pages, bool(row.partial),
            "", 0, None, row.chars or 0, row.status in OK_STATUSES,
        )

    def _document(self, row) -> str:
        key = (row.id, self.store.generation())
        with self._docs_guard:
            text = self._docs.get(key)
            if text is not None:
                self._docs.move_to_end(key)
                return text
        text = _join_chunks(self.store.source_chunks(row.id))
        with self._docs_guard:
            self._docs[key] = text
            while len(self._docs) > 6:
                self._docs.popitem(last=False)
        return text

    def read(self, url: str, entry_ids: list[str] | None = None, *, offset: int = 0, max_chars: int = 20000,
             page: int | None = None) -> SourceText:
        """Text of one source: from the library, or fetched now and stored."""
        base = url.split("#", 1)[0]
        row = self.ensure_fetched(base, entry_ids)
        if base in self.still_fetching and (row is None or row.status not in OK_STATUSES):
            return SourceText(base, None, base, None, "fetching",
                              "still downloading (a large document); ask again in a minute and it will be read from the library",
                              None, False, "", 0, None, 0, False)
        if row is None:
            return SourceText(base, None, base, None, "pending", "not fetched yet and live fetching is off", None, False, "", 0, None, 0, False)
        if row.status not in OK_STATUSES:
            return SourceText(base, row.doc_url, row.title or base, row.kind, row.status, row.detail, row.pages, bool(row.partial), "", 0, None, 0, True)

        if page is not None and row.pages and row.kind == "pdf":
            if self.live_fetch and 1 <= page <= row.pages and page not in self.store.source_pages(row.id):
                return self._live_pages(row, page, max_chars)
            # enough passages from that page on to fill the window, no more
            limit = max(4, (offset + max_chars) // 1000 + 3)
            rows = self.store.source_chunks_from_page(row.id, page, limit=limit)
            text = _join_chunks(rows)
            chunk_text = text[offset : offset + max_chars]
            more = len(rows) == limit or offset + max_chars < len(text)
            nxt = offset + max_chars if more and chunk_text else None
            return SourceText(
                base, row.doc_url, row.title or base, row.kind, row.status, row.detail, row.pages, bool(row.partial),
                chunk_text, offset, nxt, len(text), True,
            )

        text = self._document(row)
        chunk_text = text[offset : offset + max_chars]
        nxt = offset + max_chars if offset + max_chars < len(text) else None
        return SourceText(
            base, row.doc_url, row.title or base, row.kind, row.status, row.detail, row.pages, bool(row.partial),
            chunk_text, offset, nxt, len(text), True,
        )

    def _live_pages(self, row, page: int, max_chars: int) -> SourceText:
        from .extract import extract_pdf

        res = self.live.fetcher.fetch(row.doc_url or row.url, max_bytes=self.live.pdf_max_bytes, total_timeout=self.live_wait)
        if not res.ok:
            return SourceText(row.url, row.doc_url, row.title or row.url, row.kind, res.status, res.detail, row.pages,
                              True, "", 0, None, 0, False)
        ex = extract_pdf(res.body, max_pages=40, start_page=page)
        parts = [f"[page {s.page}]\n{s.text.strip()}" for s in ex.segments]
        text = "\n\n".join(parts)
        return SourceText(row.url, row.doc_url, row.title or row.url, "pdf", "ok", f"pages {page}+ read live", row.pages,
                          True, text[:max_chars], 0, None, len(text), False)

    def is_indexed(self, url: str) -> str | None:
        row = self.store.source(url.split("#", 1)[0])
        return row.status if row else None
