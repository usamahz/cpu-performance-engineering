"""Ranking on synthetic libraries: weighted expansions, source-scoped search,
spreadsheet rows versus prose, the list's own sources first, and
re-extraction when an extractor improves."""

from __future__ import annotations

from types import SimpleNamespace

from cpu_perf.corpus import CrawlTarget
from cpu_perf.library.chunk import Chunk
from cpu_perf.library.crawler import Crawler
from cpu_perf.library.extract import EXTRACT_VERSIONS, extract_xlsx
from cpu_perf.library.retrieve import Retriever
from cpu_perf.library.store import Store
from cpu_perf.net import Fetcher

from fixture_site import Site, make_xlsx


def add(store: Store, url: str, texts: list[str], kind: str = "html", entry_ids=("9.9.1",), sections=(9,)):
    store.ensure_sources([CrawlTarget(url=url, entry_ids=list(entry_ids), sections=list(sections), title=url)])
    store.replace_chunks(
        url, [Chunk(i, None, None, t) for i, t in enumerate(texts)], kind=kind, status="indexed", title=url.rsplit("/", 1)[-1]
    )


def test_the_readers_words_outrank_synonyms(tmp_path):
    store = Store(tmp_path / "lib.sqlite")
    add(store, "https://a.example/synonym", ["Hyperthreading shares one core between two threads."])
    add(store, "https://a.example/exact", ["Simultaneous multithreading issues from several threads each cycle."])
    r = Retriever(store)
    plan = r.plan("simultaneous multithreading")
    assert ("smt",) in plan.expansions or ("hyperthreading",) in plan.expansions
    assert '"' in plan.expansion_expr()
    found, _ = r.search("simultaneous multithreading")
    assert [p.source_url for p in found][:2] == ["https://a.example/exact", "https://a.example/synonym"]


def test_multi_word_synonyms_are_phrases(tmp_path):
    store = Store(tmp_path / "lib.sqlite")
    add(store, "https://a.example/phrase", ["Cache line contention between cores shows up in perf c2c."])
    add(store, "https://a.example/scattered", ["The cache was cold. One line of code. Lock contention elsewhere."])
    found, _ = Retriever(store).search("false sharing")
    assert found and found[0].source_url == "https://a.example/phrase"
    assert all(p.source_url != "https://a.example/scattered" for p in found)


def test_common_terms_are_dropped_when_rarer_ones_remain(tmp_path):
    store = Store(tmp_path / "lib.sqlite")
    add(store, "https://a.example/many", [f"performance note {i} about performance" for i in range(20)])
    add(store, "https://a.example/rare", ["performance of the reorder buffer under load"])
    plan = Retriever(store).plan("performance reorder buffer")
    assert "performance" in plan.dropped and "reorder" in plan.primary


def test_source_scoped_search_reaches_past_the_global_top(tmp_path):
    store = Store(tmp_path / "lib.sqlite")
    add(store, "https://a.example/loud", [f"cache cache cache miss latency {i}" for i in range(120)])
    add(store, "https://a.example/quiet", ["A long essay that mentions a cache once, near the end."])
    r = Retriever(store)
    found, _ = r.search("cache", source_url="https://a.example/quiet", limit=3)
    assert found and all(p.source_url == "https://a.example/quiet" for p in found)
    # the section filter is applied in the query, not to a truncated global list
    add(store, "https://a.example/s4", ["cache once"], sections=(4,))
    found, _ = r.search("cache", sections={4}, limit=3)
    assert [p.source_url for p in found] == ["https://a.example/s4"]


def test_spreadsheet_rows_give_way_to_prose_unless_they_name_the_identifier(tmp_path):
    store = Store(tmp_path / "lib.sqlite")
    add(
        store, "https://a.example/sheet",
        ["Metric: Memory_Bound | Event: CYCLE_ACTIVITY.STALLS_L3_MISS | Threshold: > 0.2 | memory stalls " * 3],
        kind="xlsx",
    )
    add(store, "https://a.example/prose", ["Why memory stalls dominate: misses to DRAM leave the core waiting."])
    r = Retriever(store)
    found, _ = r.search("why do memory stalls dominate")
    assert found[0].source_url == "https://a.example/prose"
    found, _ = r.search("cycle_activity.stalls_l3_miss memory stalls")
    assert found[0].source_url == "https://a.example/sheet"


def test_the_lists_sources_come_first_when_they_answer(tmp_path):
    store = Store(tmp_path / "lib.sqlite")
    add(store, "https://a.example/blog", ["perf c2c reports the contended cache line, its offsets and callers."])
    add(store, "https://a.example/other", ["perf c2c perf c2c perf c2c contended cache line offsets callers report."])
    add(store, "https://a.example/offtopic", ["Frequency scaling and turbo on servers."])
    store.ensure_sources([CrawlTarget(url="https://a.example/pending", entry_ids=["4.3.5"], sections=[4], title="p")])
    r = Retriever(store)
    found, meta = r.search(
        "how do I use perf c2c", prefer_urls=["https://a.example/blog", "https://a.example/offtopic", "https://a.example/pending"]
    )
    assert found[0].source_url == "https://a.example/blog" and "listed-first" in found[0].signals
    assert all(p.source_url != "https://a.example/offtopic" for p in found)  # did not clear the floor
    assert meta["unfetched"] == ["https://a.example/pending"]


def test_listed_only_skips_sources_the_list_does_not_vouch_for(tmp_path):
    store = Store(tmp_path / "lib.sqlite")
    add(store, "https://a.example/listed", ["roofline ridge point"])
    add(store, "https://a.example/rejected", ["roofline ridge point roofline"], entry_ids=())
    found, _ = Retriever(store).search("roofline ridge point", listed_only=True)
    assert [p.source_url for p in found] == ["https://a.example/listed"]


def test_spreadsheet_rows_are_labelled_by_their_columns():
    data = make_xlsx(
        [
            ["TMA", "Version", "5.2"],
            ["Key", "Level1", "Metric Description", "Threshold"],
            ["FE", "Frontend_Bound", "Fraction of slots the front end did not deliver", "> 0.15"],
            ["BE", "Backend_Bound", "Fraction of slots stalled in the back end", "> 0.2"],
            ["RET", "Retiring", "", "(> 0.7 | Heavy_Operations)"],
        ]
    )
    text = extract_xlsx(data).segments[0].text
    rows = text.split("\n\n")
    assert rows[0] == "TMA | Version | 5.2"
    assert rows[1] == "Columns: Key; Level1; Metric Description; Threshold"
    assert "Level1: Frontend_Bound" in rows[2] and "Threshold: > 0.15" in rows[2]
    # an absent cell does not shift the ones after it
    assert rows[4] == "Key: RET; Level1: Retiring; Threshold: (> 0.7 | Heavy_Operations)"


def test_an_improved_extractor_refetches_without_a_conditional_request(tmp_path):
    with Site() as site:
        url = site.url("/sheet.xlsx")
        ts = [CrawlTarget(url=url, entry_ids=["6.2.2"], sections=[6], title="sheet")]
        store = Store(tmp_path / "lib.sqlite")
        crawler = Crawler(SimpleNamespace(targets=ts), store, Fetcher(allow_private=True, per_host_interval=0, use_proxy=False))
        crawler.run()
        row = store.source(url)
        assert row.extract_version == EXTRACT_VERSIONS["xlsx"]
        assert crawler.select() == []
        store.update_source(url, extract_version=1)  # as an older release left it
        assert [t.url for t in crawler.select()] == [url]
        before = site.hits.get("/sheet.xlsx", 0)
        assert crawler.process(ts[0]) == "indexed"
        assert site.hits["/sheet.xlsx"] == before + 1
        assert store.source(url).extract_version == EXTRACT_VERSIONS["xlsx"]
