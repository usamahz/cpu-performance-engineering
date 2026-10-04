"""python -m cpu_perf_site check: the built site against the repository.

Each check reads dist/ as a browser or crawler would and compares it with
the corpus the build used and with an independent count of the README, so
a template that drops an entry, a heading that loses its anchor, a link to
a page that does not exist or a chart that loses a value fails the build
with a message saying where. tests/test_check.py seeds each defect into a
copy of a built site and asserts the check catches it.
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from markdown_it import MarkdownIt

CSP = "default-src 'self'"
LOCAL_SCHEMES = ("", "mailto")


@dataclass
class PageInfo:
    path: str
    ids: set = field(default_factory=set)
    hrefs: list = field(default_factory=list)  # (tag, attr value, rel)
    sources: list = field(default_factory=list)  # src of script, img; href of stylesheet/icon/preload
    entries: list = field(default_factory=list)  # data-entry ids, in page order
    styles: int = 0  # style attributes
    csp: str = ""
    twin: str = ""
    canonical: str = ""
    html: str = ""


class Collector(HTMLParser):
    def __init__(self, info: PageInfo):
        super().__init__(convert_charrefs=True)
        self.info = info

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        i = self.info
        if "id" in a:
            i.ids.add(a["id"])
        if "style" in a:
            i.styles += 1
        if "data-entry" in a:
            i.entries.append(a["data-entry"])
        if tag == "a" and "href" in a:
            i.hrefs.append(("a", a["href"], a.get("rel") or ""))
        if tag in ("script", "img", "iframe", "source", "video", "audio") and a.get("src"):
            i.sources.append(a["src"])
        if tag == "link":
            rel = (a.get("rel") or "").split()
            if {"stylesheet", "icon", "preload", "modulepreload"} & set(rel):
                i.sources.append(a.get("href", ""))
            if "alternate" in rel and a.get("type") == "text/markdown":
                i.twin = a.get("href", "")
            if "canonical" in rel:
                i.canonical = a.get("href", "")
        if tag == "meta" and (a.get("http-equiv") or "").lower() == "content-security-policy":
            i.csp = a.get("content", "")


def parse(dist: Path, file: Path) -> PageInfo:
    rel = file.relative_to(dist).as_posix()
    path = "/" + (rel[: -len("index.html")] if rel.endswith("index.html") else rel)
    info = PageInfo(path)
    info.html = file.read_text(encoding="utf-8")
    Collector(info).feed(info.html)
    return info


def target(dist: Path, href_path: str) -> Path | None:
    """The file a site-relative path serves, as GitHub Pages resolves it."""
    p = unquote(href_path)
    f = dist / p.lstrip("/")
    if p.endswith("/"):
        f = f / "index.html"
    if f.is_file():
        return f
    if (f / "index.html").is_file():
        return f / "index.html"
    return None


# --------------------------------------------------------------------------
# An independent count of the README: a markdown-it token walk that shares no
# code with cpu_perf's grammar, so a parser bug cannot hide in both.


def recount(readme: str) -> dict:
    tokens = MarkdownIt("commonmark").parse(readme)
    counts = {"sections": 0, "subsections": 0, "entries": 0, "unlinked": 0, "reproduce_lines": 0}
    in_section = False
    depth = 0
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            text = tokens[i + 1].content
            if tok.tag == "h2":
                in_section = bool(re.match(r"\d+\. ", text))
                counts["sections"] += in_section
            elif tok.tag == "h3" and in_section:
                counts["subsections"] += 1
        elif not in_section:
            continue
        elif tok.type in ("bullet_list_open", "ordered_list_open"):  # Start here is numbered
            depth += 1
        elif tok.type in ("bullet_list_close", "ordered_list_close"):
            depth -= 1
        elif tok.type == "inline" and tokens[i - 1].type == "paragraph_open":
            in_item = i >= 2 and tokens[i - 2].type == "list_item_open"
            children = tok.children or []
            if in_item and depth == 1:
                first = children[0] if children else None
                if first is not None and first.type == "link_open" and urlsplit(first.attrGet("href") or "").scheme:
                    counts["entries"] += 1
                else:
                    counts["unlinked"] += 1
            elif not in_item and tok.content.startswith("Reproduce it:"):
                counts["reproduce_lines"] += 1
    return counts


def markdown_tables(text: str) -> list[list[str]]:
    """Every pipe table in a Markdown text, as its list of rows."""
    tables, cur = [], []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            cur.append(" ".join(line.split()))
        elif cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    return tables


# --------------------------------------------------------------------------


class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.passed: list[str] = []

    def check(self, name: str, problems: list[str], warn: bool = False) -> None:
        if problems:
            bucket = self.warnings if warn else self.errors
            bucket += [f"{name}: {p}" for p in problems[:25]]
            if len(problems) > 25:
                bucket.append(f"{name}: ... and {len(problems) - 25} more")
        else:
            self.passed.append(name)


def run_checks(site, dist: Path, strict: bool = False, quiet: bool = False) -> int:
    from .pages import Builder

    Builder(site, dist)  # the same derived views the build used (MCP surface, charts)
    report = Report()
    files = sorted(dist.rglob("*.html"))
    pages = {p.path: p for p in (parse(dist, f) for f in files)}
    cfg = site.config
    counts = site.counts

    # 1. entry parity, page by page
    problems = []
    for sec in site.sections:
        page = pages.get(sec.url)
        if page is None:
            problems.append(f"{sec.url} was not built")
            continue
        want = [e.id for e in sec.all_entries]
        if sorted(page.entries) != sorted(want):
            missing = sorted(set(want) - set(page.entries))
            extra = sorted(set(page.entries) - set(want))
            problems.append(f"{sec.url} shows {len(page.entries)} entries, the README has {len(want)}"
                            + (f"; missing {missing[:5]}" if missing else "") + (f"; extra {extra[:5]}" if extra else ""))
        hrefs = {h for _, h, _ in page.hrefs}
        for e in sec.all_entries:
            if e.url and e.url not in hrefs:
                problems.append(f"{sec.url} has no link to {e.url} (entry {e.id})")
            if e.anchor not in page.ids:
                problems.append(f"{sec.url} has no id {e.anchor} for entry {e.id}")
    whole = pages.get("/learn/all/")
    total = counts["entries"] + counts["unlinked"]
    if whole is None:
        problems.append("/learn/all/ was not built")
    elif len(whole.entries) != total:
        problems.append(f"/learn/all/ shows {len(whole.entries)} entries, the README has {total}")
    report.check("entry parity", problems)

    # 2. every README heading has its anchor where anchors.json says
    problems = []
    published = json.loads((dist / "anchors.json").read_text(encoding="utf-8"))
    for _, level, text, anchor in site.corpus["headings"]:
        dest = published.get(anchor)
        if dest is None:
            problems.append(f"anchors.json has no entry for #{anchor} ({text})")
            continue
        path, _, frag = dest.partition("#")
        page = pages.get(path)
        if page is None:
            problems.append(f"#{anchor} points at {path}, which was not built")
        elif frag and frag not in page.ids:
            problems.append(f"#{anchor} points at {dest}, which has no such id")
        if whole is not None and anchor not in whole.ids and anchor not in ("contents",):
            problems.append(f"/learn/all/ has no id {anchor} ({text})")
    report.check("README anchors", problems)

    # 3. an independent recount of the README against the corpus
    readme = site.files.get("README.md", "")
    rc = recount(readme)
    problems = [f"{k}: the corpus says {counts[k]}, a token walk of the README finds {v}"
                for k, v in rc.items() if counts.get(k) != v]
    report.check("independent recount", problems)

    # 4. twins, corpus.json, llms.txt, sitemap
    problems = []
    for path, page in pages.items():
        if page.twin and not target(dist, page.twin):
            problems.append(f"{path} names twin {page.twin}, which was not written")
    for sec in site.sections:
        twin = (dist / sec.twin.lstrip("/")).read_text(encoding="utf-8") if (dist / sec.twin.lstrip("/")).is_file() else ""
        body = twin.split("---\n", 2)[-1]
        raw = site.readme_slice(sec.line, sec.end_line)
        plain = re.sub(r"\]\([^)]*\)", "]()", raw)
        if re.sub(r"\]\([^)]*\)", "]()", body).strip() != plain.strip():
            problems.append(f"{sec.twin} is not the README's lines {sec.line}-{sec.end_line}")
    corpus = json.loads((dist / "corpus.json").read_text(encoding="utf-8"))
    for k, v in rc.items():
        if corpus["counts"].get(k) != v:
            problems.append(f"corpus.json counts {k} as {corpus['counts'].get(k)}, the README has {v}")
    if corpus["source"]["commit"] != site.commit:
        problems.append("corpus.json names a different commit from the pages")
    llms = (dist / "llms.txt").read_text(encoding="utf-8")
    if not llms.startswith("# ") or "\n> " not in llms:
        problems.append("llms.txt does not open with an H1 and a blockquote summary")
    for url in re.findall(r"\]\((\S+?)\)", llms):
        if url.startswith(site.base_url) and not target(dist, urlsplit(url).path):
            problems.append(f"llms.txt links {url}, which was not written")
    try:
        tree = ElementTree.parse(dist / "sitemap.xml")
        locs = [e.text for e in tree.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        for loc in locs:
            if not loc.startswith(site.base_url) or not target(dist, urlsplit(loc).path):
                problems.append(f"sitemap.xml lists {loc}, which this build does not serve")
        noindex = [p for p, info in pages.items() if 'name="robots" content="noindex"' in info.html]
        for p in noindex:
            if site.absolute(p) in locs:
                problems.append(f"sitemap.xml lists {p}, which is noindex")
    except ElementTree.ParseError as exc:
        problems.append(f"sitemap.xml does not parse: {exc}")
    report.check("twins and data files", problems)

    # 5. internal links and fragments
    problems = []
    for path, page in pages.items():
        for tag, href, rel in page.hrefs:
            parts = urlsplit(href)
            if parts.scheme or href.startswith("//"):
                continue
            if href.startswith("#"):
                frag = unquote(href[1:])
                if frag and frag not in page.ids:
                    problems.append(f"{path} links #{frag}, which is not on the page")
                continue
            dest = target(dist, parts.path or path)
            if dest is None:
                problems.append(f"{path} links {href}, which was not built")
                continue
            if parts.fragment and dest.suffix == ".html":
                other = parse(dist, dest) if dest.name != "index.html" or "/" + dest.relative_to(dist).as_posix()[:-10] not in pages \
                    else pages["/" + dest.relative_to(dist).as_posix()[:-10]]
                if unquote(parts.fragment) not in other.ids:
                    problems.append(f"{path} links {href}, which has no such id")
    report.check("internal links", problems)

    # 6. benchmarks: passports, charts against their tables, README against summary.md
    problems = []
    for b in site.benchmarks:
        page = pages.get(b.url)
        if page is None:
            problems.append(f"{b.url} was not built")
            continue
        if b.passport_filled != 7:
            empty = [label for label, v in b.passport if not v]
            problems.append(f"{b.slug}: the passport lacks {', '.join(empty)}")
        for chart in b.charts:
            m = re.search(rf'<figure class="figure" id="chart-{re.escape(chart.id)}">(.*?)</figure>', page.html, re.S)
            if not m:
                problems.append(f"{b.slug}: chart {chart.id} is not on the page")
                continue
            fig = m.group(1)
            first = fig.split('<div class="v-narrow">', 1)[0] if '<div class="v-wide">' in fig else fig
            marks = len(re.findall(r'class="mark"', first))
            table = re.search(r'<table class="data">.*?<tbody>(.*?)</tbody>', fig, re.S)
            rows = len(re.findall(r"<tr>", table.group(1))) if table else 0
            if marks != rows or marks != len(chart.points):
                problems.append(f"{b.slug}: chart {chart.id} draws {marks} marks, its table has {rows} rows, "
                                f"the spec matched {len(chart.points)} values")
        summary = site.files.get(b.files.get("summary", ""), "")
        if summary and markdown_tables(b.parts.get("results", "")) != markdown_tables(summary):
            problems.append(f"{b.slug}: the README's results tables differ from results/summary.md")
    if len([b for b in site.benchmarks if b.url in pages]) != counts["benchmarks"]:
        problems.append(f"{counts['benchmarks']} benchmarks in the corpus, "
                        f"{len([b for b in site.benchmarks if b.url in pages])} pages")
    report.check("benchmarks", problems)

    # 7. the editorial record and the MCP pages
    problems = []
    record = pages.get("/evidence/record/")
    notes = pages.get("/evidence/record/link-notes/")
    if record is None or notes is None:
        problems.append("the record pages were not built")
    else:
        for items, page in ((site.rejected, record), (site.claims, record), (site.link_notes, notes)):
            missing = [r.id for r in items if r.id not in page.ids]
            if missing:
                problems.append(f"{page.path} lacks {len(missing)} record items, e.g. {missing[:3]}")
        for r in site.rejected:
            for url in r.urls[:1]:
                if not any(h == url and "nofollow" in rel for _, h, rel in record.hrefs):
                    problems.append(f"rejected {r.id} links {url} without rel=nofollow")
                    break
    mv = site.mcp
    if mv.surface:
        names = {t["name"] for t in mv.tools}
        prompts = {p["name"] for p in mv.prompts}
        for path, page in pages.items():
            for name in set(re.findall(r"/mcp__cpu-perf__([a-z_]+)", page.html)):
                if name not in prompts:
                    problems.append(f"{path} names prompt {name}, which the server does not list")
            if path.startswith("/mcp/tools/"):
                shown = set(re.findall(r'id="tool-([a-z_]+)"', page.html))
                if shown != names:
                    problems.append(f"/mcp/tools/ shows {sorted(shown ^ names)} differently from the server")
        for path in ("/mcp/workflows/",):
            page = pages.get(path)
            if page and not prompts <= page.ids:
                problems.append(f"{path} lacks prompts {sorted(prompts - page.ids)}")
    else:
        problems.append("build/mcp-surface.json is missing; run scripts/export_mcp.py")
    from .mcp import ANCHOR_PAGES, GITHUB_ONLY

    for sec in mv.sections:
        for s in [sec] + sec.children:
            if s.anchor not in ANCHOR_PAGES and s.anchor not in GITHUB_ONLY:
                problems.append(f"misc/mcp/README.md heading {s.title!r} has no page; add it to mcp.ANCHOR_PAGES")
    report.check("record and MCP", problems)

    # 8. security headers, origins, inline styles, budgets
    problems = []
    for path, page in pages.items():
        if CSP not in page.csp:
            problems.append(f"{path} has no Content-Security-Policy meta")
        if page.styles:
            problems.append(f"{path} has {page.styles} style attributes, which the CSP blocks")
        for src in page.sources:
            if urlsplit(src).scheme or src.startswith("//"):
                problems.append(f"{path} loads {src} from another origin")
        if page.canonical and not page.canonical.startswith(site.base_url):
            problems.append(f"{path} has canonical {page.canonical}, outside {site.base_url}")
    budgets = cfg.budgets
    for sec in site.chapters:
        f = target(dist, sec.url)
        if f and f.stat().st_size > budgets["chapter_html"]:
            problems.append(f"{sec.url} is {f.stat().st_size} bytes, over the {budgets['chapter_html']} budget")
    f = target(dist, "/evidence/record/")
    if f and f.stat().st_size > budgets["record_html"]:
        problems.append(f"/evidence/record/ is {f.stat().st_size} bytes, over the {budgets['record_html']} budget")
    css = gzip.compress((dist / "site.css").read_bytes(), mtime=0)
    if len(css) > budgets["css_gzip"]:
        problems.append(f"site.css is {len(css)} bytes gzipped, over the {budgets['css_gzip']} budget")
    js = sum(len(gzip.compress(f.read_bytes(), mtime=0)) for f in (dist / "js").glob("*.js"))
    if js > budgets["js_gzip"]:
        problems.append(f"the scripts are {js} bytes gzipped, over the {budgets['js_gzip']} budget")
    fonts = sum(f.stat().st_size for f in (dist / "fonts").glob("*.woff2"))
    if fonts > budgets["fonts"]:
        problems.append(f"the fonts are {fonts} bytes, over the {budgets['fonts']} budget")
    report.check("security and budgets", problems)

    # 9. warnings: the README's own badges and the changelog's totals
    problems = []
    m = re.search(r"entries-(\d+)", readme)
    if m and int(m.group(1)) != counts["entries"]:
        problems.append(f"the README badge says {m.group(1)} entries, the list has {counts['entries']}")
    report.check("README badges", problems, warn=True)

    if not quiet:
        for name in report.passed:
            print(f"ok    {name}")
        for w in report.warnings:
            print(f"warn  {w}")
        for e in report.errors:
            print(f"FAIL  {e}")
        print(f"{len(pages)} pages, {len(report.passed)} checks passed, {len(report.errors)} failures, "
              f"{len(report.warnings)} warnings")
    failed = bool(report.errors) or (strict and bool(report.warnings))
    run_checks.last_report = report
    return 1 if failed else 0
