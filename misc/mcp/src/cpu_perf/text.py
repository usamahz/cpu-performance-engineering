"""Tokenising for search: compounds, British/American folding, a light
stemmer and a CPU-performance synonym map. The same normalisation runs over
documents and queries, so 'optimisation' finds 'optimization' and
'AVX-512' finds 'avx512'."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Bumped whenever tokens() changes what it emits; stored per passage so a
# library built by an older version is re-normalised in the background.
NORMALISER_VERSION = 2  # 2: joined identifier tokens for long names

TOKEN = re.compile(r"[a-z0-9]+(?:[+#]+|(?:[._\-/][a-z0-9]+)*)")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(\[])")

STOPWORDS = frozenset(
    """a an and are as at be been being but by can could did do does doing for from had has have
    having how i if in into is it its itself just me more most my no nor not of off on once only or
    other our out over own same she should so some such than that the their them then there these
    they this those through to too under until up very was we were what when where which while who
    whom why will with would you your yours about above after again against all am any because
    before below between both down during each few further here hers him his let ours themselves
    whats whose s t don isn aren wasn doesn""".split()
)

# Folding runs on documents and queries alike, so over-folding is harmless;
# these only avoid turning ordinary words into oddities.
ISE_EXCEPT = frozenset(
    """precise concise otherwise likewise clockwise enterprise promise premise exercise compromise
    expertise franchise merchandise paradise surprise noise osnoise raise praise poise arise rise
    wise guise cruise bruise treatise demise excise chaise""".split()
)
WORD_MAP = {
    "licence": "license",
    "licences": "license",
    "defence": "defense",
    "offence": "offense",
    "practise": "practice",
    "practised": "practiced",
    "catalogue": "catalog",
    "dialogue": "dialog",
    "analogue": "analog",
    "programme": "program",
    "programmes": "program",
    "grey": "gray",
    "aluminium": "aluminum",
    "c++": "cpp",
}
LL_WORDS = re.compile(r"^(model|cancel|label|travel|signal|level|tunnel|channel|fuel|total|marshal|panel|pixel|funnel)l(ed|ing|er|ers)$")
STEM_SUFFIXES = sorted(
    """izations ization izers izer ations ation itions ition ions ion ings ing edly ed ers er ies es ly
    ity ive al ments ment ness ance ence able ible izes ized izing ize ors or ist ists""".split(),
    key=len,
    reverse=True,
)


@lru_cache(maxsize=200_000)
def fold(word: str) -> str:
    """British to American spelling and plural to singular, for one lower-case word."""
    if word in WORD_MAP:
        return WORD_MAP[word]
    if not word.isalpha() or len(word) <= 3:
        return word
    w = word
    # plurals
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is", "os", "as")) and len(w) > 3:
        w = w[:-1]
    if w in WORD_MAP:
        return WORD_MAP[w]
    m = LL_WORDS.match(w)
    if m:
        return m.group(1) + m.group(2)
    if w not in ISE_EXCEPT and not re.search(r"size[ds]?$", w):
        m = re.match(r"^(.{4,})is(ation|ations|e|ed|es|er|ers|ing)$", w)
        if m:
            w = m.group(1) + "iz" + m.group(2)
    m = re.match(r"^(.{3,})ys(e|ed|es|ing)$", w)
    if m:
        w = m.group(1) + "yz" + m.group(2)
    if len(w) >= 6 and w.endswith("our"):
        w = w[:-3] + "or"
    m = re.match(r"^(.*[^aeiou])tre$", w)
    if m and len(w) >= 5:
        w = m.group(1) + "ter"
    return w


@lru_cache(maxsize=200_000)
def stem(word: str) -> str:
    """An aggressive stem used in a low-weight second space."""
    if not word.isalpha() or len(word) <= 4:
        return word
    w = word
    for _ in range(2):
        for suf in STEM_SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                w = w[: -len(suf)]
                break
        else:
            break
    if w.endswith("e") and len(w) > 4:
        w = w[:-1]
    return w


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return text.replace("c++", "cpp ")


MAX_IDENT = 64


def _identifier_joins(tok: str, parts: list[str]) -> list[str]:
    """Whole-name joins for compounds, so a long identifier (a perf event,
    a compiler flag, an intrinsic) matches as one term:
    'cycle_activity.stalls_l3_miss' -> cycleactivitystallsl3miss, plus
    cycleactivity and stallsl3miss for each '.'/'/' segment. Only ever adds
    to what earlier versions emitted, so old index rows still match."""
    out: list[str] = []
    joined = "".join(parts)
    if len(parts) <= 3:
        out.append(joined)
    elif not ("/" in tok) and len(joined) <= MAX_IDENT:
        out.append(joined)  # paths and URLs keep only their pieces
    if len(parts) > 2 and re.search(r"[./]", tok):
        for seg in re.split(r"[./]+", tok.strip("+#")):
            sub = [x for x in re.split(r"[_\-]+", seg) if x]
            if len(sub) > 1 and len("".join(sub)) <= MAX_IDENT and "".join(sub) != joined:
                out.append("".join(sub))
    return out


SEPARATORS = re.compile(r"[._\-/]+")
HAS_SEPARATOR = re.compile(r"[._\-/]")


def tokens(text: str, keep_stopwords: bool = False) -> list[str]:
    """Folded tokens in order, with compound and alpha+number joins added."""
    out: list[str] = []
    append = out.append
    raw = TOKEN.findall(_normalise(text))
    prev_alpha: str | None = None
    stop = () if keep_stopwords else STOPWORDS
    for tok in raw:
        if tok.isalnum():  # the common case: one plain word or number
            parts = [tok]
            compound = False
        else:
            core = tok.strip("+#")
            if HAS_SEPARATOR.search(tok):
                parts = [p for p in SEPARATORS.split(core) if p]
            else:
                parts = [core or tok]
            compound = len(parts) > 1
            if compound:
                out.extend(fold(j) for j in _identifier_joins(tok, parts))
        for p in parts:
            if len(p) == 1 and not p.isdigit() and p != "c":
                prev_alpha = None
                continue
            if p in stop:
                prev_alpha = None
                continue
            if not compound and prev_alpha is not None and p.isdigit() and len(p) <= 3:
                append(prev_alpha + p)
            append(fold(p))
            prev_alpha = p if (not compound and p.isalpha()) else None
    return out


def sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text).strip()
    return [s for s in SENTENCE.split(flat) if s]


# Each group's members expand to one another at query time (weight 0.6).
SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("smt", "hyperthreading", "hyper threading", "simultaneous multithreading"),
    ("dvfs", "turbo", "boost", "frequency scaling"),
    ("uop", "micro op", "micro-op", "microop"),
    ("tlb", "translation lookaside buffer", "page walk"),
    ("thp", "hugepage", "huge page", "transparent hugepage", "large page"),
    ("simd", "vector instructions", "avx", "neon", "sve", "sse"),
    ("avx512", "avx-512"),
    ("false sharing", "cache-line contention", "c2c", "cache line contention"),
    ("p99", "tail latency", "percentile"),
    ("gemm", "matmul", "matrix multiplication", "blas", "sgemm"),
    ("top-down", "topdown", "tma"),
    ("backend bound", "back-end bound", "frontend bound", "front-end bound", "bad speculation", "top-down",
     "pipeline slots", "slot accounting"),
    ("ipc", "instructions per cycle", "cpi", "cycles per instruction"),
    ("optimise away", "optimising away", "optimised away", "dead code elimination", "optimiser from deleting",
     "donotoptimize", "clobbermemory"),
    ("numa", "multi-socket", "first touch", "remote memory"),
    ("pmu", "performance counters", "hardware counters", "pebs", "ibs", "spe"),
    ("rob", "reorder buffer"),
    ("ilp", "instruction-level parallelism"),
    ("mlp", "memory-level parallelism"),
    ("lto", "link time optimisation", "thinlto"),
    ("pgo", "profile-guided optimisation", "fdo", "autofdo", "bolt", "propeller"),
    ("lock-free", "lockfree", "non-blocking", "rcu", "hazard pointers"),
    ("coordinated omission", "closed-loop", "open-loop"),
    ("roofline", "arithmetic intensity", "operational intensity"),
    ("quantization", "int8", "int4", "low-bit"),
    ("amx", "advanced matrix extensions"),
    ("sme", "scalable matrix extension"),
    ("io_uring", "asynchronous i/o"),
    ("kernel bypass", "dpdk", "xdp", "af_xdp", "spdk"),
    ("memory bandwidth", "stream", "triad"),
    ("flame graph", "flamegraph"),
    ("syscall", "system call", "vdso"),
    ("branch prediction", "branch predictor", "misprediction", "mispredict", "tage"),
    ("prefetch", "prefetcher", "prefetching"),
    ("store forwarding", "store-to-load forwarding", "memory disambiguation"),
    ("memory model", "memory ordering", "barriers", "fences", "atomics"),
    ("spr", "sapphire rapids"),
    ("gnr", "granite rapids"),
    ("emr", "emerald rapids"),
    ("srf", "sierra forest"),
    ("genoa", "zen 4", "zen4", "epyc 9004"),
    ("turin", "zen 5", "zen5", "epyc 9005"),
    ("bergamo", "zen 4c"),
    ("graviton4", "graviton 4", "neoverse v2", "grace", "axion"),
    ("cobalt 100", "neoverse n2", "yitian"),
    ("llm", "large language model", "inference", "llama", "ggml", "token generation"),
    ("profiler", "profiling", "perf", "vtune", "uprof"),
    ("jitter", "noise", "osnoise", "interference"),
    ("allocator", "malloc", "tcmalloc", "jemalloc", "mimalloc", "hoard"),
    ("work stealing", "thread pool", "cilk", "onetbb"),
    ("affinity", "pinning", "isolcpus", "cpuset"),
    ("interrupts", "irq", "napi"),
    ("cache partitioning", "rdt", "resctrl", "mpam"),
    ("compiler explorer", "godbolt"),
    ("auto-vectorisation", "autovectorization", "vectoriser", "loop vectorizer"),
    ("aos", "array of structs", "array of structures"),
    ("soa", "structure of arrays"),
    ("scaling laws", "amdahl", "gustafson", "universal scalability law"),
    ("queueing", "little's law", "queue"),
    ("cache miss", "cache misses", "miss latency"),
)


def synonym_phrases() -> list[tuple[tuple[str, ...], list[tuple[str, ...]]]]:
    """(phrase tokens, expansions as token tuples) for every group member."""
    out = []
    for group in SYNONYM_GROUPS:
        toks = [tuple(tokens(m)) for m in group]
        toks = [t for t in toks if t]
        for i, t in enumerate(toks):
            out.append((t, [o for j, o in enumerate(toks) if j != i]))
    return out
