"""Deterministic evidence-checker evals, including failures from an ARM investigation.

Run ``python tests/eval_evidence.py`` for per-case outcomes and aggregate errors.
Numbers below are synthetic test inputs, not performance measurements.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CPU = "AWS Graviton4, Arm Neoverse V2; one core pinned to CPU2. "
CLOCK = "Measured frequency 2.6 GHz, turbo off, SMT off. "
BUILD = "Compiler Clang 18.1.3 -O3. "
WORK = "Workload: B+ tree iterator benchmark, 100000 members. "
END = "Compared with baseline revision A. 6 runs with median elapsed time, 7% faster."


def claim(clock=CLOCK, cpu=CPU, build=BUILD, end=END):
    return cpu + clock + build + WORK + end


# id, text, expected verdict, fields that must be present, fields that must not be present
CASES = [
    ("complete", claim(), "quotable", set(range(1, 8)), set()),
    ("unknown-input-is-not-unknown-clock", claim() + " Input key distribution unknown.", "quotable", {3}, set()),
    ("disabled-smt", claim(clock="2.6 GHz, turbo disabled, SMT disabled. "), "quotable", {3}, set()),
    ("no-smt", claim(clock="2.6 GHz, turbo off, no SMT on this part. "), "quotable", {3}, set()),
    ("estimated-clock-dvfs", claim(clock="Estimated clock 2.6 GHz. DVFS is on and cannot be disabled. No SMT. "), "quotable", {3}, set()),
    ("six-word", claim(end=END.replace("6 runs", "Six runs")), "quotable", {7}, set()),
    ("six-abba-blocks", claim(end=END.replace("6 runs", "Six ABBA blocks")), "quotable", {7}, set()),
    ("three-aa-blocks", claim(end=END.replace("6 runs", "Three A/A blocks")), "quotable", {7}, set()),
    ("numeric-abba-blocks", claim(end=END.replace("6 runs", "6 ABBA blocks")), "quotable", {7}, set()),
    ("compact-clang-version", claim(build=BUILD.replace("Clang 18", "Clang18")), "quotable", {4}, set()),
    ("compact-gcc-version", claim(build="Compiler GCC14.2 -O3. "), "quotable", {4}, set()),
    ("pinned-core", claim(cpu=CPU.replace("one core pinned to", "one pinned core on")), "quotable", {2}, set()),
    ("single-pinned-thread", claim(cpu=CPU.replace("one core", "single pinned thread")), "quotable", {2}, set()),
    ("nominal-plus-measured", claim(clock="Nominal 2.5 GHz; measured frequency 2.6 GHz, turbo off, SMT off. "), "quotable", {3}, set()),
]

for name, clock in [
    ("turbo-unknown", "2.6 GHz, turbo state unknown, SMT off. "),
    ("smt-unknown", "2.6 GHz, turbo off, SMT state unknown. "),
    ("unknown-before-smt", "2.6 GHz, turbo off; unknown SMT state. "),
    ("smt-not-recorded", "2.6 GHz, turbo off, SMT was not recorded. "),
    ("turbo-not-known", "2.6 GHz, turbo state is not known, SMT off. "),
    ("turbo-unspecified", "2.6 GHz, turbo unspecified, SMT off. "),
    ("smt-unreported", "2.6 GHz, turbo off, SMT unreported. "),
    ("dvfs-unknown", "2.6 GHz, DVFS unknown, no SMT. "),
    ("coordinated-unknown", "2.6 GHz; turbo and SMT states unknown. "),
    ("coordinated-unknown-prefix", "2.6 GHz; unknown turbo and SMT states. "),
    ("frequency-unmeasured", "Nominal 2.6 GHz, turbo off, SMT off. Frequency during the run was not measured. "),
    ("frequency-unknown-with-number", "2.6 GHz advertised, turbo off, SMT off; actual frequency unknown. "),
    ("clock-unmeasured", "2.6 GHz, turbo off, SMT off. Runtime clock unmeasured. "),
    ("all-unknown", "Nominal 2.6 GHz; frequency, turbo and SMT state unknown. "),
    ("nominal-only-prefix", "Nominal frequency 2.6 GHz, turbo off, SMT off. "),
    ("nominal-only-suffix", "Frequency 2.6 GHz nominal, turbo off, SMT off. "),
    ("contradictory-smt", "2.6 GHz, turbo off, SMT off; SMT state unknown. "),
    ("original-false-positive", "Frequency 2.6 GHz nominal, turbo state unknown, SMT state unknown. Frequency during the run was not measured. "),
]:
    CASES.append((name, claim(clock=clock), "drop_number", {1, 2, 4, 5, 6, 7}, {3}))

CASES.extend([
    ("missing-clock", claim(clock=""), "drop_number", {1, 2, 4, 5, 6, 7}, {3}),
    ("abba-without-count", claim(end=END.replace("6 runs", "ABBA blocks")), "drop_number", set(), {7}),
    ("unrelated-compiler-word", claim(build="Compiler clangorous -O3. "), "drop_number", set(), {4}),
    ("no-number", "This paper defines the roofline model.", "no_number", set(), set()),
])


def evaluate(audit):
    rows = []
    for ident, text, verdict, present, absent in CASES:
        r = audit(text)
        states = {f.number: f.status for f in r.fields}
        ok = r.verdict == verdict and all(states[n] == "present" for n in present) and all(states[n] != "present" for n in absent)
        rows.append(dict(id=ident, ok=ok, expected=verdict, actual=r.verdict, fields=states))
    return dict(cases=len(rows), passed=sum(r["ok"] for r in rows),
                false_quotable=sum(r["actual"] == "quotable" and r["expected"] == "drop_number" for r in rows),
                false_rejection=sum(r["actual"] == "drop_number" and r["expected"] == "quotable" for r in rows), rows=rows)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from cpu_perf.evidence import audit
    print(json.dumps(evaluate(audit), indent=2))
