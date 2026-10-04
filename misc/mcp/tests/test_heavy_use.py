"""Heavy use from several clients: vectors grow without full reloads,
repeated calls are served from cache, background work yields to requests,
and maintenance runs in exactly one process at a time."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from cpu_perf.brain import Brain
from cpu_perf.corpus import CrawlTarget
from cpu_perf.library.chunk import Chunk
from cpu_perf.library.crawler import CrawlLock
from cpu_perf.library.embed import HashingEmbedder
from cpu_perf.library.service import LibraryService
from cpu_perf.library.store import Store
from cpu_perf.net import Fetcher

from fixture_site import Site


def add(store, url, texts, emb):
    store.ensure_sources([CrawlTarget(url=url, entry_ids=["9.9.1"], sections=[9], title=url)])
    chunks = [Chunk(i, None, None, t) for i, t in enumerate(texts)]
    store.replace_chunks(url, chunks, emb.encode(texts), emb.name, status="indexed")


def test_vectors_are_appended_and_reloaded_only_after_deletes(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, "APPEND_CHECK", 0.0)
    emb = HashingEmbedder()
    store = Store(tmp_path / "lib.sqlite")
    add(store, "https://a.example/one", ["first passage", "second passage"], emb)
    ids, mat = store.vector_matrix()
    assert len(ids) == 2 and str(mat.dtype) == "int8"
    assert store.vector_loads == 1
    add(store, "https://a.example/two", ["third passage"], emb)
    ids, _ = store.vector_matrix()
    assert len(ids) == 3 and store.vector_loads == 1  # appended, not reloaded
    # a refresh deletes vectors: a full reload, but not sooner than the gap allows
    add(store, "https://a.example/one", ["first passage again"], emb)
    ids, _ = store.vector_matrix()
    assert store.vector_loads == 1 and len(ids) == 4  # stale ids are harmless meanwhile
    monkeypatch.setattr(Store, "FULL_RELOAD_GAP", 0.0)
    ids, _ = store.vector_matrix()
    assert store.vector_loads == 2 and len(ids) == 2
    sims = Store.similarities(store.vector_matrix()[1], emb.encode(["third passage"])[0])
    assert sims.shape == (2,)


def test_repeated_questions_are_answered_from_cache(corpus, index, tmp_path):
    lib = LibraryService(corpus, index.expand, data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=False)
    brain = Brain(corpus, index, lib)
    a = brain.ask("store forwarding stall")
    assert brain.ask("store forwarding stall") is a
    lib.store.ensure_sources([CrawlTarget(url="https://a.example/new", entry_ids=["1.1"], sections=[1], title="n")])
    assert brain.ask("store forwarding stall") is not a  # the library changed


def test_background_work_waits_for_a_quiet_moment(tmp_path):
    lib = LibraryService(SimpleNamespace(targets=[]), data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=False)
    lib.touch()
    t = time.perf_counter()
    lib.wait_for_quiet(quiet=0.3)
    assert time.perf_counter() - t >= 0.25
    t = time.perf_counter()
    lib.wait_for_quiet(quiet=0.3, longest=0.0)
    assert time.perf_counter() - t < 0.1


def test_one_process_maintains_and_the_pass_does_the_work(tmp_path):
    with Site() as site:
        ts = [CrawlTarget(url=site.url(p), entry_ids=["9.9.1"], sections=[9], title=p) for p in ("/article.html", "/notes.txt")]
        fetcher = Fetcher(allow_private=True, per_host_interval=0, use_proxy=False)
        lib = LibraryService(SimpleNamespace(targets=ts), data_dir=tmp_path, embed_model="none", auto_index=True,
                             live_fetch=False, fetcher=fetcher)
        other = CrawlLock(tmp_path / "crawl.lock")
        assert other.acquire()
        assert lib.maintain() == {"work": True, "lock": "held elsewhere"}
        assert lib.store.source(ts[0].url).status == "pending"
        other.release()
        ticks = []
        lib.on_tick = lambda: ticks.append(1)
        out = lib.maintain()
        assert out["fetched"] == 2 and ticks == [1]
        assert all(lib.store.source(t.url).status == "indexed" for t in ts)
        assert lib.maintain() == {"work": False}  # nothing due until the refresh interval
        assert not lib.lock.held


@pytest.mark.parametrize("n", [200])
def test_many_calls_stay_fast_and_bounded(corpus, index, tmp_path, n):
    lib = LibraryService(corpus, index.expand, data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=False)
    brain = Brain(corpus, index, lib)
    for i in range(n):
        brain.ask(f"question number {i} about cache misses")
    assert len(brain._results) <= Brain.RESULT_CACHE
