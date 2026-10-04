"""Pasted tool output: counters read exactly, metrics with their formulas,
thresholds only where Intel's sheet states them, and honest notes."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from cpu_perf.context import TMA_THRESHOLDS, analyse, parse_number

import context_fixtures as F


def metric(a, name):
    found = [m for m in a.metrics if m.name == name or m.name.startswith(name + " [")]
    assert found, (name, [m.name for m in a.metrics])
    return found[0]


def test_numbers_in_every_locale():
    assert parse_number("2,537,513,000", integer=True) == 2537513000
    assert parse_number("2.537.513.000", integer=True) == 2537513000
    assert parse_number("2'537'513'000", integer=True) == 2537513000
    assert parse_number("2 537 513", integer=True) == 2537513
    assert parse_number("1,234.56", integer=False) == 1234.56
    assert parse_number("1.234,56", integer=False) == 1234.56
    assert parse_number("812.34", integer=False) == 812.34


def test_perf5_plain_output():
    a = analyse(F.PERF5)
    assert a.kinds == ["perf stat"]
    assert metric(a, "IPC").value == pytest.approx(1015005200 / 2537513000, abs=1e-4)
    assert metric(a, "branch miss rate").value == pytest.approx(100 * 12856000 / 381153000, abs=1e-3)
    assert metric(a, "L1d miss rate").value == pytest.approx(10.0)
    assert metric(a, "backend stall share").value == pytest.approx(100 * 1.5e9 / 2537513000, abs=1e-3)
    assert metric(a, "CPUs utilised").value == pytest.approx(0.812 / 0.8139553, abs=2e-3)
    assert all(m.flag is None for m in a.metrics)  # no threshold without a cited source
    assert not a.unparsed
    assert "perf stat of './bench'" in a.notes[0]


def test_hybrid_cores_are_kept_apart_and_thresholds_cited():
    a = analyse(F.PERF6_HYBRID)
    ipc = metric(a, "IPC")
    assert ipc.name == "IPC [cpu_core/u]" and ipc.value == pytest.approx(9876543210 / 4567890123, abs=1e-4)
    assert not any(m.name.endswith("[cpu_atom/u]") and m.name.startswith("IPC") for m in a.metrics)
    be = metric(a, "Backend_Bound (level 1)")
    assert be.value == pytest.approx(0.293) and be.flag == "above Intel's threshold > 0.2"
    assert be.source and "TMA_Metrics_5.2-full" in be.source
    fe = metric(a, "Frontend_Bound (level 1) [cpu_core]")
    assert fe.flag == "above Intel's threshold > 0.15"
    atom = [m for m in a.metrics if "[cpu_atom]" in m.name]
    assert atom and all(m.flag is None and m.source is None for m in atom)  # E-cores: values only
    assert any("multiplexed (lowest running share 83.3%" in n for n in a.notes)
    assert any("cpu_atom/cycles/u" in n and "not counted" in n for n in a.notes)
    assert any(n.startswith("Hybrid CPU") for n in a.notes)
    assert a.routing[0] == "top-down" and "backend bound memory bound core bound" in a.routing


def test_csv_json_and_intervals():
    a = analyse(F.PERF_CSV)
    assert a.kinds == ["perf stat -x"]
    assert metric(a, "IPC").value == pytest.approx(9876543210 / 4567890123, abs=1e-4)
    raw = [c for c in a.counts if c.raw.startswith("cpu/event=0x3c")]
    assert raw and raw[0].raw == "cpu/event=0x3c,umask=0x0/" and raw[0].running == 50.0
    assert any("stalled-cycles-frontend: not supported" in n for n in a.notes)

    a = analyse(F.PERF_CSV_INTERVAL)
    assert metric(a, "IPC").value == pytest.approx(1.2e9 / 2e9)  # intervals add up before dividing

    a = analyse(F.PERF_JSON)
    assert a.kinds == ["perf stat -j"]
    assert metric(a, "IPC").value == pytest.approx(0.5, abs=1e-4)
    assert any("61.5%" in n for n in a.notes)
    assert any("LLC-load-misses: not counted" in n for n in a.notes)


def test_locale_with_dots_for_thousands():
    a = analyse(F.PERF_DE_LOCALE)
    assert metric(a, "IPC").value == pytest.approx(1.5)


def test_old_topdown_table_and_amd_pipeline():
    a = analyse(F.PERF_OLD_TOPDOWN)
    be = metric(a, "Backend_Bound (level 1)")
    assert be.value == pytest.approx(0.40) and be.flag and "mean of 2 rows" in be.formula
    assert metric(a, "Bad_Speculation (level 1)").flag is None
    a = analyse(F.PERF_AMD_PIPELINE)
    be = metric(a, "Backend_Bound (level 1)")
    assert be.value == pytest.approx(0.45) and be.flag is None and be.source is None  # not Intel's thresholds


def test_toplev():
    a = analyse(F.TOPLEV)
    assert "toplev" in a.kinds
    assert metric(a, "Backend_Bound (level 1)").flag == "above Intel's threshold > 0.2"
    assert metric(a, "Frontend_Bound (level 1)").flag is None
    assert metric(a, "Backend_Bound.Memory_Bound").value == pytest.approx(0.452)
    assert any("Backend_Bound.Memory_Bound as the bottleneck" in n for n in a.notes)
    assert any("multiplexed" in n for n in a.notes)


def test_compiler_remarks():
    a = analyse(F.GCC_REMARKS)
    assert a.kinds == ["compiler remarks"]
    assert "strided access gather data layout structure of arrays" in a.routing
    assert "aliasing restrict pointer" in a.routing
    assert any("loop vectorized using 32 byte vectors" in r for r in a.remarks)
    a = analyse(F.CLANG_REMARKS)
    assert "loop trip count bounds" in a.routing
    assert any("vectorization width: 8" in r for r in a.remarks)


def test_assembly_and_code():
    a = analyse(F.OBJDUMP)
    assert a.kinds == ["assembly"]
    assert "vgatherdps" in a.terms and "gather" in a.routing and "atomic contention" in a.routing and "avx2" in a.routing
    a = analyse(F.PERF_ANNOTATE)
    assert "avx512" in a.routing and "fma throughput" in a.routing
    a = analyse(F.CODE)
    assert a.kinds == ["code"]
    assert {"intrinsics simd", "atomics memory ordering", "alignment cache line padding", "aliasing restrict"} <= set(a.routing)
    assert "_mm256_fmadd_ps" in a.terms


def test_disassembly_without_opcode_bytes_is_still_assembly():
    a = analyse(F.OBJDUMP_NO_BYTES)  # objdump --no-show-raw-insn
    assert a.kinds == ["assembly"] and "vaddss" in a.terms and "avx2" in a.routing
    a = analyse(F.GDB_DISASSEMBLE)
    assert a.kinds == ["assembly"] and "vaddps" in a.terms


def test_an_in_order_float_reduction_is_named_in_assembly_code_and_remarks():
    """gcc reports the dot product vectorised; its adds still run one at a time, in order."""
    a = analyse(F.OBJDUMP_NO_BYTES)
    assert any("in-order float reduction" in n and "vaddss x8" in n for n in a.notes)
    assert a.benchmarks == ["03-latency-vs-throughput"] and "auto-vectorisation" in a.topics

    a = analyse(F.DSP_CODE)
    assert a.kinds == ["code"]  # plain C with no API to route on is code, not search words
    assert any(n.startswith("`s`: a float sum") for n in a.notes)
    assert a.benchmarks == ["03-latency-vs-throughput"]
    assert "control flow branches predication early exit" in a.routing  # first_clip returns from inside its loop
    assert not analyse(F.DSP_CODE + "\n// built with -O3 -ffast-math\n").benchmarks  # reassociation allowed

    a = analyse(F.GCC_DSP_REMARKS + F.DSP_CODE)
    assert a.kinds == ["compiler remarks", "code"] and a.benchmarks == ["03-latency-vs-throughput"]

    a = analyse(F.CLANG_DSP_REMARKS)
    assert "floating point reduction reassociation fast-math" in a.routing
    assert "aliasing restrict pointer" not in a.routing  # "cannot prove it is safe to reorder floating-point"
    assert a.benchmarks == ["03-latency-vs-throughput"]


def test_remarks_count_loops_and_lead_with_what_failed():
    a = analyse(F.GCC_DSP_REMARKS)
    assert "1 loop(s) not vectorised; the reasons are in the remarks" in a.notes
    assert a.remarks[:2] == ["dsp.c:24:14: couldn't vectorize loop", "dsp.c:24:14: not vectorized: control flow in loop"]
    assert not any("loops in function" in r for r in a.remarks)
    assert len([r for r in a.remarks if "16 byte vectors" in r]) == 2  # one per loop, not repeated
    a = analyse(F.CLANG_DSP_REMARKS)  # one -Rpass-missed per loop; the reasons sit at other lines
    assert "2 loop(s) not vectorised; the reasons are in the remarks" in a.notes


def test_a_loop_over_an_array_of_structs_leads_with_its_layout():
    a = analyse(F.ORDER_BOOK)
    assert "perf stat -x" not in a.kinds and not a.counts  # '2,000,000 orders (320 MB), ~26 ms' is a note
    assert a.kinds == ["code"]
    assert a.topics[:2] == ["struct layout", "data layout"]
    assert a.benchmarks == ["07-aos-vs-soa-simd", "03-latency-vs-throughput"]  # the bytes first, then the adds


def test_unknown_text_is_only_search_words():
    a = analyse("my program feels slow on the new box")
    assert not a.kinds and not a.metrics and a.notes


def test_thresholds_match_the_sheet_when_it_is_indexed():
    """When a crawled library is at hand, the constants must equal Intel's sheet."""
    db = os.environ.get("CPU_PERF_EVAL_DB")
    if not db:
        pytest.skip("set CPU_PERF_EVAL_DB to a crawled library.sqlite")
    from cpu_perf.library.store import Store

    store = Store(Path(db), readonly=True)
    row = store.source("https://github.com/intel/perfmon/blob/main/TMA_Metrics-full.xlsx")
    if row is None or row.status != "indexed" or (row.extract_version or 1) < 2:
        pytest.skip("the TMA sheet is not indexed with the row-aware extractor")
    texts = [r["text"] for r in store.source_chunks(row.id)]
    for name, (threshold, _) in TMA_THRESHOLDS.items():
        found = None
        for t in texts:
            m = re.search(r"Level1: " + name + r"[;( ].*?Threshold: ([^;]*)", t)
            if m:
                found = m.group(1).strip()
                break
        assert found == threshold, (name, found)


def test_perf5_frequency_and_rates_match_perf():
    a = analyse(F.PERF5)
    ghz = metric(a, "frequency")
    assert ghz.value == pytest.approx(3.124, abs=1e-3) and ghz.unit == "GHz"  # perf printed 3.124 GHz
    faults = metric(a, "page faults per second")
    assert faults.value == pytest.approx(128.0, abs=0.1)  # perf printed 0.128 K/sec, per task-clock second
    assert metric(a, "context switches per second").value == pytest.approx(3.7, abs=0.1)
    assert a.vendor is None  # generic events name no vendor


def test_hybrid_has_no_frequency_and_names_the_lowest_share():
    a = analyse(F.RPL_HYBRID_MUX)
    assert a.vendor == "intel"
    assert not any(m.name.startswith("frequency") for m in a.metrics)
    assert any(n.startswith("No frequency is given") for n in a.notes)
    # the 11.64% on a TopdownL1 line is lower than any count's share
    assert any("lowest running share 11.6%, TopdownL1 [cpu_atom]" in n for n in a.notes)
    assert metric(a, "context switches per second").value == pytest.approx(24.0, abs=0.05)  # perf: 24.003 /sec
    assert a.topics[:2] == ["top-down analysis", "fetch and decode"]  # Frontend_Bound is furthest over


def test_memory_bound_routes_to_the_memory_hierarchy():
    a = analyse(F.SPR_MEMORY)
    assert a.vendor == "intel"
    assert metric(a, "Backend_Bound (level 1)").flag
    assert a.topics[:2] == ["top-down analysis", "cache geometry"]
    assert "tlbs, page walks" in a.topics
    assert a.routing[:2] == ["top-down", "intel tma metrics"] and "cache miss memory latency prefetch" in a.routing


def test_level2_orders_the_reading_without_flags():
    a = analyse(F.PERF_TOPDOWN_L2)
    core = metric(a, "Core_Bound (level 2)")
    assert core.value == pytest.approx(0.35) and core.flag is None and core.source is None
    assert a.topics[:2] == ["top-down analysis", "execute"]  # Core_Bound over Memory_Bound
    assert "cache geometry" not in a.topics


def test_intervals_are_counted_and_give_the_elapsed_time():
    a = analyse(F.VM_CSV_INTERVALS)
    assert any(n.startswith("3 intervals over 3.003 s") for n in a.notes)
    assert a.elapsed == pytest.approx(3.003012875)
    assert metric(a, "dTLB MPKI").value == pytest.approx(1000 * (9873214 + 10412776 + 9541087) / (6874120338 + 6712345120 + 6903318841), abs=1e-3)
    assert metric(a, "cache MPKI").unit == "per 1k instructions"
    assert any("lowest running share 57.6%" in n for n in a.notes)


def test_vendor_from_events_and_pmus():
    assert analyse(F.ARM_NEOVERSE).vendor == "arm"
    arm = analyse(F.ARM_NEOVERSE)
    assert metric(arm, "IPC").value == pytest.approx(1.5)  # Arm's architected names count as cycles and instructions
    assert all(m.flag is None and m.source is None for m in arm.metrics)  # Intel's thresholds stay Intel's
    assert analyse(F.AMD_EVENTS).vendor == "amd"
    assert analyse(F.PERF_AMD_PIPELINE).vendor == "amd"
    assert analyse(F.TOPLEV).vendor == "intel"
    assert analyse(F.PERF6_HYBRID).vendor == "intel"


def test_perf_errors_are_explained_not_searched_for():
    a = analyse(F.PERF_ERR_METRICGROUP)
    assert a.kinds == ["perf error"]
    assert any("no metric group PipelineL1" in n and "perf list metricgroups" in n for n in a.notes)
    assert a.vendor is None and a.vendor_hint == "amd"
    assert a.topics == ["top-down analysis"] and "amd zen pipeline" in a.routing
    assert not any("No tool output was recognised" in n for n in a.notes)
    assert "Cannot" not in a.search_terms and "Usage" not in a.search_terms

    a = analyse(F.PERF_ERR_PARANOID)
    assert a.kinds == ["perf error"]
    assert any("perf_event_paranoid" in n and "CAP_PERFMON" in n for n in a.notes)
    assert "counters, events" in a.topics

    a = analyse(F.PERF_ERR_EVENTS)
    assert a.kinds[0] == "perf error" and "perf stat" in a.kinds
    assert any("did not recognise the event cycle_activty.stalls_l3_miss" in n for n in a.notes)
    assert any("would not open branch-misses (error 95" in n for n in a.notes)
    assert any("NMI watchdog" in n for n in a.notes)
    assert not a.unparsed  # the watchdog lines are explained, not left over
