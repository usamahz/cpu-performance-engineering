"""The store under several processes and heavy reading: ids, counters, the
writer lock, migrations and live-fetch concurrency."""

from __future__ import annotations

import multiprocessing as mp
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest

from cpu_perf.corpus import CrawlTarget
from cpu_perf.library.crawler import CrawlLock, Crawler
from cpu_perf.library.embed import HashingEmbedder
from cpu_perf.library.service import LibraryService
from cpu_perf.library.store import Store
from cpu_perf.net import Fetcher

from fixture_site import Site


@pytest.fixture()
def site():
    with Site() as s:
        yield s


def fetcher():
    return Fetcher(allow_private=True, per_host_interval=0, use_proxy=False)


def targets(site, *paths):
    return [CrawlTarget(url=site.url(p), entry_ids=[f"9.9.{i}"], sections=[9], title=p) for i, p in enumerate(paths, 1)]


def test_passage_ids_only_grow_and_stay_contiguous(tmp_path, site):
    ts = targets(site, "/article.html", "/papers/false-sharing.pdf")
    store = Store(tmp_path / "lib.sqlite")
    crawler = Crawler(SimpleNamespace(targets=ts), store, fetcher(), HashingEmbedder(), workers=1)
    crawler.run()
    paper = store.source(ts[1].url)
    first = store.chunk_span(paper.id)
    epoch = store.get_meta("vec_epoch", "0")
    # refreshing the source that holds the highest ids must not reuse them
    crawler.process(ts[1], force=True)
    second = store.chunk_span(store.source(ts[1].url).id)
    assert second[0] > first[1]
    assert second[1] - second[0] + 1 == store.source(ts[1].url).chunks
    assert store.get_meta("vec_epoch", "0") != epoch  # old vectors were deleted
    sid, rows = store.chunk_with_neighbours(second[0])
    assert sid == paper.id and rows[0]["id"] == second[0]
    assert store.chunk_with_neighbours(first[0]) is None


def test_every_write_bumps_the_generation(tmp_path, site):
    store = Store(tmp_path / "lib.sqlite")
    g0 = store.generation()
    store.ensure_sources(targets(site, "/article.html"))
    g1 = store.generation()
    store.update_source(site.url("/article.html"), status="blocked")
    g2 = store.generation()
    assert g0 < g1 < g2


def test_old_files_gain_new_columns(tmp_path):
    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(path)
    con.executescript(
        """CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE sources(id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
        CREATE TABLE chunks(id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, ord INTEGER NOT NULL, page INTEGER,
            heading TEXT, text TEXT NOT NULL);"""
    )
    con.close()
    Store(path)
    con = sqlite3.connect(path)
    assert "normv" in {r[1] for r in con.execute("PRAGMA table_info(chunks)")}
    assert "extract_version" in {r[1] for r in con.execute("PRAGMA table_info(sources)")}


def test_readonly_store_writes_nothing(tmp_path, site):
    path = tmp_path / "lib.sqlite"
    store = Store(path)
    store.ensure_sources(targets(site, "/article.html"))
    store.close()
    before = sorted(p.name for p in tmp_path.iterdir())
    ro = Store(path, readonly=True)
    assert ro.source(site.url("/article.html")) is not None
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def _open_fresh(barrier, root, rounds, out):
    errors = []
    for k in range(rounds):
        barrier.wait()
        try:
            store = Store(f"{root}/lib{k}.sqlite")
            store.generation()
            store.close()
        except Exception as exc:  # noqa: BLE001 - every failure is reported
            errors.append(f"{type(exc).__name__}: {exc}")
    out.put(errors)


def test_clients_starting_together_open_a_new_library(tmp_path):
    """Two clients started at once both create the library: SQLite answers
    'database is locked' at once while one switches the new file to WAL."""
    ctx = mp.get_context("spawn")
    barrier, out = ctx.Barrier(6), ctx.Queue()
    procs = [ctx.Process(target=_open_fresh, args=(barrier, str(tmp_path), 20, out)) for _ in range(6)]
    for p in procs:
        p.start()
    errors = [e for _ in procs for e in out.get(timeout=300)]
    for p in procs:
        p.join(timeout=60)
    assert errors == []


HOLDER = textwrap.dedent(
    """
    import sys, time
    from cpu_perf.library.crawler import CrawlLock
    lock = CrawlLock(sys.argv[1])
    assert lock.acquire()
    print("held", flush=True)
    time.sleep(60)
    """
)


def test_lock_is_released_when_its_holder_dies(tmp_path):
    path = tmp_path / "crawl.lock"
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(path)], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        mine = CrawlLock(path)
        assert mine.held_elsewhere()
        assert not mine.acquire()
    finally:
        proc.kill()
        proc.wait()
    deadline = time.time() + 5
    while not mine.acquire():
        assert time.time() < deadline
        time.sleep(0.05)
    assert mine.held and not mine.held_elsewhere()
    other = CrawlLock(path)
    assert other.held_elsewhere() and not other.acquire()
    mine.release()
    assert other.acquire()
    other.release()


def test_one_live_fetch_per_url(tmp_path, site):
    ts = targets(site, "/papers/false-sharing.pdf")
    lib = LibraryService(
        SimpleNamespace(targets=ts), data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=True,
        fetcher=fetcher(),
    )
    results = []
    threads = [threading.Thread(target=lambda: results.append(lib.read(ts[0].url).status)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == ["indexed"] * 6
    assert site.hits.get("/papers/false-sharing.pdf") == 1


def test_page_reads_continue_and_metadata_reads_carry_no_text(tmp_path, site):
    ts = targets(site, "/papers/false-sharing.pdf")
    lib = LibraryService(
        SimpleNamespace(targets=ts), data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=True,
        fetcher=fetcher(),
    )
    st = lib.state(ts[0].url)
    assert st.status == "indexed" and st.text == "" and st.total_chars > 0
    page2 = lib.read(ts[0].url, page=2, max_chars=40)
    assert page2.text.startswith("[page 2]") and page2.next_offset == 40
    rest = lib.read(ts[0].url, page=2, offset=40, max_chars=10_000)
    assert "Padding" in page2.text + rest.text and rest.next_offset is None
    whole = lib.read(ts[0].url)
    assert lib.read(ts[0].url).text == whole.text  # served from the document cache



def test_a_slow_live_read_returns_before_the_client_times_out(tmp_path, site):
    """Hosted clients allow about a minute per call: a big download keeps going
    in the background and the call says so instead of hanging."""
    ts = targets(site, "/slow/manual.pdf")
    lib = LibraryService(
        SimpleNamespace(targets=ts), data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=True,
        fetcher=fetcher(),
    )
    lib.live_wait = 0.2
    first = lib.read(ts[0].url)
    assert first.status == "fetching" and "ask again" in first.detail
    deadline = time.time() + 10
    while lib.store.source(ts[0].url) is None or lib.store.source(ts[0].url).status != "indexed":
        assert time.time() < deadline
        time.sleep(0.1)
    again = lib.read(ts[0].url)
    assert again.status == "indexed" and "forwarding" in again.text
    assert site.hits["/slow/manual.pdf"] == 1  # the second call did not download again
