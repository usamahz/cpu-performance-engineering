"""Understand pasted tool output, deterministically.

perf stat (plain, -x CSV, -j JSON, per-CPU and interval forms), its top-down
output (old --topdown tables and perf 6 TopdownL1 / TopdownL2 / tma_* lines),
perf's own error messages, toplev, gcc and clang vectoriser remarks, assembly
and source code. The result is the counters as read, metrics computed from
them with their formulas, notes on how far to trust them, the CPU vendor when
the events name it, and the terms that steer the search.

Nothing here judges a number unless a source the list links states the
threshold; the only such thresholds are Intel's own top-down level 1 values,
applied only to Intel P-cores."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

MAX_CHARS = 100_000
MAX_LINES = 5_000

# Intel's thresholds for top-down level 1, verbatim from TMA_Metrics-full.xlsx
# (sheet TMA_Metrics_5.2-full, column Threshold), the list's entry 6.2.2.
# Fractions of pipeline slots; perf prints percentages.
TMA_SOURCE = (
    "Intel TMA_Metrics-full.xlsx, sheet TMA_Metrics_5.2-full, column Threshold "
    "(https://github.com/intel/perfmon/blob/main/TMA_Metrics-full.xlsx)"
)
TMA_THRESHOLDS = {
    "Frontend_Bound": ("> 0.15", 0.15),
    "Bad_Speculation": ("> 0.15", 0.15),
    "Backend_Bound": ("> 0.2", 0.2),
    "Retiring": ("(> 0.7 | Heavy_Operations)", 0.7),
}
TMA_ROUTING = {
    "Frontend_Bound": "frontend bound instruction fetch decode icache",
    "Bad_Speculation": "bad speculation branch misprediction",
    "Backend_Bound": "backend bound memory bound core bound",
    "Retiring": "retiring vectorization instruction count",
}
TMA_NAMES = {
    "retiring": "Retiring",
    "bad speculation": "Bad_Speculation",
    "bad_speculation": "Bad_Speculation",
    "frontend bound": "Frontend_Bound",
    "frontend_bound": "Frontend_Bound",
    "fe bound": "Frontend_Bound",
    "backend bound": "Backend_Bound",
    "backend_bound": "Backend_Bound",
    "be bound": "Backend_Bound",
}
# level 2 is read and shown, never flagged: it only orders what to read
TMA_LEVEL2 = {
    "memory bound": "Memory_Bound",
    "core bound": "Core_Bound",
    "fetch latency": "Fetch_Latency",
    "fetch bandwidth": "Fetch_Bandwidth",
    "branch mispredicts": "Branch_Mispredicts",
    "machine clears": "Machine_Clears",
    "light operations": "Light_Operations",
    "heavy operations": "Heavy_Operations",
}
# the list's subsections to read for a level over Intel's threshold, by title
FLAG_TOPICS = {
    "Frontend_Bound": ["fetch and decode"],
    "Bad_Speculation": ["branch prediction and speculation"],
}
MEMORY_TOPICS = ["cache geometry", "tlbs, page walks", "struct layout"]
CORE_TOPICS = ["execute"]
# counters that show the memory side was measured
MEMORY_EVENTS = re.compile(
    r"^(l1-dcache-load-misses|llc-load-misses|cache-misses|dtlb-load-misses|"
    r"cycle_activity\.stalls_l[123]_miss|mem_load_retired\.\w+|mem_load_l3_miss_retired\.\w+|longest_lat_cache\.miss|"
    r"ls_any_fills_from_sys\.\w+|l2_cache_req_stat\.\w+|ll_cache_miss_rd|l1d_cache_refill|l2d_cache_refill)$",
    re.I,
)

# which vendor's PMU printed the output; a mix of signals means unknown
INTEL_PREFIXES = (
    "cpu_clk_unhalted.", "inst_retired.", "mem_load_retired.", "mem_inst_retired.", "mem_load_l3_miss_retired.",
    "cycle_activity.", "int_misc.", "topdown.", "uops_issued.", "uops_retired.", "uops_executed.", "uops_dispatched.",
    "br_misp_retired.", "br_inst_retired.", "l2_rqsts.", "offcore_requests.", "idq.", "idq_uops_not_delivered.",
    "idq_bubbles.", "resource_stalls.", "machine_clears.", "exe_activity.", "dtlb_load_misses.", "dtlb_store_misses.",
    "itlb_misses.", "fp_arith_inst_retired.", "frontend_retired.", "longest_lat_cache.", "l1d_pend_miss.", "ocr.",
    "memory_activity.",
)
INTEL_EVENTS = {"slots", "topdown-retiring", "topdown-bad-spec", "topdown-fe-bound", "topdown-be-bound"}
AMD_EVENT = re.compile(r"^(ls|de|ex|ic|bp|df)_\w|^l2_(request|cache|pf)\w*|^l3_\w|^fp_(ret|ops|disp)\w*|^ibs_", re.I)
ARM_EVENT = re.compile(
    r"^(stall_frontend|stall_backend|stall_slot\w*|op_spec|op_retired|inst_spec|l1d_cache_refill|l2d_cache_refill|"
    r"ll_cache_miss_rd|br_mis_pred(_retired)?|cpu_cycles)$",
    re.I,
)
VENDOR_PMU = (
    (re.compile(r"^cpu_(core|atom)$"), "intel"),
    (re.compile(r"^amd_|^ibs_"), "amd"),
    (re.compile(r"^armv\d_pmuv\d|^arm_|^apple_\w+_pmu|^hisi_"), "arm"),
)

# perf's generic names and the common raw names, folded to one key each
ALIASES = {
    "cycles": "cycles",
    "cpu-cycles": "cycles",
    "cpu_clk_unhalted.thread": "cycles",
    "cpu_clk_unhalted.core": "cycles",
    "instructions": "instructions",
    "inst_retired.any": "instructions",
    "branches": "branches",
    "branch-instructions": "branches",
    "br_inst_retired.all_branches": "branches",
    "branch-misses": "branch-misses",
    "br_misp_retired.all_branches": "branch-misses",
    "l1-dcache-loads": "L1-dcache-loads",
    "l1-dcache-load-misses": "L1-dcache-load-misses",
    "l1-icache-load-misses": "L1-icache-load-misses",
    "llc-loads": "LLC-loads",
    "llc-load-misses": "LLC-load-misses",
    "cache-references": "cache-references",
    "cache-misses": "cache-misses",
    "stalled-cycles-frontend": "stalled-cycles-frontend",
    "idle-cycles-frontend": "stalled-cycles-frontend",
    "stalled-cycles-backend": "stalled-cycles-backend",
    "idle-cycles-backend": "stalled-cycles-backend",
    "dtlb-loads": "dTLB-loads",
    "dtlb-load-misses": "dTLB-load-misses",
    "itlb-loads": "iTLB-loads",
    "itlb-load-misses": "iTLB-load-misses",
    "task-clock": "task-clock",
    "cpu-clock": "task-clock",
    "context-switches": "context-switches",
    "cs": "context-switches",
    "cpu-migrations": "cpu-migrations",
    "migrations": "cpu-migrations",
    "page-faults": "page-faults",
    "faults": "page-faults",
    "slots": "slots",
    "topdown.slots": "slots",
    "topdown-retiring": "topdown-retiring",
    "topdown-bad-spec": "topdown-bad-spec",
    "topdown-fe-bound": "topdown-fe-bound",
    "topdown-be-bound": "topdown-be-bound",
    # Arm's architected events, the ones perf's generic names map to on arm64
    "cpu_cycles": "cycles",
    "inst_retired": "instructions",
    "br_retired": "branches",
    "br_mis_pred_retired": "branch-misses",
    "stall_frontend": "stalled-cycles-frontend",
    "stall_backend": "stalled-cycles-backend",
}

ROUTING = {
    "IPC": "instructions per cycle",
    "branch miss rate": "branch misprediction",
    "branch MPKI": "branch misprediction",
    "L1d miss rate": "cache miss L1",
    "L1d MPKI": "cache miss L1",
    "LLC miss rate": "last level cache miss memory latency",
    "LLC MPKI": "last level cache miss memory latency",
    "cache miss rate": "cache miss",
    "cache MPKI": "cache miss",
    "dTLB miss rate": "tlb huge pages",
    "dTLB MPKI": "tlb huge pages",
    "iTLB miss rate": "tlb instruction footprint",
    "iTLB MPKI": "tlb instruction footprint",
    "frontend stall share": "frontend stalls",
    "backend stall share": "backend stalls memory",
    "context switches per second": "context switches scheduler",
}

# gcc and clang vectoriser reasons -> what to read about
REMARK_REASONS: tuple[tuple[str, str], ...] = (
    (r"complicated access pattern|non-consecutive|strided|gather", "strided access gather data layout structure of arrays"),
    # clang's "cannot prove it is safe to reorder floating-point operations" is a reduction, not aliasing
    (r"alias|unsafe dependent memory|cannot prove(?! it is safe to reorder floating)|runtime check|dependence|versioning",
     "aliasing restrict pointer"),
    (r"control flow|switch|unsupported.*(if|branch)|cannot be if-converted", "control flow branches predication"),
    (r"number of iterations|trip count|loop bounds|array bounds|could not determine", "loop trip count bounds"),
    (r"call|clobbers memory|function", "function call inlining vector math"),
    (r"reduction|floating[- ]point|reorder|fast-math|reassociat|fp ", "floating point reduction reassociation fast-math"),
    (r"data ref|data-ref|unhandled", "pointer analysis data dependence"),
    (r"not beneficial|cost model|cost", "vectorization cost model"),
    (r"unaligned|alignment|peel", "alignment"),
    (r"outer loop|inner-loop|loop nest", "loop nest outer loop"),
)

ASM_FAMILIES: tuple[tuple[str, str], ...] = (
    (r"^v?p?gather|^vpgather|^vgather", "gather"),
    (r"^v?(div|sqrt)", "divider latency throughput"),
    (r"^(xchg|cmpxchg|xadd)", "atomic contention"),
    (r"^pause$", "spin lock"),
    (r"^[lsm]fence$", "memory ordering fences"),
    (r"^prefetch", "software prefetch"),
    (r"^v?fmadd|^v?fmsub|^vfnmadd", "fma throughput"),
    (r"^rdtscp?$", "timing rdtsc"),
)

CODE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b_mm\d*_\w+", "intrinsics simd"),
    (r"\bstd::atomic\b|\batomic_\w+\(|\bmemory_order_\w+", "atomics memory ordering"),
    (r"\balignas\s*\(|__attribute__\s*\(\(\s*aligned", "alignment cache line padding"),
    (r"#\s*pragma\s+omp", "openmp threads"),
    (r"__builtin_prefetch", "software prefetch"),
    (r"__builtin_expect|\[\[(un)?likely\]\]", "branch prediction"),
    (r"\b(malloc|calloc|realloc|free|operator new)\s*\(", "allocator malloc"),
    (r"\b(pthread_mutex_\w+|std::mutex|spin_?lock)\b", "locks contention"),
    (r"\b(__)?restrict\b", "aliasing restrict"),
    (r"#\s*pragma\s+(GCC\s+ivdep|clang\s+loop|omp\s+simd)", "auto-vectorization"),
    (r"\bvolatile\b", "memory ordering"),
)


@dataclass
class Count:
    event: str  # canonical name when known, else as printed (lower case)
    raw: str
    pmu: str = ""
    mods: str = ""
    value: float | None = None
    unit: str = ""
    running: float | None = None  # percentage of the time the counter was on
    status: str = "ok"  # ok | not counted | not supported
    ts: float | None = None  # the interval's time stamp (perf stat -I)


@dataclass
class Metric:
    name: str
    value: float
    unit: str = ""
    formula: str = ""
    inputs: list[str] = field(default_factory=list)
    flag: str | None = None
    source: str | None = None


@dataclass
class Analysis:
    kinds: list[str] = field(default_factory=list)
    counts: list[Count] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)  # identifiers worth searching for exactly
    routing: list[str] = field(default_factory=list)  # topic words for the list and library
    remarks: list[str] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    elapsed: float | None = None
    topics: list[str] = field(default_factory=list)  # words of the list's subsection titles to read first
    benchmarks: list[str] = field(default_factory=list)  # benchmark slugs that reproduce what the output shows
    flagged: list[tuple[float, str]] = field(default_factory=list)  # (how far over Intel's threshold, level 1 name)
    level2: dict[str, float] = field(default_factory=dict)  # Memory_Bound -> fraction of slots (P-cores)
    shares: list[tuple[str, float]] = field(default_factory=list)  # (metric group, running %) from metric lines
    vendor: str | None = None  # intel | amd | arm, from the events and PMUs printed
    vendor_hint: str | None = None  # weaker: the vendor of a metric group a failed command asked for
    consumed: set[str] = field(default_factory=set)  # lines an earlier parser explained
    signals: set[str] = field(default_factory=set)  # vendors the metric lines point to

    @property
    def search_terms(self) -> list[str]:
        out: list[str] = []
        for t in self.routing + self.terms:
            if t not in out:
                out.append(t)
        return out[:24]

    def summary(self):
        from .models import ContextOut, MetricOut

        counters = {}
        for c in self.counts:
            if c.value is not None and c.status == "ok":
                key = f"{c.pmu}/{c.event}" if c.pmu else c.event
                key += f":{c.mods}" if c.mods else ""
                counters[key] = counters.get(key, 0.0) + c.value
        return ContextOut(
            kinds=self.kinds,
            vendor=self.vendor,
            metrics=[MetricOut(**m.__dict__) for m in self.metrics],
            counters=dict(list(counters.items())[:40]),
            notes=self.notes,
            terms=self.search_terms,
            remarks=self.remarks[:12],
            unparsed=self.unparsed[:20],
        )


# ----- numbers ------------------------------------------------------------------------


def parse_number(text: str, integer: bool) -> float | None:
    """perf prints counts with the locale's thousands separator."""
    t = text.strip().replace(" ", "").replace(" ", "").replace("'", "").replace(" ", "")
    if not t or not re.fullmatch(r"[\d.,]+", t):
        return None
    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in t:
        t = t.replace(",", "") if (integer or re.fullmatch(r"\d{1,3}(,\d{3})+", t)) else t.replace(",", ".")
    elif "." in t and integer and re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def split_event(raw: str) -> tuple[str, str, str]:
    """'cpu_core/cycles/u' -> ('cycles', 'cpu_core', 'u'); 'cycles:u' -> ('cycles', '', 'u')."""
    name, pmu, mods = raw.strip(), "", ""
    m = re.fullmatch(r"([\w.-]+)/([^/]+)/(\w*)", name)
    if m:
        pmu, name, mods = m.group(1), m.group(2), m.group(3)
    elif ":" in name:
        name, mods = name.rsplit(":", 1)
    key = ALIASES.get(name.lower(), name.lower())
    return key, pmu, mods


# ----- perf stat --------------------------------------------------------------------------

PLAIN = re.compile(
    r"^\s*(?:(?P<ts>\d+\.\d+)\s+)?"
    r"(?:(?P<where>CPU\d+|S\d+(?:-D\d+)?(?:-C\d+)?(?:-T\d+)?|N\d+|C\d+)\s+(?:\d+\s+)?)?"
    r"(?P<value>\d[\d,.'  ]*|<not counted>|<not supported>)\s+"
    r"(?:(?P<unit>msec|ms|ns|us|Joules|MiB|GiB|MB|GB)\s+)?"
    r"(?P<event>[A-Za-z_][\w.:/=,-]*/?\w*)"
    r"(?P<rest>.*)$"
)
RUNNING = re.compile(r"\(\s*(\d+(?:\.\d+)?)%\s*\)\s*$")
TMA_LINE = re.compile(r"#\s*(\d+(?:\.\d+)?)\s*%\s*(tma_)?(\w+)")
TOPDOWN_GROUP = re.compile(r"^\s*(TopdownL\d|PipelineL\d)\s*(?:\((\w+)\))?", re.I)
ELAPSED = re.compile(r"^\s*([\d.,]+)\s+seconds\s+time\s+elapsed")
HEADER = re.compile(r"Performance counter stats for\s+(.+?):?\s*$")


def _record_tma(a: Analysis, name: str, pct: float, origin: str, intel_pcore: bool, pmu: str = "") -> None:
    key = name.lower().replace("tma_", "").replace("_", " ")
    frac = pct / 100.0
    if key in TMA_LEVEL2:
        canon = TMA_LEVEL2[key]
        label = f"{canon} (level 2)" + (f" [{pmu}]" if pmu else "")
        if pmu != "cpu_atom":
            a.level2.setdefault(canon, frac)
        if all(x.name != label for x in a.metrics):
            a.metrics.append(Metric(name=label, value=round(frac, 4), unit="of slots", formula=origin, inputs=[origin]))
        return
    canon = TMA_NAMES.get(key, None) or TMA_NAMES.get(name.lower())
    if canon is None:
        return
    label = f"{canon} (level 1)" + (f" [{pmu}]" if pmu else "")
    m = Metric(name=label, value=round(frac, 4), unit="of slots", formula=origin, inputs=[origin])
    if intel_pcore and canon in TMA_THRESHOLDS:
        text, limit = TMA_THRESHOLDS[canon]
        m.source = TMA_SOURCE
        if frac > limit:
            m.flag = f"above Intel's threshold {text}"
            if all(n != canon for _, n in a.flagged):
                a.flagged.append((frac / limit, canon))
    if all(x.name != label for x in a.metrics):
        a.metrics.append(m)


def parse_perf_plain(lines: list[str], a: Analysis) -> bool:
    found = False
    td_header: list[str] | None = None
    td_rows: list[list[float]] = []
    group_pmu = ""
    group_kind = ""
    in_block = False
    for line in lines:
        if not line.strip() or line.strip() in a.consumed:
            continue
        h = HEADER.search(line)
        if h:
            in_block, found = True, True
            a.notes.append(f"perf stat of {h.group(1).strip()}")
            continue
        m = ELAPSED.match(line)
        if m:
            a.elapsed = parse_number(m.group(1), integer=False)
            continue
        if re.match(r"^\s*[\d.,]+\s+seconds\s+(user|sys)", line):
            continue
        low = line.lower()
        # old --topdown: a header of the four level 1 names, then rows of percentages
        if "retiring" in low and "frontend bound" in low and "%" not in low:
            td_header = [n for n in ("retiring", "bad speculation", "frontend bound", "backend bound") if n in low]
            td_header.sort(key=low.index)
            found = in_block = True
            continue
        if td_header is not None and "%" in line and not PLAIN.match(line):
            vals = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)%", line)]
            if len(vals) >= len(td_header):
                td_rows.append(vals[: len(td_header)])
                continue
        g = TOPDOWN_GROUP.search(line)
        if g:
            group_kind, group_pmu = g.group(1), (g.group(2) or "")
            found = True
        tma = TMA_LINE.search(line)
        if tma and (group_kind or tma.group(2)):
            intel = bool(tma.group(2)) and group_pmu != "cpu_atom" and not group_kind.lower().startswith("pipeline")
            _record_tma(a, tma.group(3), float(tma.group(1)), f"perf {group_kind or 'tma'}", intel, group_pmu)
            found = True
            if tma.group(2):
                a.signals.add("intel")
            elif group_kind.lower().startswith("pipeline"):
                a.signals.add("amd")
            elif group_kind.lower().startswith("topdown") and tma.group(3).islower():
                a.signals.add("arm")  # perf's Arm metrics: TopdownL1 with plain lower-case names
            if not PLAIN.match(line):
                r = RUNNING.search(line)
                if r:  # the share of the events behind this metric group
                    a.shares.append((group_kind + (f" [{group_pmu}]" if group_pmu else ""), float(r.group(1))))
                continue
        if line.lstrip().startswith("#"):
            continue
        pm = PLAIN.match(line)
        if not pm:
            if in_block and not g and not line.lstrip().startswith(("Performance", "Some events")):
                a.unparsed.append(line.strip()[:200])
            continue
        raw = pm.group("event").rstrip(",")
        key, pmu, mods = split_event(raw)
        c = Count(event=key, raw=raw, pmu=pmu, mods=mods, unit=pm.group("unit") or "")
        v = pm.group("value")
        if v.startswith("<"):
            c.status = v.strip("<>")
        else:
            c.value = parse_number(v, integer=not c.unit)
        r = RUNNING.search(pm.group("rest"))
        if r:
            c.running = float(r.group(1))
        if pm.group("ts"):
            c.ts = float(pm.group("ts"))
        a.counts.append(c)
        found = True
    if td_header and td_rows:
        avg = [sum(r[i] for r in td_rows) / len(td_rows) for i in range(len(td_header))]
        for name, pct in zip(td_header, avg):
            _record_tma(a, name, pct, "perf stat --topdown" + (f", mean of {len(td_rows)} rows" if len(td_rows) > 1 else ""), True)
    if found and "perf stat" not in a.kinds:
        a.kinds.append("perf stat")
    return found


CSV_EVENT = re.compile(r"[A-Za-z][\w.:/=,@+-]*")
CSV_UNIT = re.compile(r"[\w%/.-]{0,16}")


def parse_perf_csv(lines: list[str], a: Analysis) -> bool:
    sep = None
    for cand in (",", ";", "\t"):
        hits = sum(1 for ln in lines if ln.count(cand) >= 3 and re.search(r"[A-Za-z]", ln))
        if hits >= max(1, len(lines) // 3):
            sep = cand
            break
    if sep is None:
        return False
    found = False
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        fields = _rejoin_event(line.split(sep), sep)
        for i in range(len(fields) - 2):
            v = fields[i].strip()
            ev = fields[i + 2].strip()
            unit = fields[i + 1].strip()
            # an event name has no spaces and a unit is one short token: '2,000,000 orders (320 MB), ~26 ms'
            # in a pasted note splits into a number, '000 orders (320 MB)' and '~26 ms', which are neither
            if not (CSV_EVENT.fullmatch(ev) and CSV_UNIT.fullmatch(unit)):
                continue
            if re.fullmatch(r"[\d.]+", v) or v in ("<not counted>", "<not supported>"):
                key, pmu, mods = split_event(ev)
                c = Count(event=key, raw=ev, pmu=pmu, mods=mods, unit=unit)
                if v.startswith("<"):
                    c.status = v.strip("<>")
                else:
                    c.value = float(v)
                if len(fields) > i + 4 and re.fullmatch(r"[\d.]+", fields[i + 4].strip()):
                    c.running = float(fields[i + 4])
                if i >= 1 and re.fullmatch(r"\d+\.\d+", fields[0].strip()):
                    c.ts = float(fields[0])  # -I: the time stamp leads the line
                a.counts.append(c)
                found = True
                break
    if found:
        a.kinds.append("perf stat -x")
    return found


def _rejoin_event(fields: list[str], sep: str) -> list[str]:
    """'cpu/event=0x3c,umask=0x0/' is split by a comma separator: put it back."""
    out: list[str] = []
    buf: str | None = None
    for f in fields:
        if buf is not None:
            buf += sep + f
            if f.endswith("/") or re.search(r"/\w*$", f):
                out.append(buf)
                buf = None
            continue
        if re.match(r"^[\w.-]+/[^/]*$", f) and not f.endswith("/"):
            buf = f
            continue
        out.append(f)
    if buf is not None:
        out.append(buf)
    return out


def parse_perf_json(lines: list[str], a: Analysis) -> bool:
    found = False
    for line in lines:
        s = line.strip()
        if not (s.startswith("{") and s.endswith("}")):
            continue
        try:
            obj = json.loads(s)
        except ValueError:
            continue
        if "event" not in obj or "counter-value" not in obj:
            continue
        key, pmu, mods = split_event(str(obj["event"]))
        c = Count(event=key, raw=str(obj["event"]), pmu=pmu, mods=mods, unit=str(obj.get("unit") or ""))
        val = str(obj.get("counter-value", ""))
        if val.startswith("<"):
            c.status = val.strip("<>")
        else:
            try:
                c.value = float(val)
            except ValueError:
                continue
        if obj.get("pcnt-running") is not None:
            c.running = float(obj["pcnt-running"])
        if obj.get("interval") is not None:
            c.ts = float(obj["interval"])
        a.counts.append(c)
        found = True
    if found:
        a.kinds.append("perf stat -j")
    return found


# ----- perf's own errors ----------------------------------------------------------------

METRIC_GROUP_MISSING = re.compile(r"Cannot find metric or group [`'\"]?([\w.-]+?)['`\"]?\s*$")
NO_ACCESS = re.compile(
    r"perf_event_paranoid|Access to performance monitoring and observability operations is limited|"
    r"No permission to enable|may not have permission to collect",
    re.I,
)
SYSCALL = re.compile(r"sys_perf_event_open\(\) syscall returned with (\d+) \(([^)]*)\) for event \(([^)]*)\)")
EVENT_SYNTAX = re.compile(r"event syntax error: '([^']*)'")
UNKNOWN_TERM = re.compile(r"unknown (?:term|event) '([^']*)'", re.I)
EVENT_UNSUPPORTED = re.compile(r"The ([\w:./=,-]+) event is not supported")
NMI = re.compile(r"Some events weren't counted|nmi_watchdog", re.I)
WORKLOAD = re.compile(r"Workload failed: (.+?)\s*$")
USAGE = re.compile(r"^\s*(Usage: perf|or: perf|-\w, --[\w-]+|--[\w-]+(\s|=|$)|Run 'perf list'|\\_{3}|perf stat \.\.\.\s*$)")
ERRNO_NOTE = {
    "2": "the event does not exist on this CPU or kernel; virtual machines without a virtual PMU expose few or no hardware events",
    "95": "the event does not exist on this CPU or kernel; virtual machines without a virtual PMU expose few or no hardware events",
    "13": "permission was refused; /proc/sys/kernel/perf_event_paranoid and CAP_PERFMON decide who may count",
    "1": "permission was refused; /proc/sys/kernel/perf_event_paranoid and CAP_PERFMON decide who may count",
    "22": "the kernel rejected its settings, a modifier or field this PMU does not accept",
    "16": "another user holds the counter, such as the NMI watchdog or another profiler",
    "24": "too many files are open: events times CPUs exceeded the open-file limit (ulimit -n)",
}


def parse_perf_errors(lines: list[str], a: Analysis) -> bool:
    """perf's messages when a command fails, restated with what perf itself says to do."""
    notes: list[str] = []
    topics: list[str] = []
    routing: list[str] = []
    usage = False

    def add(note: str, topic: str | None = None, words: str | None = None) -> None:
        if note not in notes:
            notes.append(note)
        if topic and topic not in topics:
            topics.append(topic)
        if words and words not in routing:
            routing.append(words)

    for line in lines:
        s = line.strip()
        if not s:
            continue
        hit = True
        m = METRIC_GROUP_MISSING.search(s)
        if m:
            group = m.group(1)
            note = (
                f"This perf has no metric group {group}. perf's metric groups come from per-CPU event tables built "
                "into perf, so an older perf, or a CPU model its tables do not list, lacks them; `perf list "
                "metricgroups` shows the groups this perf has."
            )
            if group.lower().startswith("pipelinel"):
                note += (
                    " AMD's level 1 split needs Zen 4 or later; perf's amdzen4 pipeline.json gives its formulas "
                    "in raw events, which can be counted directly."
                )
                a.vendor_hint = "amd"
                add(note, "top-down analysis", "amd zen pipeline")
            elif group.lower().startswith("topdownl"):
                note += " On Intel, `perf stat --topdown` or toplev give level 1 from older perf versions too."
                add(note, "top-down analysis", "top-down")
            else:
                add(note, "counters, events", "perf metric groups")
        elif NO_ACCESS.search(s):
            add(
                "perf was refused access to the counters. Its own message names the fix: lower "
                "/proc/sys/kernel/perf_event_paranoid, or run with CAP_PERFMON (or CAP_SYS_ADMIN); "
                "perf_event_open(2) defines each setting.",
                "counters, events", "perf_event_paranoid",
            )
        elif SYSCALL.search(s):
            m = SYSCALL.search(s)
            why = ERRNO_NOTE.get(m.group(1), "perf's message above gives the reason")
            add(f"The kernel would not open {m.group(3)} (error {m.group(1)}, {m.group(2)}): {why}.", "counters, events", "perf_event_open")
        elif EVENT_SYNTAX.search(s) or UNKNOWN_TERM.search(s):
            m = EVENT_SYNTAX.search(s) or UNKNOWN_TERM.search(s)
            add(f"perf did not recognise the event {m.group(1)}; `perf list` shows the names this perf knows for this CPU.", "counters, events")
        elif EVENT_UNSUPPORTED.search(s):
            ev = EVENT_UNSUPPORTED.search(s).group(1)
            add(
                f"{ev} is not supported here: not available on this CPU or kernel (common on virtual machines and macOS).",
                "counters, events",
            )
        elif NMI.search(s):
            add(
                "perf reports that some events were not counted and suggests turning off the NMI watchdog, which "
                "keeps one counter for itself (echo 0 > /proc/sys/kernel/nmi_watchdog as root, restored afterwards).",
                "counters, events", "multiplexing counters",
            )
        elif WORKLOAD.search(s):
            add(f"perf could not start the measured command ({WORKLOAD.search(s).group(1)}); nothing was measured.")
        elif USAGE.search(line) or s in ("Error:", "Error"):
            usage = usage or s.startswith(("Usage:", "-", "--"))
        else:
            hit = False
        if hit:
            a.consumed.add(s)
    if not notes:
        return False
    a.kinds.append("perf error")
    a.notes.extend(notes)
    a.topics.extend(t for t in topics if t not in a.topics)
    a.routing.extend(r for r in routing if r not in a.routing)
    if usage:
        a.notes.append("perf printed its usage text after the error; the options it lists are its own help, not results.")
    return True


# ----- the vendor ----------------------------------------------------------------------


def detect_vendor(a: Analysis) -> None:
    """Only the PMUs and events decide; one vendor or none."""
    found = set(a.signals)
    for c in a.counts:
        for pattern, vendor in VENDOR_PMU:
            if c.pmu and pattern.search(c.pmu):
                found.add(vendor)
        ev = c.event.lower()
        raw = (c.raw.split("/")[1] if c.raw.count("/") >= 2 else c.raw.split(":")[0]).lower()
        if ARM_EVENT.match(raw):
            found.add("arm")
        elif ev in INTEL_EVENTS or ev.startswith(INTEL_PREFIXES):
            found.add("intel")
        elif AMD_EVENT.match(ev):
            found.add("amd")
        elif ARM_EVENT.match(ev):
            found.add("arm")
    a.vendor = found.pop() if len(found) == 1 else None


# ----- toplev --------------------------------------------------------------------------

TOPLEV = re.compile(
    r"^\s*(?:(?P<where>[SCN]\d[\w-]*)\s+)?(?P<area>FE|BAD|BE|RET|BE/Mem|BE/Core|FE/\w+|Info\.\w+)\s+"
    r"(?P<node>[A-Z][\w.]*)\s+(?P<unit>%\s*\w+|\w+)\s+(?P<value>\d+(?:\.\d+)?)(?P<rest>.*)$"
)


def parse_toplev(lines: list[str], a: Analysis) -> bool:
    found = False
    level1: dict[str, list[float]] = {}
    for line in lines:
        m = TOPLEV.match(line)
        if not m:
            continue
        found = True
        node, value, rest = m.group("node"), float(m.group("value")), m.group("rest")
        unit = m.group("unit")
        if "." not in node and node in TMA_THRESHOLDS and "%" in unit:
            level1.setdefault(node, []).append(value)
        elif "%" in unit:
            a.metrics.append(Metric(name=node, value=round(value / 100.0, 4), unit="of slots", formula="toplev", inputs=["toplev"]))
            if node.count(".") == 1 and node.split(".")[1] in TMA_LEVEL2.values():
                a.level2.setdefault(node.split(".")[1], value / 100.0)
        if "<==" in rest:
            a.notes.append(f"toplev marks {node} as the bottleneck")
            a.routing.append(node.replace("_", " ").replace(".", " ").lower())
        mux = re.search(r"\[\s*(\d+(?:\.\d+)?)%\]", rest)
        if mux and float(mux.group(1)) < 100:
            a.counts.append(Count(event=node, raw=node, running=float(mux.group(1))))
    for node, vals in level1.items():
        _record_tma(a, node, sum(vals) / len(vals), "toplev" + (f", mean of {len(vals)} rows" if len(vals) > 1 else ""), True)
    if found:
        a.kinds.append("toplev")
        a.signals.add("intel")  # toplev runs Intel's TMA tree only
    return found


# ----- compiler remarks ------------------------------------------------------------------

REMARK = re.compile(r"(?P<loc>[^\s:]+:\d+(?::\d+)?):\s*(?P<kind>missed|optimized|note|remark|warning):\s*(?P<msg>.+?)\s*$")


def parse_remarks(lines: list[str], a: Analysis) -> bool:
    found = False
    reasons: list[str] = []
    missed: list[str] = []
    done: list[str] = []
    clang_loops: set[str] = set()  # clang: one -Rpass-missed remark per loop, its reasons at other lines
    gcc_loops: set[str] = set()  # gcc: a loop's "couldn't vectorize" and its reason share one location
    for line in lines:
        m = REMARK.search(line)
        if not m:
            continue
        msg = m.group("msg")
        low = msg.lower()
        if "vectoriz" not in low and "vectorise" not in low and "loop" not in low:
            continue
        found = True
        if m.group("kind") == "note" and re.search(r"vectori[sz]ed \d+ loops? in function", low):
            continue  # gcc's per-function tally repeats the remarks above it
        flag = re.search(r"\[-R(pass|pass-missed|pass-analysis)=([\w-]+)\]", msg)
        text = re.sub(r"\s*\[-R[\w-]+=[\w-]+\]", "", msg).strip().rstrip(".")
        remark = f"{m.group('loc')}: {text}"
        success = m.group("kind") == "optimized" or "vectorized loop" in low or (flag and flag.group(1) == "pass")
        if success:
            if remark not in done:
                done.append(remark)
            continue
        if remark not in missed:
            missed.append(remark)
        at_line = ":".join(m.group("loc").split(":")[:2])
        if flag and flag.group(1) == "pass-missed":
            clang_loops.add(at_line)
        elif not flag and ("couldn't vectorize" in low or "not vectorized" in low):
            gcc_loops.add(at_line)
        for pattern, words in REMARK_REASONS:
            if re.search(pattern, low) and words not in reasons:
                reasons.append(words)
        if re.search(r"reorder floating[- ]point|unsafe fp math|fp reduction", low):
            a.benchmarks.append(REDUCTION_BENCHMARK)  # the vectoriser declined a float reduction
    if found:
        a.kinds.append("compiler remarks")
        a.remarks = missed + done  # what failed first: a summary cut short keeps the reasons
        a.routing.append("auto-vectorization vectorizer remarks")
        a.routing.extend(reasons)
        loops = len(clang_loops) or len(gcc_loops)
        if loops:
            a.notes.append(f"{loops} loop(s) not vectorised; the reasons are in the remarks")
    return found


# ----- assembly and code -----------------------------------------------------------------

ASM_LINE = re.compile(
    r"^\s*(?:[0-9a-f]+:\s+(?:[0-9a-f]{2}\s)+\s*"  # objdump -d: address and opcode bytes
    r"|[0-9a-f]+:\s+"  # objdump --no-show-raw-insn, llvm-objdump: the address alone
    r"|(?:=>\s*)?0x[0-9a-f]+(?:\s*<[^>]*>)?:\s+"  # gdb disassemble: 0x... <+4>:
    r"|\d+\.\d+\s*[│|:]\s*|[│|]\s*)?"  # perf annotate
    r"(?P<mn>(?:lock\s+)?[a-z][a-z0-9]{1,15}(?:\.[a-z0-9]+)?)\s+(?P<ops>[%$\w\[\](){},.:+*#-][^;]*)$"
)
REGISTER = re.compile(r"%?\b([xyz]mm\d+|[re][a-ds][xi]|r\d+[dwb]?|[vqdsbh]\d+|[xw]\d+)\b")
SCALAR_ADD = re.compile(r"v?adds[sd]")
PACKED_MUL = re.compile(r"v?mulp[sd]|vfn?m(add|sub)\d*p[sd]")

REDUCTION_WORDS = "floating point reduction reassociation dependency chain accumulators"
REDUCTION_BENCHMARK = "03-latency-vs-throughput"  # one dependency chain against independent accumulators
LAYOUT_BENCHMARK = "07-aos-vs-soa-simd"  # array of structs against structure of arrays
LOOKS_LIKE_CODE = re.compile(
    r"\b(for|while|if)\s*\(|\breturn\b[^;\n]*;|#\s*include\b"
    r"|\b(void|int|float|double|char|struct|size_t|u?int\d+_t|auto|const)\b\s*\**\s*\w+\s*[(=;\[{]"
)
FLOAT_ACC = re.compile(r"\b(?:float|double)\s+(\w+)\s*=\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?[fFlL]?\s*[;,]")
LOOP = re.compile(r"\b(?:for|while)\s*\(")
REORDER_ALLOWED = re.compile(r"-ffast-math|-fassociative-math|-Ofast\b|\breduction\s*\(\s*[+*]")
EARLY_EXIT = re.compile(r"\b(?:for|while)\s*\([^)]*\)[^;]*?(?:\{[^{}]*?)?\b(?:return|break)\b", re.S)
AOS_FIELD = re.compile(r"\b\w+\s*\[[^\]\n]+\]\s*\.\s*[A-Za-z_]\w*")


def float_sums(text: str) -> list[str]:
    """Float and double scalars that a loop adds into: `float s = 0; for (...) s += a[i] * b[i];`."""
    names: list[str] = []
    for m in FLOAT_ACC.finditer(text):
        name, rest = m.group(1), text[m.end() :]
        loop = LOOP.search(rest)
        if loop and name not in names and re.search(
            rf"\b{re.escape(name)}\s*[+-]=|\b{re.escape(name)}\s*=\s*{re.escape(name)}\s*[+-]", rest[loop.start() :]
        ):
            names.append(name)
    return names


def parse_asm(lines: list[str], a: Analysis) -> bool:
    mnemonics: dict[str, int] = {}
    n_lines = 0
    for line in lines:
        m = ASM_LINE.match(line)
        if not m or not REGISTER.search(m.group("ops")):
            continue
        n_lines += 1
        mn = m.group("mn")
        if mn.startswith("lock "):
            mn = mn[5:]
            if "atomic contention" not in a.routing:
                a.routing.append("atomic contention")
        mnemonics[mn] = mnemonics.get(mn, 0) + 1
    if n_lines < 3:
        return False
    a.kinds.append("assembly")
    text = "\n".join(lines)
    if re.search(r"\bzmm\d+", text):
        a.routing.append("avx512")
    elif re.search(r"\bymm\d+", text):
        a.routing.append("avx2")
    if re.search(r"\b[zp]\d+\.[bhsd]\b|\bwhilelo\b|\bptrue\b", text):
        a.routing.append("sve")
    for mn in sorted(mnemonics, key=lambda k: -mnemonics[k])[:12]:
        if mn not in a.terms:
            a.terms.append(mn)
        for pattern, words in ASM_FAMILIES:
            if re.search(pattern, mn) and words not in a.routing:
                a.routing.append(words)
    scalar_adds = {mn: n for mn, n in mnemonics.items() if SCALAR_ADD.fullmatch(mn)}
    packed = {mn: n for mn, n in mnemonics.items() if PACKED_MUL.fullmatch(mn)}
    if sum(scalar_adds.values()) >= 4 and packed:
        adds = ", ".join(f"{mn} x{n}" for mn, n in scalar_adds.items())
        muls = ", ".join(f"{mn} x{n}" for mn, n in packed.items())
        a.notes.append(
            f"Packed multiplies ({muls}) feed a run of scalar adds ({adds}): the shape of an in-order float "
            "reduction, whose adds stay one serial dependency chain however wide the vectors are."
        )
        a.routing.append(REDUCTION_WORDS)
        a.topics.append("auto-vectorisation")
        a.benchmarks.append(REDUCTION_BENCHMARK)
    return True


def parse_code(text: str, a: Analysis) -> bool:
    if not re.search(r"[;{}]\s*$|#include|#pragma|\bfn\b|\bdef\b|\bfor\s*\(", text, re.M):
        return False
    found = False
    for pattern, words in CODE_PATTERNS:
        hits = re.findall(pattern, text)
        if hits:
            found = True
            if words not in a.routing:
                a.routing.append(words)
            for h in re.findall(r"\b_mm\d*_\w+", text)[:6] if "intrinsics" in words else []:
                if h not in a.terms:
                    a.terms.append(h)
    # what the loops do, beyond the APIs they call. A loop over an array of structs is about the bytes
    # it moves before it is about its adds: its layout leads, and a float sum in it comes second.
    if LOOP.search(text) and AOS_FIELD.search(text):
        found = True
        a.routing.append("struct layout hot cold field splitting structure of arrays cache line utilisation")
        a.topics += ["struct layout", "data layout"]
        a.benchmarks.append(LAYOUT_BENCHMARK)
    sums = float_sums(text)
    if sums and not REORDER_ALLOWED.search(text):
        found = True
        a.routing.append(REDUCTION_WORDS)
        a.topics.append("auto-vectorisation")
        a.benchmarks.append(REDUCTION_BENCHMARK)
        names = ", ".join(f"`{n}`" for n in sums[:3])
        a.notes.append(
            f"{names}: a float sum carried across loop iterations. Without -ffast-math or -fassociative-math the "
            "compiler keeps its adds in source order, one serial chain of add latencies, even where a remark says "
            "the loop was vectorised."
        )
    if EARLY_EXIT.search(text):
        found = True
        a.routing.append("control flow branches predication early exit")
    if found or LOOKS_LIKE_CODE.search(text):
        a.kinds.append("code")  # code with nothing to route on still is code, not search words
        return True
    return False


# ----- metrics ---------------------------------------------------------------------------


def _totals(a: Analysis) -> dict[tuple[str, str, str], float]:
    """Counts summed per (pmu, event, modifiers): per-CPU and interval lines add up."""
    out: dict[tuple[str, str, str], float] = {}
    for c in a.counts:
        if c.value is not None and c.status == "ok":
            k = (c.pmu, c.event, c.mods)
            out[k] = out.get(k, 0.0) + c.value
    return out


def compute_metrics(a: Analysis) -> None:
    totals = _totals(a)
    groups = {(p, m) for (p, _, m) in totals}
    generic: list[str] = []  # topics of the plain ratios; used only without top-down data
    stamps = sorted({c.ts for c in a.counts if c.ts is not None})
    if len(stamps) >= 2:
        if a.elapsed is None:
            a.elapsed = stamps[-1]
        a.notes.append(
            f"{len(stamps)} intervals over {stamps[-1]:.4g} s (perf stat -I): the counts are summed across them, so "
            "the metrics describe the whole run, not any one interval."
        )
    hybrid = {"cpu_core", "cpu_atom"} <= {p for (p, _, _) in totals}

    def get(pmu: str, mods: str, ev: str) -> float | None:
        return totals.get((pmu, ev, mods))

    for pmu, mods in sorted(groups):
        tag = "/".join(x for x in (pmu, mods) if x)
        sfx = f" [{tag}]" if tag else ""

        def ratio(name, num, den, scale=1.0, unit="", formula=""):
            n, d = get(pmu, mods, num), get(pmu, mods, den)
            if n is None or not d:
                return
            a.metrics.append(
                Metric(name=name + sfx, value=round(n / d * scale, 4), unit=unit, formula=formula or f"{num} / {den}", inputs=[num, den])
            )
            if name in ROUTING and ROUTING[name] not in generic:
                generic.append(ROUTING[name])

        ratio("IPC", "instructions", "cycles", formula="instructions / cycles")
        ratio("branch miss rate", "branch-misses", "branches", 100, "%")
        ratio("branch MPKI", "branch-misses", "instructions", 1000, "per 1k instructions")
        ratio("L1d miss rate", "L1-dcache-load-misses", "L1-dcache-loads", 100, "%")
        ratio("L1d MPKI", "L1-dcache-load-misses", "instructions", 1000, "per 1k instructions")
        ratio("LLC miss rate", "LLC-load-misses", "LLC-loads", 100, "%")
        ratio("LLC MPKI", "LLC-load-misses", "instructions", 1000, "per 1k instructions")
        ratio("cache miss rate", "cache-misses", "cache-references", 100, "%")
        ratio("cache MPKI", "cache-misses", "instructions", 1000, "per 1k instructions")
        ratio("dTLB miss rate", "dTLB-load-misses", "dTLB-loads", 100, "%")
        ratio("dTLB MPKI", "dTLB-load-misses", "instructions", 1000, "per 1k instructions")
        ratio("iTLB miss rate", "iTLB-load-misses", "iTLB-loads", 100, "%")
        ratio("iTLB MPKI", "iTLB-load-misses", "instructions", 1000, "per 1k instructions")
        ratio("frontend stall share", "stalled-cycles-frontend", "cycles", 100, "% of cycles")
        ratio("backend stall share", "stalled-cycles-backend", "cycles", 100, "% of cycles")
        # perf divides by task-clock for its GHz and /sec columns; so do these
        task = totals.get(("", "task-clock", mods)) if not pmu or pmu == "cpu" else None
        cycles = get(pmu, mods, "cycles")
        if task and cycles and not hybrid:
            a.metrics.append(
                Metric(name="frequency" + sfx, value=round(cycles / (task * 1e6), 3), unit="GHz",
                       formula="cycles / task-clock (ns)", inputs=["cycles", "task-clock"])
            )
        slots = get(pmu, mods, "slots")
        if slots:
            for ev, name in (
                ("topdown-retiring", "Retiring"),
                ("topdown-bad-spec", "Bad_Speculation"),
                ("topdown-fe-bound", "Frontend_Bound"),
                ("topdown-be-bound", "Backend_Bound"),
            ):
                v = get(pmu, mods, ev)
                if v is not None:
                    _record_tma(a, name, 100.0 * v / slots, f"{ev} / slots", pmu != "cpu_atom", pmu)
    if not any("level 1" in m.name for m in a.metrics):
        a.routing.extend(g for g in generic[:3] if g not in a.routing)
    if hybrid and any(ev == "cycles" for (_, ev, _) in totals):
        a.notes.append(
            "No frequency is given: task-clock covers P-cores and E-cores together, so dividing either core type's "
            "cycles by it (as perf's GHz column does) is not that core type's clock."
        )
    task_ms = sum(v for (_, ev, _), v in totals.items() if ev == "task-clock")
    for (pmu, ev, mods), v in totals.items():
        if ev == "task-clock" and a.elapsed:
            a.metrics.append(
                Metric(name="CPUs utilised", value=round(v / 1000.0 / a.elapsed, 3), formula="task-clock (ms) / 1000 / elapsed (s)", inputs=["task-clock", "elapsed"])
            )
        for name, event in (("context switches", "context-switches"), ("page faults", "page-faults")):
            if ev != event:
                continue
            if task_ms:
                a.metrics.append(
                    Metric(name=f"{name} per second", value=round(v / (task_ms / 1000.0), 1), unit="/s of task-clock",
                           formula=f"{event} / task-clock (s)", inputs=[event, "task-clock"])
                )
            elif a.elapsed:
                a.metrics.append(
                    Metric(name=f"{name} per second", value=round(v / a.elapsed, 1), unit="/s",
                           formula=f"{event} / elapsed", inputs=[event, "elapsed"])
                )


def trust_notes(a: Analysis) -> None:
    running = [(c.running, c.raw) for c in a.counts if c.running is not None and c.status == "ok"]
    running += [(share, what) for what, share in a.shares]
    if running and min(running)[0] < 99.99:
        low, what = min(running)
        a.notes.append(
            f"Counters were multiplexed (lowest running share {low:.1f}%, {what}): perf scaled them up, so ratios "
            "between events counted at different times carry error, worst on short or phase-changing runs."
        )
        a.routing.append("multiplexing counters")
    for status in ("not counted", "not supported"):
        names = sorted({c.raw for c in a.counts if c.status == status})
        if not names:
            continue
        why = (
            "never scheduled (more events than counters, or the run ended first)"
            if status == "not counted"
            else "not available on this CPU or kernel (common on virtual machines and macOS)"
        )
        a.notes.append(f"{', '.join(names[:6])}: {status}, {why}; metrics needing them are left out.")
    pmus = {c.pmu for c in a.counts if c.pmu}
    if {"cpu_core", "cpu_atom"} <= pmus:
        a.notes.append("Hybrid CPU: P-core (cpu_core) and E-core (cpu_atom) counts are kept apart and never divided by each other.")
    # identifiers for exact search: the raw events actually printed
    for c in a.counts:
        name = c.raw.split("/")[1] if c.raw.count("/") >= 2 else c.raw.split(":")[0]
        if ("." in name or "_" in name) and name not in a.terms and len(a.terms) < 16:
            a.terms.append(name)


def _flag_topics(a: Analysis) -> tuple[list[str], list[str]]:
    """The list's subsections and the search words for each level over Intel's
    threshold, furthest over first. Backend_Bound splits by level 2 when it was
    measured, else by whether the memory side was counted at all."""
    topics: list[str] = []
    words: list[str] = []
    for _, canon in sorted(a.flagged, key=lambda x: -x[0]):
        words.append(TMA_ROUTING[canon])
        if canon != "Backend_Bound":
            topics += FLAG_TOPICS.get(canon, [])
            continue
        mem, core = a.level2.get("Memory_Bound"), a.level2.get("Core_Bound")
        if mem is not None or core is not None:
            side = "memory" if (mem or 0.0) >= (core or 0.0) else "core"
        elif any(MEMORY_EVENTS.match(c.event) for c in a.counts if c.status == "ok"):
            side = "memory"
        else:
            side = None
        if side == "memory":
            topics += MEMORY_TOPICS
            words.append("cache miss memory latency prefetch")
        elif side == "core":
            topics += CORE_TOPICS
            words.append("execution ports latency throughput")
    return topics, words


def analyse(text: str) -> Analysis:
    a = Analysis()
    if len(text) > MAX_CHARS:
        a.notes.append(f"Only the first {MAX_CHARS} characters were read.")
        text = text[:MAX_CHARS]
    lines = text.replace("\r\n", "\n").split("\n")[:MAX_LINES]
    parse_perf_errors(lines, a)
    if not parse_perf_json(lines, a):
        if not parse_perf_plain(lines, a):
            parse_perf_csv(lines, a)
    parse_toplev(lines, a)
    parse_remarks(lines, a)
    if not parse_asm(lines, a):
        parse_code(text, a)
    detect_vendor(a)
    compute_metrics(a)
    trust_notes(a)
    level1 = any("level 1" in m.name for m in a.metrics)
    if a.counts and "perf stat" in " ".join(a.kinds) and "top-down" not in a.routing and not level1:
        a.routing.append("perf stat counters")
    if level1:
        # top-down leads, then the levels over their thresholds, furthest first
        lead = ["top-down"]
        if any(m.source for m in a.metrics):
            lead.append("intel tma metrics")
        elif any("PipelineL" in m.formula for m in a.metrics):
            lead.append("amd zen pipeline")
        flag_topics, flag_words = _flag_topics(a)
        lead += flag_words
        a.routing = lead + [r for r in a.routing if r not in lead]
        a.topics.append("top-down analysis")
        a.topics += flag_topics
    elif any(k.startswith("perf stat") for k in a.kinds) and a.counts:
        a.notes.append(
            "No top-down data in this output. The list's method classifies the bottleneck next: perf stat --topdown "
            "or -M TopdownL1 (Intel), -M PipelineL1 (AMD Zen 4 and later), or toplev give the level 1 split."
        )
        a.topics.append("top-down analysis")
    if any(n.startswith("Counters were multiplexed") or ": not supported" in n for n in a.notes):
        a.topics.append("counters, events")
    if "compiler remarks" in a.kinds:
        a.topics.append("auto-vectorisation")
    if "atomics memory ordering" in a.routing or "atomic contention" in a.routing:
        a.topics += ["memory models and atomics", "cache-line contention"]
    if any(r in a.routing for r in ("gather", "avx512", "avx2", "sve", "intrinsics simd")):
        a.topics.append("simd instruction sets")
    if "locks contention" in a.routing or "allocator malloc" in a.routing:
        a.topics.append("locks, contention")
    a.routing = list(dict.fromkeys(a.routing))
    a.topics = list(dict.fromkeys(a.topics))
    a.benchmarks = list(dict.fromkeys(a.benchmarks))
    if not a.kinds:
        a.notes.append("No tool output was recognised; the text was used as extra search words.")
        a.terms = [w for w in re.findall(r"[A-Za-z_][\w.]{3,}", text)[:12]]
    return a
