"""Load the whole repository into memory and cross-link it."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urldefrag

from . import REPO_URL
from . import grammar as g
from .locate import CorpusReader, locate
from .parse_benchmarks import parse_benchmark, supported_titles
from .parse_readme import parse_readme
from .parse_record import parse_draft, parse_rules
from .schema import Benchmark, Claim, Draft, Entry, LinkNote, NoteChunk, Rejected, Section, Subsection

NOTE_DOCS = (
    "CONTRIBUTING.md",
    "misc/README.md",
    "misc/benchmarks/README.md",
    "misc/notes/conventions.md",
    "misc/notes/owner-brief.md",
    "misc/notes/benchmark-brief.md",
    "misc/notes/voice.md",
    "misc/notes/status.md",
    "misc/notes/banner/README.md",
    ".github/pull_request_template.md",
)
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


@dataclass(slots=True)
class CrawlTarget:
    """One linked source to fetch: a README URL without its fragment."""

    url: str
    entry_ids: list[str]
    sections: list[int]
    title: str


@dataclass
class Corpus:
    reader: CorpusReader
    sections: dict[int, Section]
    subsections: dict[str, Subsection]
    entries: dict[str, Entry]
    order: list[str]
    drafts: dict[int, Draft]
    rejected: list[Rejected]
    claims: list[Claim]
    link_notes: list[LinkNote]
    benchmarks: dict[str, Benchmark]
    notes: list[NoteChunk]
    seven_fields: list[str]
    admission: str
    intro: str
    rules: dict[int, str]
    badge_entries: int | None
    badge_benchmarks: int | None
    headings: list[tuple[int, int, str, str]]
    by_url: dict[str, list[str]] = field(default_factory=dict)
    by_url_nofrag: dict[str, list[str]] = field(default_factory=dict)
    record_by_url: dict[str, dict[str, list]] = field(default_factory=dict)
    related: dict[int, set[int]] = field(default_factory=dict)
    targets: list[CrawlTarget] = field(default_factory=list)
    allowed_urls: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    load_ms: float = 0.0

    # ----- lookups -------------------------------------------------------

    @property
    def source(self) -> str:
        return self.reader.source

    @property
    def commit(self) -> str | None:
        return self.reader.commit

    def entries_for_url(self, url: str) -> list[Entry]:
        ids = self.by_url.get(g.url_key(url)) or self.by_url_nofrag.get(g.url_key(url, keep_fragment=False)) or []
        return [self.entries[i] for i in ids]

    def record_for_url(self, url: str) -> dict[str, list]:
        empty = {"rejected": [], "claims": [], "link_notes": []}
        return self.record_by_url.get(g.url_key(url, keep_fragment=False), empty)

    def anchor_url(self, entry: Entry) -> str:
        if entry.subsection:
            anchor = self.subsections[entry.subsection].anchor
        else:
            anchor = self.sections[entry.section].anchor
        return f"{REPO_URL}#{anchor}"

    def file_url(self, path: str, line: int | None = None) -> str:
        suffix = f"#L{line}" if line else ""
        return f"{REPO_URL}/blob/main/{path}{suffix}"

    def location(self, entry: Entry) -> str:
        sec = self.sections[entry.section]
        if entry.subsection:
            return f"{sec.number}. {sec.title} / {self.subsections[entry.subsection].title}"
        return f"{sec.number}. {sec.title}"

    def benchmark_for_section(self, number: int) -> Benchmark | None:
        for slug in self.sections[number].benchmarks:
            return self.benchmarks.get(slug)
        return None

    def benchmarks_for_subsection(self, sub_id: str) -> list[Benchmark]:
        sub = self.subsections[sub_id]
        return [self.benchmarks[r.slug] for r in sub.reproduce if r.slug in self.benchmarks]

    def is_allowed_url(self, url: str) -> bool:
        return g.url_key(url, keep_fragment=False) in self.allowed_urls

    def stats(self) -> dict[str, int]:
        return {
            "sections": len(self.sections),
            "subsections": len(self.subsections),
            "entries": len(self.entries),
            "linked_entries": sum(1 for e in self.entries.values() if e.url),
            "unique_urls": len({g.url_key(e.url) for e in self.entries.values() if e.url}),
            "reproduce_lines": sum(len(s.reproduce) for s in self.sections.values())
            + sum(len(s.reproduce) for s in self.subsections.values()),
            "benchmarks": len(self.benchmarks),
            "rejected": len(self.rejected),
            "claims": len(self.claims),
            "link_notes": len(self.link_notes),
            "notes": len(self.notes),
            "files": len(self.reader.files),
            "crawl_targets": len(self.targets),
        }


def chunk_markdown(path: str, text: str) -> list[NoteChunk]:
    chunks: list[NoteChunk] = []
    heading, level, start = path, 0, 1
    buf: list[str] = []
    in_code = False

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            anchor = g.github_anchor(heading) if level else "top"
            chunks.append(
                NoteChunk(id=f"n:{path}#{anchor}", path=path, heading=heading, level=level, line=start, text=body)
            )

    for n, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else HEADING.match(line)
        if m:
            flush()
            heading, level, start, buf = m.group(2), len(m.group(1)), n, []
            continue
        buf.append(line)
    flush()
    return chunks


def load(reader: CorpusReader | None = None) -> Corpus:
    t0 = time.perf_counter()
    reader = reader or locate()
    readme = parse_readme(reader.read_text("README.md"))

    drafts: dict[int, Draft] = {}
    rejected: list[Rejected] = []
    claims: list[Claim] = []
    link_notes: list[LinkNote] = []
    for rel in reader.files:
        m = re.match(r"^misc/notes/sections/(\d{2})-[^/]+\.md$", rel)
        if not m:
            continue
        number = int(m.group(1))
        draft, rej, cl, ln = parse_draft(rel, reader.read_text(rel), number)
        drafts[number] = draft
        rejected += rej
        claims += cl
        link_notes += ln

    benchmarks: dict[str, Benchmark] = {}
    for rel in reader.files:
        m = re.match(r"^misc/benchmarks/(\d{2}-[a-z0-9-]+)/README\.md$", rel)
        if not m:
            continue
        slug = m.group(1)
        base = f"misc/benchmarks/{slug}"

        def opt(path: str) -> str:
            return reader.read_text(path) if reader.has(path) else ""

        benchmarks[slug] = parse_benchmark(
            slug, reader.read_text(rel), opt(f"{base}/results/raw.txt"), opt(f"{base}/bench.c"), base
        )

    notes: list[NoteChunk] = []
    for rel in NOTE_DOCS + tuple(f for f in reader.files if f.startswith(".github/ISSUE_TEMPLATE/")):
        if reader.has(rel):
            notes += chunk_markdown(rel, reader.read_text(rel))
    if readme.intro:
        notes.append(NoteChunk(id="n:README.md#intro", path="README.md", heading="Scope, evidence and proof", level=2, line=7, text=readme.intro))
    if readme.admission:
        notes.append(
            NoteChunk(id="n:README.md#what-earns-a-place", path="README.md", heading="What earns a place", level=2, line=690, text=readme.admission)
        )

    rules = parse_rules(reader.read_text("misc/notes/owner-brief.md")) if reader.has("misc/notes/owner-brief.md") else {}

    corpus = Corpus(
        reader=reader,
        sections=readme.sections,
        subsections=readme.subsections,
        entries=readme.entries,
        order=readme.order,
        drafts=drafts,
        rejected=rejected,
        claims=claims,
        link_notes=link_notes,
        benchmarks=benchmarks,
        notes=notes,
        seven_fields=readme.seven_fields,
        admission=readme.admission,
        intro=readme.intro,
        rules=rules,
        badge_entries=readme.badge_entries,
        badge_benchmarks=readme.badge_benchmarks,
        headings=readme.headings,
    )
    _cross_link(corpus)
    corpus.load_ms = (time.perf_counter() - t0) * 1000
    return corpus


def _cross_link(c: Corpus) -> None:
    for eid in c.order:
        e = c.entries[eid]
        if not e.url:
            continue
        c.by_url.setdefault(g.url_key(e.url), []).append(eid)
        c.by_url_nofrag.setdefault(g.url_key(e.url, keep_fragment=False), []).append(eid)

    for number, draft in c.drafts.items():
        if number in c.sections:
            c.sections[number].draft = draft.path
            c.sections[number].owner = draft.owner

    def add_record(kind: str, url: str, item) -> None:
        bucket = c.record_by_url.setdefault(
            g.url_key(url, keep_fragment=False), {"rejected": [], "claims": [], "link_notes": []}
        )
        if item not in bucket[kind]:
            bucket[kind].append(item)

    for r in c.rejected:
        for u in r.urls:
            add_record("rejected", u, r)
    for cl in c.claims:
        for u in cl.urls:
            add_record("claims", u, cl)
    for ln in c.link_notes:
        for u in ln.urls:
            add_record("link_notes", u, ln)

    # Benchmarks: which README lines reproduce them, and which entries they support.
    reproduce = [r for s in c.sections.values() for r in s.reproduce] + [
        r for s in c.subsections.values() for r in s.reproduce
    ]
    for r in reproduce:
        b = c.benchmarks.get(r.slug)
        if b is None:
            c.warnings.append(f"README line {r.line}: Reproduce it names missing benchmark {r.slug}")
            continue
        b.reproduced_from.append((r.section, r.subsection))
        if r.slug not in c.sections[r.section].benchmarks:
            c.sections[r.section].benchmarks.append(r.slug)
    for b in c.benchmarks.values():
        b.reproduced_from.sort(key=lambda x: (x[0], x[1] or ""))
        ids: list[str] = []
        for title in supported_titles(b.supports_text):
            low = title.lower()
            matches = [e for e in c.entries.values() if e.title.lower() == low]
            same = [e for e in matches if e.section == b.number]
            for e in same or matches[:1]:
                if e.id not in ids:
                    ids.append(e.id)
        b.supports = ids

    # Related sections, derived only from the repository.
    related: dict[int, set[int]] = defaultdict(set)
    for ids in c.by_url_nofrag.values():
        secs = {c.entries[i].section for i in ids}
        for a in secs:
            related[a] |= secs - {a}
    titles = {n: s.title.lower() for n, s in c.sections.items()}
    for n, s in c.sections.items():
        pre = s.preamble.lower()
        for m, t in titles.items():
            if m != n and f"{t} section" in pre:
                related[n].add(m)
    for r in c.rejected:
        for target in r.listed_in + ([r.left_to] if r.left_to else []):
            if target not in c.sections or target == r.section:
                continue
            if any(e.section == target for u in r.urls for e in c.entries_for_url(u)):
                related[r.section].add(target)
                related[target].add(r.section)
    c.related = {k: set(v) for k, v in related.items()}

    # Crawl targets: README URLs without fragments, each with every entry that links it.
    targets: dict[str, CrawlTarget] = {}
    for eid in c.order:
        e = c.entries[eid]
        if not e.url:
            continue
        base, _ = urldefrag(e.url)
        t = targets.get(base)
        if t is None:
            targets[base] = CrawlTarget(url=base, entry_ids=[eid], sections=[e.section], title=e.title)
        else:
            t.entry_ids.append(eid)
            if e.section not in t.sections:
                t.sections.append(e.section)
    for comp in (cp for s in c.sections.values() for cp in s.companions):
        base, _ = urldefrag(comp.url)
        targets.setdefault(base, CrawlTarget(url=base, entry_ids=[], sections=[comp.section], title=comp.title))
    c.targets = list(targets.values())

    # Every URL written anywhere in the corpus may be read on demand.
    allowed: set[str] = set()
    for rel in c.reader.files:
        if rel.endswith((".md", ".txt", ".c", ".h", ".sh", ".py")):
            for u in g.find_urls(c.reader.read_text(rel)):
                allowed.add(g.url_key(u, keep_fragment=False))
    c.allowed_urls = allowed

    if c.badge_entries is not None:
        linked = sum(1 for e in c.entries.values() if e.url)
        if linked != c.badge_entries:
            c.warnings.append(f"README badge says {c.badge_entries} entries; parsed {linked} linked entries")
