"""Exact identifiers (perf events, flags, intrinsics) and the background
re-normalisation of libraries built by an older tokenizer."""

from __future__ import annotations

import re
from types import SimpleNamespace

from cpu_perf import text as tx
from cpu_perf.corpus import CrawlTarget
from cpu_perf.library.crawler import Crawler
from cpu_perf.library.retrieve import Retriever
from cpu_perf.library.service import LibraryService
from cpu_perf.library.store import Store
from cpu_perf.net import Fetcher

from fixture_site import Site


def tokens_v1(text: str) -> list[str]:
    """The tokenizer as NORMALISER_VERSION 1 shipped it, frozen for the superset check."""
    out: list[str] = []
    raw = tx.TOKEN.findall(tx._normalise(text))
    prev_alpha = None
    for tok in raw:
        parts = re.split(r"[._\-/]+", tok.strip("+#")) if re.search(r"[._\-/]", tok) else [tok.strip("+#") or tok]
        parts = [p for p in parts if p]
        compound = len(parts) > 1
        if compound and len(parts) <= 3:
            out.append(tx.fold("".join(parts)))
        for p in parts:
            if len(p) == 1 and not p.isdigit() and p != "c":
                prev_alpha = None
                continue
            if p in tx.STOPWORDS:
                prev_alpha = None
                continue
            if not compound and prev_alpha is not None and p.isdigit() and len(p) <= 3:
                out.append(prev_alpha + p)
            out.append(tx.fold(p))
            prev_alpha = p if (p.isalpha() and not compound) else None
    return out


def test_long_identifiers_match_as_one_term():
    cases = {
        "cycle_activity.stalls_l3_miss": {"cycleactivitystallsl3miss", "cycleactivity", "stallsl3miss"},
        "L2_REQUEST.RFO_HIT_XSNP_HIT_FWD": {"l2requestrfohitxsnphitfwd", "l2request", "rfohitxsnphitfwd"},
        "-fno-omit-frame-pointer": {"fnoomitframepointer"},
        "_mm512_dpbusd_epi32": {"mm512dpbusdepi32"},
        "kernel.numa_balancing": {"kernelnumabalancing", "numabalancing"},
    }
    for text, want in cases.items():
        assert want <= set(tx.tokens(text)), (text, tx.tokens(text))
    # paths and URLs keep their pieces but no giant whole-name token
    toks = tx.tokens("misc/benchmarks/09-false-sharing/README.md https://github.com/intel/perfmon")
    assert not any(len(t) > 25 for t in toks), toks


def test_new_tokens_only_add_to_old_ones(index):
    samples = [f"{d.title} {d.body}" for d in index.docs]
    samples += ["cycle_activity.stalls_l3_miss", "perf stat -e cpu_core/cycles/ -fno-omit-frame-pointer", "Zen 5 and AVX-512"]
    for text in samples:
        old, new = set(tokens_v1(text)), set(tx.tokens(text))
        assert old <= new, (text[:80], old - new)


def test_old_libraries_are_renormalised_without_refetching(tmp_path):
    with Site() as site:
        url = site.url("/notes.txt")
        ts = [CrawlTarget(url=url, entry_ids=["9.9.1"], sections=[9], title="notes")]
        store = Store(tmp_path / "library.sqlite")
        Crawler(SimpleNamespace(targets=ts), store, Fetcher(allow_private=True, per_host_interval=0, use_proxy=False)).run()
        hits_after_crawl = dict(site.hits)
    # make the library look as if an older tokenizer built it
    con = store._conn()
    con.execute("UPDATE chunks SET normv=NULL")
    con.execute("UPDATE chunks_fts SET norm='plain text notes'")
    con.execute("INSERT INTO chunks(id, source_id, ord, text) VALUES(9999, 1, 99, 'see cycle_activity.stalls_l3_miss')")
    con.execute("INSERT INTO chunks_fts(rowid, norm) VALUES(9999, 'see cycle activity stall l3 miss')")
    r = Retriever(store)
    assert not r.search("TLB reach")[0]
    assert store.stale_normalisation() == 2

    lib = LibraryService(SimpleNamespace(targets=ts), data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=False)
    assert lib.renormalise(batch=1) == 2
    assert store.stale_normalisation() == 0
    assert r.search("TLB reach")[0]
    found, _ = r.search("cycle_activity.stalls_l3_miss")
    assert found and found[0].chunk_id == 9999
    assert site.hits == hits_after_crawl  # nothing was fetched again
