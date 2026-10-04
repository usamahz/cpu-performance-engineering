"""Everyday questions and what a good answer must surface.

Run against the list (always) and against a real crawled library when
CPU_PERF_EVAL_DB points at one. Also usable as a report:

    python tests/eval_queries.py /path/to/library.sqlite
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# (question, any of these refs counts, within the top k). Refs are entry ids,
# subsection ids (an entry inside the subsection also counts) or benchmark slugs.
LIST_GOLDEN: list[tuple[str, set[str], int]] = [
    ("how do I use perf c2c to find false sharing", {"4.3.5"}, 3),
    ("my p99 latency jumps when load increases, how should I measure it properly", {"12.1.3", "12-coordinated-omission"}, 3),
    ("does hyperthreading help my workload", {"3.1.4"}, 3),
    ("my matrix multiply is slow compared to BLAS", {"13.1", "13-sgemm-naive-vs-blas"}, 3),
    ("cycle_activity.stalls_l3_miss is high, what does it mean", {"6.2", "4.1"}, 5),
    ("perf report shows no call stacks, should I build with -fno-omit-frame-pointer", {"5.3"}, 3),
    ("gcc -O3 says 'not vectorized: complicated access pattern' for my loop", {"8.3", "08-autovectorization-aliasing", "07-aos-vs-soa-simd"}, 5),
    ("how do I pin threads to cores and keep memory on the local NUMA node", {"10.1", "10.2", "10-first-touch"}, 3),
    ("what does the Frontend_Bound metric in toplev mean", {"6.2"}, 3),
    ("branch mispredictions in a sorted versus unsorted loop", {"02-branch-misprediction", "3.2"}, 3),
    ("huge pages and TLB misses", {"4.4.5", "4.4.6"}, 3),
    ("how do I stop the compiler optimising away my benchmark", {"5.4"}, 5),
    ("memory bandwidth STREAM triad", {"15-stream-bandwidth", "15.2.1"}, 3),
    ("store forwarding stall", {"2.4.2"}, 3),
    ("lock-free queue performance", {"9.3"}, 3),
    ("AVX-512 frequency drop", {"3.4.3"}, 3),
    ("llama.cpp token generation speed on CPU", {"13.2.3", "13.5.4", "13.6"}, 3),
    ("Graviton compiler flags", {"14.3.1"}, 3),
    ("PGO and BOLT for a large binary", {"8.4"}, 3),
    ("roofline model arithmetic intensity", {"6.1", "06-roofline"}, 3),
    ("IPC is 0.4 and backend bound is 60 percent, where do I look", {"6.2"}, 5),
]

# (question, any source URL containing one of these, within the top k passages).
# These hold for the sources reachable from a restricted network too (GitHub).
LIBRARY_GOLDEN: list[tuple[str, list[str], int]] = [
    ("coordinated omission in load testing", ["giltene/wrk2"], 3),
    ("how do I stop the compiler optimising away my benchmark loop", ["google/benchmark"], 3),
    ("parse JSON at gigabytes per second", ["simdjson"], 3),
    ("record latency percentiles in a histogram", ["HdrHistogram"], 3),
    ("collect a profile for BOLT with perf2bolt", ["main/bolt"], 3),
    ("dispatch to the best SIMD target at run time", ["google/highway"], 3),
    ("likwid-perfctr marker API", ["likwid"], 3),
    ("cycle_activity.stalls_l3_miss", ["TMA_Metrics"], 3),
    ("toplev level 1 frontend bound", ["pmu-tools"], 3),
    ("prompt processing and token generation pp512 tg128", ["llama-bench"], 3),
    ("tuning software for Graviton", ["aws-graviton"], 3),
    ("memory model litmus tests", ["herdtools7"], 3),
]

# Prose questions whose passages should not be crowded out by spreadsheet rows.
PROSE: list[str] = [
    "how do I use perf c2c to find false sharing",
    "my p99 latency jumps when load increases, how should I measure it properly",
    "how do I pin threads to cores and keep memory on the local NUMA node",
    "why is my interpreter loop slow on branch mispredictions",
]


def list_hit(hit, wanted: set[str]) -> bool:
    if hit.ref in wanted:
        return True
    sub = getattr(hit, "subsection", None)
    return bool(sub and sub in wanted)


def eval_list(index) -> dict:
    rows = []
    for q, wanted, k in LIST_GOLDEN:
        hits, _ = index.search(q, scope="list", limit=k)
        ok = any(list_hit(h, wanted) for h in hits)
        rows.append({"q": q, "ok": ok, "got": [h.ref for h in hits]})
    return {"recall": sum(r["ok"] for r in rows) / len(rows), "rows": rows}


def eval_library(retriever) -> dict:
    rows, times = [], []
    for q, wanted, k in LIBRARY_GOLDEN:
        t = time.perf_counter()
        ps, _ = retriever.search(q, limit=k)
        times.append(time.perf_counter() - t)
        ok = any(any(w in p.source_url for w in wanted) for p in ps)
        rows.append({"q": q, "ok": ok, "got": [p.source_url for p in ps]})
    table_share = []
    for q in PROSE:
        ps, _ = retriever.search(q, limit=5)
        if ps:
            table_share.append(sum(1 for p in ps if p.kind == "xlsx") / len(ps))
    times.sort()
    return {
        "recall": sum(r["ok"] for r in rows) / len(rows),
        "table_share": sum(table_share) / len(table_share) if table_share else 0.0,
        "p50_ms": round(1000 * times[len(times) // 2], 2),
        "max_ms": round(1000 * times[-1], 2),
        "rows": rows,
    }


def payload_size(result) -> int:
    """Characters an AI client receives for one tool call: text plus structured content."""
    text = sum(len(getattr(c, "text", "") or "") for c in (result.content or []))
    structured = len(json.dumps(result.structured_content, ensure_ascii=False)) if result.structured_content else 0
    return text + structured


def main(argv: list[str]) -> int:
    from cpu_perf.corpus import load
    from cpu_perf.library.retrieve import Retriever
    from cpu_perf.library.store import Store
    from cpu_perf.locate import locate
    from cpu_perf.search import SearchIndex

    index = SearchIndex(load(locate()))
    lst = eval_list(index)
    print(f"list recall {lst['recall']:.2f}")
    for r in lst["rows"]:
        if not r["ok"]:
            print("  miss:", r["q"], "->", r["got"])
    if len(argv) > 1:
        store = Store(Path(argv[1]), readonly=True)
        lib = eval_library(Retriever(store, lambda: None, index.expand))
        print(f"library recall {lib['recall']:.2f}, table share {lib['table_share']:.2f}, p50 {lib['p50_ms']} ms, max {lib['max_ms']} ms")
        for r in lib["rows"]:
            if not r["ok"]:
                print("  miss:", r["q"], "->", [u.split("/")[-1] for u in r["got"]])
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    raise SystemExit(main(sys.argv))
