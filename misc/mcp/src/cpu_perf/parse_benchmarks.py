"""Parse misc/benchmarks/NN-*/: the README parts, the seven machine fields,
the results tables and the raw.txt header.

The directory number NN is the README section the benchmark backs. The H1
inside each README is numbered one lower, so only its title text is used."""

from __future__ import annotations

import re

from .schema import Benchmark, Table

START, END = "<!-- results:start -->", "<!-- results:end -->"
H1 = re.compile(r"^# (?:\d{2}\.\s+)?(.+)$")
BOLD_LEAD = re.compile(r"^\*\*([A-Z][^*]{0,40}?)\.\*\*\s?")
MACHINE = re.compile(
    r"^- (CPU model and microarchitecture|Cores used|Frequency|Compiler and flags|Workload|Baseline|Method): (.*)$"
)
HEADER_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9 ()/._,-]{0,60}?): (.*)$")
RESULT = re.compile(r"^RESULT (\S+) (\S+) (\S+)$")
QUOTED = re.compile(r"[\"“]([^\"”]+)[\"”]")

MACHINE_KEYS = (
    "CPU model and microarchitecture",
    "Cores used",
    "Frequency",
    "Compiler and flags",
    "Workload",
    "Baseline",
    "Method",
)


def _slug_key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def parse_tables(md: str) -> list[Table]:
    """Pipe tables, each captioned by the paragraph just above it."""
    tables: list[Table] = []
    lines = md.splitlines()
    i = 0
    para: list[str] = []
    last_para: list[str] = []
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            header = [c.strip() for c in line.strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            caption = " ".join(para or last_para).strip()
            tables.append(Table(caption=caption, header=header, rows=rows))
            para, last_para = [], []
            continue
        if line:
            para.append(line)
        elif para:
            last_para, para = para, []
        i += 1
    return tables


def parse_metrics(raw: str) -> list[tuple[str, str, str]]:
    return [m.groups() for m in (RESULT.match(line) for line in raw.splitlines()) if m]


def parse_raw_header(raw: str) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in raw.splitlines():
        if line.strip() == "---":
            break
        if line.startswith("RESULT "):
            break
        m = HEADER_LINE.match(line)
        if m and m.group(1) not in header:
            header[m.group(1)] = m.group(2).strip()
    return header


def parse_benchmark(slug: str, readme: str, raw: str, bench_c: str, base: str) -> Benchmark:
    # Results first: the block carries its own bold leads (04's Line mode, Page mode).
    results_md = ""
    body = readme
    if START in readme and END in readme:
        head, rest = readme.split(START, 1)
        results_md, tail = rest.split(END, 1)
        results_md = results_md.strip()
        body = head + "\n[[RESULTS]]\n" + tail
    lines = body.splitlines()
    title = slug
    if lines:
        hm = H1.match(lines[0])
        if hm:
            title = hm.group(1).strip()

    parts: dict[str, list[str]] = {}
    current: str | None = None
    in_code = False
    for line in lines[1:]:
        if line.strip().startswith("```"):
            in_code = not in_code
        if not in_code:
            if line.startswith("## "):
                current = _slug_key(line[3:])
                parts.setdefault(current, [])
                continue
            bm = BOLD_LEAD.match(line)
            if bm and current not in ("results", "analysis", "limits", "reproduce"):
                current = _slug_key(bm.group(1))
                parts.setdefault(current, []).append(line[bm.end():])
                continue
        if current is not None:
            parts[current].append(line)
    text_parts = {k: "\n".join(v).strip() for k, v in parts.items()}
    if "results" in text_parts:
        text_parts["results"] = text_parts["results"].replace("[[RESULTS]]", results_md).strip()

    claim_full = text_parts.get("claim", "")
    if "Supports:" in claim_full:
        claim, supports_text = claim_full.split("Supports:", 1)
    else:
        claim, supports_text = claim_full, ""

    machine: dict[str, str] = {}
    for line in text_parts.get("machine", "").splitlines():
        mm = MACHINE.match(line.strip())
        if mm:
            machine[mm.group(1)] = mm.group(2).strip()

    description = ""
    first = bench_c.splitlines()[0] if bench_c else ""
    dm = re.match(r"^/\*\s*[\w-]+:\s*(.*?)\s*(?:\*/)?$", first)
    if dm:
        description = dm.group(1).strip()

    files = {
        "readme": f"{base}/README.md",
        "code": f"{base}/bench.c",
        "build": f"{base}/build.sh",
        "run": f"{base}/run.sh",
        "raw": f"{base}/results/raw.txt",
        "summary": f"{base}/results/summary.md",
    }
    return Benchmark(
        slug=slug,
        number=int(slug[:2]),
        title=title,
        description=description,
        claim=claim.strip(),
        supports_text=supports_text.strip(),
        supports=[],
        machine=machine,
        parts=text_parts,
        results_md=results_md,
        tables=parse_tables(results_md),
        raw_header=parse_raw_header(raw),
        files=files,
    )


def supported_titles(supports_text: str) -> list[str]:
    return [q.strip() for q in QUOTED.findall(supports_text)]
