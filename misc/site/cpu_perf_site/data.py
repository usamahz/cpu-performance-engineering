"""The site's view of the repository, built from build/export.json alone.

Nothing here parses the README: sections, entries, benchmarks and the
editorial record arrive already parsed by cpu_perf. This module adds only
what a page needs to show them: URLs, stable keys, evidence badges, rendered
markdown and cross-links.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .config import Config
from .markdown import Markdown
from .paths import Links, slugify

# --------------------------------------------------------------------------
# Evidence badges: a labelled heuristic from each link's host and path, as
# the prototype's design had them. The README's wording stays authoritative.

KINDS = ("paper", "manual", "repository", "report", "talk", "book", "unlinked")
TALK_HOSTS = {"youtube.com", "youtu.be", "vimeo.com"}
BOOK_HOSTS = {"shop.elsevier.com", "informit.com"}
REPO_HOSTS = {"github.com", "gitlab.com", "git.kernel.org", "sourceforge.net", "bitbucket.org", "godbolt.org"}
MANUAL_HOSTS = {
    "intel.com", "support.arm.com", "developer.arm.com", "docs.amd.com", "docs.kernel.org", "kernel.org",
    "man7.org", "gcc.gnu.org", "clang.llvm.org", "llvm.org", "docs.nvidia.com", "spec.org", "docs.riscv.org",
    "computeexpresslink.org", "jedec.org", "uxlfoundation.github.io", "docs.openvino.ai", "onnxruntime.ai",
    "doc.dpdk.org", "arm-software.github.io", "itanium-cxx-abi.github.io", "eel.is", "openmp.org",
    "google.github.io", "perfwiki.github.io", "amperecomputing.com", "agner.org", "lmax-exchange.github.io",
}
PAPER_HOSTS = {
    "arxiv.org", "dl.acm.org", "ieeexplore.ieee.org", "usenix.org", "cacm.acm.org", "queue.acm.org", "jilp.org",
    "nature.com", "sigops.org", "projecteuclid.org", "cambridge.org", "pubsonline.informs.org",
    "inria.hal.science", "kar.kent.ac.uk", "real.mtak.hu", "research.google", "static.googleusercontent.com",
    "open-std.org", "sites.google.com",
}
PAPER_PATH = re.compile(r"/(papers?|pubs|publications?|doi)/|\.pdf$|\.ps\.gz$", re.I)

# The seven fields in the README's order, against the labels each benchmark
# README's Machine block uses for them (cpu_perf.parse_benchmarks.MACHINE_KEYS).
MACHINE_KEYS = ("CPU model and microarchitecture", "Cores used", "Frequency", "Compiler and flags",
                "Workload", "Baseline", "Method")
LEAD = re.compile(r"^\*\*(?P<lead>[^*]+?)\.\*\*\s+(?P<rest>.*)$", re.S)
LABEL_ONLY = re.compile(r"^\*\*(?P<label>[^*]+)\*\*$")


def kind_of(url: str | None) -> str:
    if not url:
        return "unlinked"
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.lower()
    if host in TALK_HOSTS:
        return "talk"
    if host in BOOK_HOSTS or "book" in path:
        return "book"
    if host in REPO_HOSTS:
        return "repository"
    if host in MANUAL_HOSTS:
        return "manual"
    if host in PAPER_HOSTS or PAPER_PATH.search(path):
        return "paper"
    return "report"


def stable_key(text: str) -> str:
    """Ten base32 characters of SHA-256: the same source keeps the same key
    however the README is renumbered or reordered."""
    return base64.b32encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii").lower()[:10]


def pad(n: int) -> str:
    return f"{n:02d}"


def split_blocks(text: str) -> list[str]:
    """Markdown into paragraphs and fenced code blocks."""
    blocks, buf, fence = [], [], False
    for line in text.splitlines():
        if line.startswith("```"):
            if not fence and buf:
                blocks.append("\n".join(buf))
                buf = []
            buf.append(line)
            if fence:
                blocks.append("\n".join(buf))
                buf = []
            fence = not fence
            continue
        if not fence and not line.strip():
            if buf:
                blocks.append("\n".join(buf))
                buf = []
            continue
        buf.append(line)
    if buf:
        blocks.append("\n".join(buf))
    return blocks


def fence_body(block: str) -> str:
    lines = block.splitlines()
    return "\n".join(lines[1:-1]) if len(lines) >= 2 else ""


# --------------------------------------------------------------------------
# Records


@dataclass
class Entry:
    id: str
    kind: str
    section: int
    subsection: str | None
    position: int
    title: str
    url: str | None
    reason: str
    line: int
    host: str
    condition: str | None = None
    condition_kw: str | None = None
    reason_html: str = ""
    key: str = ""
    anchor: str = ""
    progress_key: str = ""
    badge: str = "report"
    readme_line: str = ""
    page: str = ""
    also_in: list = field(default_factory=list)  # Entry objects elsewhere with the same URL

    @property
    def number(self) -> str:
        return pad(self.position)


@dataclass
class Reproduce:
    slug: str
    description: str
    description_html: str
    line: int
    section: int
    subsection: str | None
    benchmark: object = None


@dataclass
class Companion:
    title: str
    url: str
    text: str
    html: str
    line: int


@dataclass
class Subsection:
    id: str
    section: int
    position: int
    title: str
    anchor: str
    line: int
    entries: list[Entry]
    reproduce: list[Reproduce]


@dataclass
class Group:
    id: str
    name: str
    blurb: str
    numbers: list[int]
    sections: list = field(default_factory=list)

    @property
    def range_label(self) -> str:
        lo, hi = min(self.numbers), max(self.numbers)
        return f"§{lo}" if lo == hi else f"§{lo}–{hi}"


@dataclass
class Section:
    number: int
    title: str
    heading: str
    anchor: str
    line: int
    end_line: int
    kind: str
    preamble: str
    preamble_html: str
    slug: str
    url: str
    twin: str
    mcp_resource: str
    subsections: list[Subsection]
    entries: list[Entry]  # entries directly under the H2 (Start here)
    all_entries: list[Entry]
    reproduce: list[Reproduce]  # Reproduce lines directly under the H2
    companions: list[Companion]
    benchmark_slugs: list[str]
    related_numbers: list[int]
    watch_checked: str | None
    draft: str | None
    group: Group | None = None
    related: list = field(default_factory=list)
    benchmarks: list = field(default_factory=list)
    prev: object = None
    next: object = None

    @property
    def number_label(self) -> str:
        return pad(self.number)

    @property
    def entry_count(self) -> int:
        return len(self.all_entries)

    @property
    def linked_count(self) -> int:
        return sum(1 for e in self.all_entries if e.url)

    def stream(self) -> list[tuple[str, object]]:
        """What the README puts under this H2, in README order: the entries
        written directly under it, its H3 subsections, its companion lines and
        its Reproduce lines."""
        items: list[tuple[int, str, object]] = []
        if self.entries:
            items.append((self.entries[0].line, "entries", self.entries))
        items += [(s.line, "subsection", s) for s in self.subsections]
        items += [(c.line, "companion", c) for c in self.companions]
        items += [(r.line, "reproduce", r) for r in self.reproduce]
        return [(kind, obj) for _, kind, obj in sorted(items, key=lambda t: t[0])]


@dataclass
class Benchmark:
    slug: str
    number: int
    title: str
    description: str
    claim: str
    claim_html: str
    supports_text: str
    supports: list[Entry]
    machine: dict
    passport: list[tuple[str, str]]
    passport_filled: int
    parts: dict
    parts_html: dict
    extras: list[tuple[str, str]]
    extras_after: dict
    results_html: str
    tables: list[dict]
    raw_header: dict
    raw_header_text: str
    files: dict
    file_urls: dict
    index_claim: str
    threads: str
    neon: bool
    cflags: str
    results: list[dict]
    raw: str
    url: str
    twin: str
    mcp_resource: str
    readme: str
    section: Section | None = None
    charts: list = field(default_factory=list)
    prev: object = None
    next: object = None

    @property
    def section_label(self) -> str:
        return pad(self.number)


@dataclass
class RecordItem:
    kind: str  # rejected | claim | link_note
    id: str
    section: int
    line: int
    source: str
    title: str
    urls: list[str]
    html: str
    category: str = ""
    rules: list[int] = field(default_factory=list)
    verdict: str = ""
    verdict_text: str = ""
    missing_fields: list[int] = field(default_factory=list)
    listed_in: list = field(default_factory=list)  # Section objects
    left_to: object = None
    quote: str = ""
    source_url: str = ""


# --------------------------------------------------------------------------


class Site:
    """Everything the templates read, built once per build."""

    def __init__(self, export: dict, config: Config, surface: dict | None = None):
        self.config = config
        self.copy = config.copy
        self.export = export
        self.source = export["source"]
        self.generator = export["generator"]
        self.counts = export["counts"]
        self.files: dict[str, str] = export["files"]
        self.lastmod: dict[str, str] = export.get("lastmod", {})
        self.commit = self.source["commit"]
        self.commit_short = self.commit[:7]
        self.committed_date = (self.source.get("committed_at") or "")[:10]
        self.repo_url = config.repo
        self.base_url = config.base_url
        self.surface = surface
        corpus = export["corpus"]
        self.corpus = corpus
        self.seven_fields = [f[:1].upper() + f[1:] for f in corpus["seven_fields"]]

        self.title_anchor = next((h[3] for h in corpus["headings"] if h[1] == 1), "")
        anchors = self._readme_anchors(corpus)
        self.anchors = anchors
        from .mcp import ANCHOR_PAGES

        self.links = Links(self.repo_url, self.commit, anchors, ANCHOR_PAGES)
        self.md = Markdown(self.links)
        readme_lines = self.files.get("README.md", "").splitlines()

        # ---- entries
        group_of: dict[str, str] = {}
        for ukey, ids in corpus.get("by_url", {}).items():
            for eid in ids:
                group_of[eid] = ukey
        self.entries: dict[str, Entry] = {}
        for eid in corpus["order"]:
            raw = corpus["entries"][eid]
            e = Entry(**{k: raw.get(k) for k in (
                "id", "kind", "section", "subsection", "position", "title", "url", "reason", "line", "host",
                "condition", "condition_kw")})
            e.reason_html = self.md.inline(e.reason, "README.md")
            e.key = stable_key(e.url.rstrip("/")) if e.url else "t" + stable_key(e.reason)[:9]
            e.badge = kind_of(e.url)
            e.readme_line = readme_lines[e.line - 1] if 0 < e.line <= len(readme_lines) else ""
            self.entries[eid] = e
        by_group: dict[str, list[Entry]] = {}
        for eid, e in self.entries.items():
            if eid in group_of:
                by_group.setdefault(group_of[eid], []).append(e)
        for members in by_group.values():
            for e in members:
                e.also_in = [o for o in members if o is not e and o.section != e.section]

        # ---- sections
        h2_lines = sorted(h[0] for h in corpus["headings"] if h[1] == 2)
        self.sections: list[Section] = []
        for num_s, raw in sorted(corpus["sections"].items(), key=lambda kv: int(kv[0])):
            n = int(num_s)
            slug = slugify(raw["title"])
            url = "/watchlist/" if raw["kind"] == "watchlist" else f"/learn/{slug}/"
            twin = "/watchlist.md" if raw["kind"] == "watchlist" else f"/learn/{slug}.md"
            end = next((ln for ln in h2_lines if ln > raw["line"]), len(readme_lines) + 1) - 1
            subs = []
            for sid in raw["subsection_ids"]:
                s = corpus["subsections"][sid]
                subs.append(Subsection(
                    id=sid, section=n, position=s["position"], title=s["title"], anchor=s["anchor"], line=s["line"],
                    entries=[self.entries[i] for i in s["entry_ids"]],
                    reproduce=[self._reproduce(r) for r in s["reproduce"]],
                ))
            direct_ids = set(raw["entry_ids"]) - {i for s in raw["subsection_ids"] for i in corpus["subsections"][s]["entry_ids"]}
            direct = [self.entries[i] for i in raw["entry_ids"] if i in direct_ids]
            all_entries = [self.entries[i] for i in raw["entry_ids"]]
            sec = Section(
                number=n, title=raw["title"], heading=raw["heading"], anchor=raw["anchor"], line=raw["line"],
                end_line=end, kind=raw["kind"], preamble=raw["preamble"],
                preamble_html=self.md.inline(raw["preamble"], "README.md"),
                slug=slug, url=url, twin=twin, mcp_resource=f"cpuperf://section/{n}",
                subsections=subs, entries=direct, all_entries=all_entries,
                reproduce=[self._reproduce(r) for r in raw["reproduce"]],
                companions=[Companion(c["title"], c["url"], c["text"], self.md.inline(c["text"], "README.md"), c["line"])
                            for c in raw["companions"]],
                benchmark_slugs=list(raw["benchmarks"]),
                related_numbers=sorted(int(x) for x in corpus.get("related", {}).get(num_s, [])),
                watch_checked=raw.get("watch_checked"), draft=raw.get("draft"),
            )
            self.sections.append(sec)
            for e in all_entries:
                anchors_on_page = [x.key for x in all_entries]
                dup = anchors_on_page.count(e.key) > 1
                e.anchor = f"e-{e.key}" + (f"-{e.id.replace('.', '-')}" if dup else "")
                e.page = f"{url}#{e.anchor}"
                e.progress_key = f"{e.key}@{slug}"
        self.section_by_number = {s.number: s for s in self.sections}
        for i, s in enumerate(self.sections):
            s.prev = self.sections[i - 1] if i else None
            s.next = self.sections[i + 1] if i + 1 < len(self.sections) else None
            s.related = [self.section_by_number[r] for r in s.related_numbers if r in self.section_by_number]

        # ---- groups
        self.groups: list[Group] = []
        for g in config.groups:
            names = self.copy.groups[g["id"]]
            grp = Group(id=g["id"], name=names["name"], blurb=names["blurb"], numbers=list(g["sections"]))
            grp.sections = [self.section_by_number[n] for n in grp.numbers if n in self.section_by_number]
            for s in grp.sections:
                s.group = grp
            self.groups.append(grp)

        # ---- benchmarks
        extra = export.get("benchmarks_extra", {})
        self.benchmarks: list[Benchmark] = []
        for slug, raw in sorted(corpus["benchmarks"].items()):
            self.benchmarks.append(self._benchmark(slug, raw, extra.get(slug, {})))
        self.bench_by_slug = {b.slug: b for b in self.benchmarks}
        for i, b in enumerate(self.benchmarks):
            b.prev = self.benchmarks[i - 1] if i else None
            b.next = self.benchmarks[i + 1] if i + 1 < len(self.benchmarks) else None
            b.section = self.section_by_number.get(b.number)
        for s in self.sections:
            s.benchmarks = [self.bench_by_slug[x] for x in s.benchmark_slugs if x in self.bench_by_slug]
            for r in s.reproduce + [r for sub in s.subsections for r in sub.reproduce]:
                r.benchmark = self.bench_by_slug.get(r.slug)

        self.bench_readme = self._bench_readme()

        # ---- the README's own framing
        self.intro = self._intro(readme_lines, corpus)
        self.admission_html = self.md.render(corpus["admission"], "README.md", demote=1)
        self.evidence = self._evidence(corpus)
        self.license_text = self._license(readme_lines, corpus)

        # ---- editorial record
        self.rejected = [self._record("rejected", r) for r in corpus["rejected"]]
        self.claims = [self._record("claim", r) for r in corpus["claims"]]
        self.link_notes = [self._record("link_note", r) for r in corpus["link_notes"]]

    # ----------------------------------------------------------------------

    def _readme_anchors(self, corpus: dict) -> dict[str, str]:
        """Every README heading's fragment, mapped to the page that carries it."""
        pages: dict[str, str] = {}
        for _, level, text, anchor in corpus["headings"]:
            if level == 1:
                pages[anchor] = "/"
        pages["contents"] = "/learn/#contents"
        pages["what-earns-a-place"] = "/evidence/#what-earns-a-place"
        pages["license"] = "/evidence/#license"
        for num_s, s in corpus["sections"].items():
            base = "/watchlist/" if s["kind"] == "watchlist" else f"/learn/{slugify(s['title'])}/"
            pages[s["anchor"]] = f"{base}#{s['anchor']}"
            for sid in s["subsection_ids"]:
                a = corpus["subsections"][sid]["anchor"]
                pages[a] = f"{base}#{a}"
        return pages

    def _reproduce(self, r: dict) -> Reproduce:
        return Reproduce(slug=r["slug"], description=r["description"],
                         description_html=self.md.inline(r["description"], "README.md"),
                         line=r["line"], section=r["section"], subsection=r.get("subsection"))

    def _intro(self, readme_lines: list[str], corpus: dict) -> dict:
        """The README's opening, between its badges and its Contents, as the
        home page lays it out: the lede, the bold-led notes, the commands that
        add the MCP server, and the closing sentence."""
        contents_line = next((h[0] for h in corpus["headings"] if h[3] == "contents"), len(readme_lines))
        start = 1
        for i, line in enumerate(readme_lines[: contents_line - 1], 1):
            if line.startswith("[![") or line.startswith("!["):
                start = i + 1
        blocks = split_blocks("\n".join(readme_lines[start - 1: contents_line - 1]))
        lede, leads, commands, after, closing = "", [], [], [], ""
        label = None
        for i, block in enumerate(blocks):
            m = LEAD.match(block)
            lab = LABEL_ONLY.match(block.strip())
            if not lede and not m:
                lede = block
            elif m:
                leads.append({"lead": m.group("lead"), "html": self.md.inline(" ".join(m.group("rest").split()), "README.md")})
            elif lab:
                label = lab.group("label")
            elif block.startswith("```"):
                commands.append({"label": label or "", "code": fence_body(block)})
                label = None
            elif i == len(blocks) - 1:
                closing = block
            else:
                after.append(self.md.inline(" ".join(block.split()), "README.md"))
        return {
            "lede": " ".join(lede.split()),
            "lede_html": self.md.inline(" ".join(lede.split()), "README.md"),
            "leads": leads,
            "commands": commands,
            "after_commands": after,
            "closing_html": self.md.inline(" ".join(closing.split()), "README.md"),
        }

    def _evidence(self, corpus: dict) -> dict:
        """The README's "What earns a place" in the order /evidence/ shows it:
        its opening line, the paragraph after the seven fields, the rest; and
        CONTRIBUTING.md without its title, under the page's own heading."""
        blocks = split_blocks(corpus["admission"])
        lead, after, rest = (blocks + ["", ""])[0], (blocks + ["", ""])[1], blocks[2:]
        contributing = self.files.get("CONTRIBUTING.md", "").splitlines()
        if contributing and contributing[0].startswith("# "):
            contributing = contributing[1:]
        return {
            "lead": " ".join(lead.split()),
            "after_html": self.md.render(after, "README.md"),
            "rest_html": [self.md.render(b, "README.md") for b in rest],
            "contributing_html": self.md.render("\n".join(contributing).strip(), "CONTRIBUTING.md", demote=1),
        }

    def _license(self, readme_lines: list[str], corpus: dict) -> str:
        line = next((h[0] for h in corpus["headings"] if h[3] == "license"), None)
        if not line:
            return ""
        body = []
        for text in readme_lines[line:]:
            if text.startswith("## "):
                break
            body.append(text)
        return self.md.render("\n".join(body).strip(), "README.md")

    def _bench_readme(self) -> dict:
        """misc/benchmarks/README.md as /benchmarks/ shows it: the opening
        paragraph, then each H2 section under the README's own anchor. The
        directory table is drawn from the corpus instead, as the lab table."""
        from .mcp import split_sections

        source = "misc/benchmarks/README.md"
        intro, sections = split_sections(self.files.get(source, ""))
        lede = next((b for b in split_blocks(intro) if not b.lstrip().startswith("|")), "")
        return {
            "source": source,
            "lede": " ".join(lede.split()),
            "lede_html": self.md.inline(" ".join(lede.split()), source),
            "sections": [{"title": sec.title, "anchor": sec.anchor,
                          "html": self.md.render(sec.body, source, demote=1, id_prefix=f"{sec.anchor}-")}
                         for sec in sections],
        }

    def _benchmark(self, slug: str, raw: dict, extra: dict) -> Benchmark:
        base = raw["files"]["readme"].rsplit("/", 1)[0]
        source = raw["files"]["readme"]
        parts = raw["parts"]
        parts_html = {k: self.md.render(v, source, demote=1, id_prefix=f"{k}-") for k, v in parts.items()}
        known = {"claim", "method", "generated_code", "machine", "results", "analysis", "limits", "reproduce"}
        extras = [(k.replace("_", " ").capitalize(), parts_html[k]) for k in parts if k not in known]
        # A part the site has no block for (a second claim, a vendor figure,
        # vectoriser remarks) goes in the block it follows in the README.
        readme_text = self.files.get(source, "")

        def position(key: str) -> int:
            i = readme_text.find(parts[key].strip()[:80])
            return i if i >= 0 else len(readme_text)

        extras_after: dict[str, list[tuple[str, str]]] = {}
        last = "claim"
        for key in sorted(parts, key=position):
            if key in known:
                last = "claim" if key == "machine" else key
            else:
                extras_after.setdefault(last, []).append((key.replace("_", " ").capitalize(), parts_html[key]))
        machine = raw["machine"]
        passport = []
        for label, key in zip(self.seven_fields, MACHINE_KEYS):
            value = machine.get(key, "")
            passport.append((label, self.md.inline(value, source) if value else ""))
        header = raw.get("raw_header", {})
        raw_text = extra.get("raw", "")
        header_lines = []
        for line in raw_text.splitlines():
            if line.strip() == "---" or line.startswith("RESULT ") or (not line.strip() and header_lines):
                break
            header_lines.append(line)
        return Benchmark(
            slug=slug, number=raw["number"], title=raw["title"], description=raw["description"],
            claim=raw["claim"], claim_html=self.md.render(raw["claim"], source),
            supports_text=raw["supports_text"],
            supports=[self.entries[i] for i in raw["supports"] if i in self.entries],
            machine=machine, passport=passport, passport_filled=sum(1 for _, v in passport if v),
            parts=parts, parts_html=parts_html, extras=extras, extras_after=extras_after,
            results_html=self.md.render(raw["results_md"], source, demote=1, id_prefix="results-"),
            tables=raw["tables"], raw_header=header, raw_header_text="\n".join(header_lines).strip(),
            files=raw["files"], file_urls={k: self.links.blob(v) for k, v in raw["files"].items()},
            index_claim=extra.get("index_claim", ""), threads=extra.get("threads", ""),
            neon=bool(extra.get("neon")), cflags=extra.get("cflags", ""),
            results=extra.get("results", []), raw=raw_text,
            url=f"/benchmarks/{slug}/", twin=f"/benchmarks/{slug}.md", mcp_resource=f"cpuperf://benchmark/{slug}",
            readme=self.files.get(source, ""),
        )

    def _record(self, kind: str, r: dict) -> RecordItem:
        src = r["source"]
        if kind == "rejected":
            text = r["reason"]
            title = r["title"]
        elif kind == "claim":
            text = r["text"]
            title = r.get("quote") or ""
        else:
            text = r["text"]
            title = ""
        item = RecordItem(
            kind=kind, id=r["id"], section=r["section"], line=r["line"], source=src, title=title,
            urls=list(r.get("urls") or []), html=self.md.inline(" ".join(text.split()), src),
            category=r.get("category", ""), rules=list(r.get("rules") or []),
            verdict=(r.get("verdict") or "") if kind == "claim" else "",
            verdict_text=r.get("verdict_text") or "",
            missing_fields=list(r.get("missing_fields") or []),
            quote=r.get("quote") or "",
            # 12 hex digits of the commit: unambiguous, and 700 rows shorter.
            source_url=self.links.blob(src, r["line"]).replace(self.commit, self.commit[:12]),
        )
        item.listed_in = [self.section_by_number[n] for n in (r.get("listed_in") or []) if n in self.section_by_number]
        if r.get("left_to") in self.section_by_number:
            item.left_to = self.section_by_number[r["left_to"]]
        return item

    def resolve_ref(self, ref: str) -> dict | None:
        """A document id from the server's search tool (benchmark:09-false-sharing,
        section:9.4, entry:9.4.1, record:r9.14) as a page on this site."""
        kind, _, key = ref.partition(":")
        if kind == "benchmark" and key in self.bench_by_slug:
            b = self.bench_by_slug[key]
            return {"kind": "benchmark", "label": b.title, "url": b.url, "tag": b.slug}
        if kind == "entry" and key in self.entries:
            e = self.entries[key]
            return {"kind": "source", "label": e.title, "url": e.page, "tag": f"§{e.section}"}
        if kind == "section":
            num, _, _ = key.partition(".")
            sec = self.section_by_number.get(int(num)) if num.isdigit() else None
            if sec is None:
                return None
            sub = next((x for x in sec.subsections if x.id == key), None)
            if sub:
                return {"kind": "part", "label": sub.title, "url": f"{sec.url}#{sub.anchor}", "tag": f"§{sec.number}"}
            return {"kind": "section", "label": sec.title, "url": sec.url, "tag": f"§{sec.number}"}
        if kind == "record":
            for items, page in ((self.rejected, "/evidence/record/"), (self.claims, "/evidence/record/"),
                                (self.link_notes, "/evidence/record/link-notes/")):
                item = next((r for r in items if r.id == key), None)
                if item:
                    return {"kind": "record", "label": item.title or item.id, "url": f"{page}#{item.id}", "tag": item.id}
        return None

    # ----------------------------------------------------------------------

    @property
    def chapters(self) -> list[Section]:
        return [s for s in self.sections if s.kind != "watchlist"]

    @property
    def watchlist(self) -> Section | None:
        return next((s for s in self.sections if s.kind == "watchlist"), None)

    def absolute(self, path: str) -> str:
        return self.base_url + path

    def readme_slice(self, start: int, end: int) -> str:
        lines = self.files.get("README.md", "").splitlines()[start - 1: end]
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines) + "\n"


def load_site(build_dir: Path, config: Config) -> Site:
    export = json.loads((build_dir / "export.json").read_text(encoding="utf-8"))
    surface_path = build_dir / "mcp-surface.json"
    surface = json.loads(surface_path.read_text(encoding="utf-8")) if surface_path.is_file() else None
    site = Site(export, config, surface)
    site.build_dir = build_dir
    return site
