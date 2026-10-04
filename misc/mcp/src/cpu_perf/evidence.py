"""A heuristic audit of a performance claim against the list's seven-field rule
(README "What earns a place"; CONTRIBUTING Step 3). It reports what the text
states; a human or the model still judges whether each field is adequate."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

I = re.I

CPU_MODEL = re.compile(
    r"\b(xeon[\w\s+-]{0,24}?\d{3,5}\w*|xeon\s*(?:6|max|platinum|gold|silver)\w*|epyc\s*\d{3,4}\w*|"
    r"core\s*i[3579][- ]?\d{3,5}\w*|core\s*ultra\s*\d*\s*\w*|ryzen\s*\d?\s*\d{3,4}\w*|threadripper\s*\w*|"
    r"graviton\s*\d|neoverse[- ]?[nve]\d|ampere\s*(?:altra|one)\w*|ampereone|grace|axion|cobalt\s*\d+|"
    r"yitian\s*\d*|apple\s*m\d(?:\s*(?:pro|max|ultra))?|a64fx|power\s*\d+|cortex[- ]a\d+|opteron\s*\d*|"
    r"pentium\s*\w*|snapdragon\s*\w*|sparc\s*\w*|ultrasparc\s*\w*|mips\s*r\d+|tegra\s*\d*|"
    r"(?:intel|amd|arm|ibm|apple|ampere|nvidia)\s+[a-z]*\s*\d{2,5}\w*)",
    I,
)
MICROARCH = re.compile(
    r"\b(microarchitecture|uarch|skylake(?:-sp|-x)?|cascade\s*lake|cooper\s*lake|ice\s*lake|sapphire\s*rapids|"
    r"emerald\s*rapids|granite\s*rapids|sierra\s*forest|clearwater\s*forest|diamond\s*rapids|golden\s*cove|"
    r"raptor\s*cove|redwood\s*cove|lion\s*cove|crestmont|gracemont|skymont|haswell|broadwell|ivy\s*bridge|"
    r"sandy\s*bridge|westmere(?:-ex)?|nehalem|zen\s*\d\w?|k8|k10|bulldozer|piledriver|firestorm|icestorm|"
    r"avalanche|blizzard|everest|sawtooth|neoverse\s*[nve]\d|cortex-a\d+|armv[89](?:\.\d)?)\b",
    I,
)
CORES = re.compile(
    r"\b((?:\d+|one|two|four|six|eight|ten|twelve|sixteen|thirty-two|sixty-four|single)[- ]?"
    r"(?:p-|e-|performance |efficiency )?(?:cores?|threads?|vcpus?|hardware threads|sockets?|copies|processors?)|"
    r"single[- ]threaded|cores? used|taskset|numactl|\d+\s*t\b)",
    I,
)
FREQ = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ghz|mhz)\b", I)
TURBO = re.compile(r"\b(turbo|boost|dvfs|governor|fixed (?:frequency|clock)|frequency (?:locked|pinned|fixed)|p-?states?|cpufreq)\b", I)
SMT = re.compile(r"\b(smt|hyper-?threading|ht (?:on|off)|siblings?|no smt|smt: none)\b", I)
COMPILER = re.compile(
    r"\b(gcc|g\+\+|clang|llvm|icx|icpx|icc|msvc|rustc|go\s*1\.\d+|javac|openjdk|nvcc|xlc|armclang|aocc|"
    r"apple clang|cl\.exe)\b(?:\s*(?:version\s*)?\d+(?:\.\d+)*)?",
    I,
)
FLAGS = re.compile(
    r"(?<![\w-])-(?:O[0-3sfz]?\b|Ofast|march=\S+|mtune=\S+|mcpu=\S+|ffast-math|flto\S*|fprofile\S*|"
    r"std=\S+|f[a-z][a-z0-9-]+|m(?:avx\S*|sse\S*|fma)|C\s*opt-level=\d)",
)
WORKLOAD = re.compile(
    r"\b(workload|benchmark|spec\s*cpu\s*\d*|stream|triad|gemm|sgemm|matmul|kernel|dataset|input|"
    r"array of|elements|requests|queries|tokens|batch(?: size)?|redis|memcached|nginx|postgres|mysql|tpc-?\w*|"
    r"ycsb|pointer chase|loop|llama\S*|resnet\S*|bert\S*|model)\b|\b\d+\s*(?:kib|mib|gib|kb|mb|gb|elements|tokens|rows|bytes)\b",
    I,
)
BASELINE = re.compile(
    r"\b(baseline|vs\.?|versus|compared (?:to|with)|relative to|against|faster than|slower than|than|"
    r"speed-?up over|normali[sz]ed to|over (?:the )?(?:previous|prior|old|naive|scalar))\b",
    I,
)
STATISTIC = re.compile(
    r"\b(median|mean|average|geomean|geometric mean|min(?:imum)?|max(?:imum)?|p\d{2,3}(?:\.\d)?|percentiles?|"
    r"std(?:dev)?|standard deviation|cv|coefficient of variation|confidence interval|error bars?)\b",
    I,
)
RUNS = re.compile(
    r"\b((?:\d+|three|five|seven|ten|eleven|twenty)\s*(?:timed\s+)?(?:runs?|repetitions?|reps|trials|iterations|samples|rounds|passes)|"
    r"perf stat|rdtsc|clock_gettime|clock_monotonic\w*|now_ns|hyperfine|google benchmark|criterion|"
    r"warm-?up|llama-bench|likwid)\b",
    I,
)
NUMBER = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|x\b|×|times\b|ns\b|µs\b|us\b|ms\b|gb/s|gib/s|mb/s|gflop/?s|tflop/?s|"
    r"cycles\b|ipc\b|tokens?/s|req/s|rps\b|qps\b|mpps\b|ops/s|fold\b)",
    I,
)

FIELDS = (
    (1, "CPU model and microarchitecture", "Which CPU model, and which microarchitecture?"),
    (2, "core count used", "How many cores or threads did the run use?"),
    (3, "frequency, with turbo and SMT state", "What frequency, and were turbo (or DVFS) and SMT on or off?"),
    (4, "compiler and flags", "Which compiler, which version, and which flags?"),
    (5, "workload", "What exactly ran: program, input, sizes?"),
    (6, "baseline", "Faster or slower than what?"),
    (7, "measurement method", "How was it timed, how many runs, which statistic?"),
)

RULE_TEXT = (
    "Seven fields, and a number without all of them does not appear here. Miss one and the number is "
    "dropped; if the entry rests on that number, it moves to the watchlist or goes. (README, What earns a place)"
)


@dataclass
class FieldResult:
    number: int
    name: str
    status: str  # present | partial | missing
    found: list[str] = field(default_factory=list)
    note: str = ""
    question: str = ""


@dataclass
class EvidenceResult:
    claim: str
    numbers: list[str]
    fields: list[FieldResult]
    verdict: str  # quotable | drop_number | no_number
    summary: str
    rule: str = RULE_TEXT


def _find(rx: re.Pattern, text: str, limit: int = 3) -> list[str]:
    out: list[str] = []
    for m in rx.finditer(text):
        s = m.group(0).strip().rstrip(",.;:")
        if s and s.lower() not in (x.lower() for x in out):
            out.append(s)
        if len(out) >= limit:
            break
    return out


def audit(claim: str) -> EvidenceResult:
    text = " ".join(claim.split())
    numbers = _find(NUMBER, text, 8)
    results: list[FieldResult] = []

    def add(num: int, status: str, found: list[str], note: str = "") -> None:
        _, name, question = FIELDS[num - 1]
        results.append(FieldResult(num, name, status, found, note, "" if status == "present" else question))

    model, uarch = _find(CPU_MODEL, text), _find(MICROARCH, text)
    add(1, "present" if model and uarch else "partial" if model or uarch else "missing", model + uarch,
        "" if model and uarch else ("model without microarchitecture" if model else "microarchitecture without model" if uarch else ""))
    cores = _find(CORES, text)
    add(2, "present" if cores else "missing", cores)
    freq, turbo, smt = _find(FREQ, text), _find(TURBO, text), _find(SMT, text)
    have = [bool(freq), bool(turbo), bool(smt)]
    missing_parts = [n for n, h in zip(("frequency", "turbo/DVFS state", "SMT state"), have) if not h]
    add(3, "present" if all(have) else "partial" if any(have) else "missing", freq + turbo + smt,
        ("missing " + ", ".join(missing_parts)) if missing_parts and any(have) else "")
    comp, flags = _find(COMPILER, text), _find(FLAGS, text)
    add(4, "present" if comp and flags else "partial" if comp or flags else "missing", comp + flags,
        "" if comp and flags else ("compiler without flags" if comp else "flags without compiler" if flags else ""))
    work = _find(WORKLOAD, text)
    add(5, "present" if work else "missing", work)
    base = _find(BASELINE, text)
    add(6, "present" if base else "missing", base)
    stat, runs = _find(STATISTIC, text), _find(RUNS, text)
    add(7, "present" if stat and runs else "partial" if stat or runs else "missing", stat + runs,
        "" if stat and runs else ("statistic without run count or timer" if stat else "run count or timer without statistic" if runs else ""))

    complete = all(r.status == "present" for r in results)
    if not numbers:
        verdict = "no_number"
        summary = "No performance number found; the seven-field rule applies to numbers, so there is nothing to drop."
    elif complete:
        verdict = "quotable"
        summary = "All seven fields appear to be stated; the number may be quoted with them."
    else:
        gaps = [r.name for r in results if r.status != "present"]
        verdict = "drop_number"
        summary = f"Missing or incomplete: {'; '.join(gaps)}. Under the list's rule the number is dropped, or the entry resting on it moves to the watchlist."
    return EvidenceResult(claim=claim, numbers=numbers, fields=results, verdict=verdict, summary=summary)
