from __future__ import annotations

import time

import pytest

from cpu_perf import text as tx
from cpu_perf.evidence import audit
from cpu_perf.resolve import NotFound


def titles(hits):
    return [h.title for h in hits]


@pytest.mark.parametrize(
    "query,scope,expect,k",
    [
        ("false sharing", "entries", "C2C - False Sharing Detection in Linux Perf", 1),
        ("coordinated omission", "entries", "Coordinated Omission", 1),
        ("hyperthreading", "list", "Simultaneous Multithreading: Maximizing On-Chip Parallelism", 3),
        ("matmul", "list", "Anatomy of High-Performance Matrix Multiplication", 5),
        ("THP", "list", "Transparent Hugepage Support", 3),
        ("AVX-512 frequency", "list", "Gathering Intel on Intel AVX-512 Transitions", 1),
        ("USE method", "list", "The USE Method", 1),
        ("speed limits", "list", "Performance Speed Limits", 1),
        ("TMA", "list", "TMA_Metrics-full.xlsx (intel/perfmon)", 2),
        ("cppreference", "record", "std::memory_order at cppreference", 1),
    ],
)
def test_golden_queries(index, query, scope, expect, k):
    hits, _ = index.search(query, scope=scope, limit=10)
    assert expect in titles(hits[:k]), titles(hits[:5])


def test_benchmark_hits(index):
    hits, _ = index.search("coordinated omission", limit=5)
    assert "12-coordinated-omission" in [h.ref for h in hits[:3]]
    hits, _ = index.search("vectorization aliasing restrict", limit=5)
    assert "08-autovectorization-aliasing" in [h.ref for h in hits[:3]]


def test_spelling_equivalence(index):
    a, _ = index.search("optimisation levels", limit=5)
    b, _ = index.search("optimization levels", limit=5)
    assert [h.ref for h in a] == [h.ref for h in b]
    assert tx.tokens("vectorisation behaviour centre") == tx.tokens("vectorization behavior center")


def test_did_you_mean(index):
    hits, meta = index.search("coordinted omission", scope="entries", limit=3)
    assert meta["did_you_mean"]
    assert hits[0].title == "Coordinated Omission"


def test_scope_and_section_filters(index):
    hits, _ = index.search("NEON", scope="watchlist", limit=10)
    assert all(h.kind == "watch" for h in hits)
    hits, _ = index.search("latency", section=12, limit=10)
    assert hits and all(h.section == 12 for h in hits)


def test_shared_url_collapses(index):
    hits, _ = index.search("What Every Programmer Should Know About Memory", scope="entries", limit=10)
    first = hits[0]
    assert first.also  # the second appearance is folded into the first


def test_search_latency(index):
    queries = ["cache line contention between cores", "branch prediction", "numa first touch", "roofline"]
    t0 = time.perf_counter()
    for _ in range(50):
        for q in queries:
            index.search(q, limit=10)
    per_query = (time.perf_counter() - t0) / 200
    assert per_query < 0.02  # generous for CI; typically well under a millisecond


def test_resolve_entries(resolver):
    assert resolver.entry("4.3.5").primary.title.startswith("C2C")
    roof = resolver.entry("1.7")
    assert roof.primary.id == "1.7" and [e.id for e in roof.also] == ["6.1.1"]
    assert resolver.entry("https://www.brendangregg.com/usemethod.html").primary.id == "5.1.1"
    assert resolver.entry("The USE Method").how == "title"
    assert resolver.entry("hoard").primary.id == "9.2.4"
    with pytest.raises(NotFound):
        resolver.entry("99.1.1")
    with pytest.raises(NotFound):
        resolver.entry("https://example.com/not-listed")


def test_resolve_sections_and_benchmarks(resolver):
    assert resolver.section("9").number == 9
    assert resolver.section("watchlist").number == 16
    assert resolver.section("Top-down analysis").number == 6
    assert resolver.benchmark("09").slug == "09-false-sharing"
    assert resolver.benchmark("false sharing").slug == "09-false-sharing"
    assert resolver.record("r9.14").title == "std::memory_order at cppreference"


def test_evidence_on_benchmark_machines(corpus):
    for b in corpus.benchmarks.values():
        text = " ".join(f"{k}: {v}" for k, v in b.machine.items())
        result = audit(text + " 1.5 ns median")
        assert all(f.status == "present" for f in result.fields), (b.slug, [(f.number, f.status) for f in result.fields])
        assert result.verdict == "quotable"


def test_evidence_negatives():
    r = audit("Graviton4 is 30% faster than Graviton3")
    status = {f.number: f.status for f in r.fields}
    assert r.verdict == "drop_number"
    assert status[1] == "partial" and status[6] == "present"
    assert status[4] == "missing" and status[7] == "missing"
    assert audit("This paper defines the roofline model.").verdict == "no_number"
