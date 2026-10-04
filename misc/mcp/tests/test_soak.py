"""Several clients on one machine: separate server processes share one data
folder, one of them crawling, all of them answering mixed calls at once.
Nothing may fail, nothing may report a locked database, memory stays flat."""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
import traceback

import pytest

from fixture_site import Site

CALLS = int(os.environ.get("CPU_PERF_SOAK_CALLS", "120"))
QUESTIONS = [
    "false sharing between cores on one cache line",
    "store forwarding size mismatch stall",
    "roofline ridge point and memory bandwidth",
    "why is cppreference not in the list",
    "how do I measure tail latency",
]


def worker(n: int, data_dir: str, base: str, crawl: bool, out) -> None:
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from types import SimpleNamespace

        import context_fixtures as F

        from cpu_perf.brain import Brain
        from cpu_perf.corpus import CrawlTarget, load
        from cpu_perf.library.service import LibraryService
        from cpu_perf.locate import locate
        from cpu_perf.net import Fetcher
        from cpu_perf.search import SearchIndex

        corpus = load(locate())
        index = SearchIndex(corpus)
        targets = [
            CrawlTarget(url=f"{base}/papers/false-sharing.pdf", entry_ids=["4.3.5"], sections=[4], title="C2C"),
            CrawlTarget(url=f"{base}/content-details/manual.html", entry_ids=["2.4.2"], sections=[2], title="Manual"),
            CrawlTarget(url=f"{base}/article.html", entry_ids=["6.1.1"], sections=[6], title="Roofline"),
            CrawlTarget(url=f"{base}/sheet.xlsx", entry_ids=["6.2.2"], sections=[6], title="Sheet"),
            CrawlTarget(url=f"{base}/notes.txt", entry_ids=["4.4.5"], sections=[4], title="Notes"),
        ]
        fetcher = Fetcher(allow_private=True, per_host_interval=0, use_proxy=False)
        lib = LibraryService(
            SimpleNamespace(targets=targets), index.expand, data_dir=data_dir, embed_model="hashing",
            auto_index=crawl, live_fetch=False, fetcher=fetcher, workers=2,
        )
        lib.load_embedder()
        brain = Brain(corpus, index, lib)
        errors, locked = [], 0
        rss = []
        for i in range(CALLS):
            if crawl and i % 20 == 0:
                lib.maintain()
                if i == 40:  # force the refresh path too: delete and rewrite passages under the readers
                    lib.crawler.run(refresh=True)
            q = f"{QUESTIONS[i % len(QUESTIONS)]} ({n}.{i})"
            try:
                kind = i % 4
                if kind == 0:
                    brain.ask(q)
                elif kind == 1:
                    brain.ask(q, context=F.PERF6_HYBRID if i % 8 == 1 else F.GCC_REMARKS)
                elif kind == 2:
                    brain.search(q, scope="sources")
                else:
                    brain.library_status()
            except Exception as exc:  # noqa: BLE001 - every failure is reported
                if "locked" in str(exc):
                    locked += 1
                errors.append(f"{type(exc).__name__}: {exc}")
            if i in (CALLS // 4, CALLS - 1):
                try:
                    import resource

                    rss.append(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                except ImportError:
                    pass
        out.put({"n": n, "errors": errors[:5], "n_errors": len(errors), "locked": locked, "rss": rss,
                 "passages": lib.store.counts()["chunks"]})
    except Exception:
        out.put({"n": n, "errors": [traceback.format_exc()], "n_errors": 1, "locked": 0, "rss": [], "passages": 0})


@pytest.mark.skipif(sys.platform == "win32", reason="spawned workers and the fixture site are exercised on Linux and macOS")
def test_several_processes_share_one_library(tmp_path):
    ctx = mp.get_context("spawn")
    with Site() as site:
        out = ctx.Queue()
        procs = [ctx.Process(target=worker, args=(n, str(tmp_path), site.base, n == 0, out)) for n in range(3)]
        for p in procs:
            p.start()
        results = [out.get(timeout=600) for _ in procs]
        for p in procs:
            p.join(timeout=60)
    for r in sorted(results, key=lambda r: r["n"]):
        assert r["n_errors"] == 0, r["errors"]
        assert r["locked"] == 0
        if len(r["rss"]) == 2:
            assert r["rss"][1] <= r["rss"][0] * 1.5, r["rss"]  # no steady growth under load
    assert max(r["passages"] for r in results) > 0
