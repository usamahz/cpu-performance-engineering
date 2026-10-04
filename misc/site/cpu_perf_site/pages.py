"""Every page the site publishes, and the static files beside them."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup

from . import SITE_ROOT, agents, charts, images, seo
from .data import KINDS, Site
from .mcp import McpView

TEMPLATES = SITE_ROOT / "templates"
STATIC = SITE_ROOT / "static"


@dataclass
class Page:
    path: str
    template: str
    title: str
    description: str
    nav: str = ""
    twin: str | None = None
    noindex: bool = False
    og_title: str | None = None
    json_ld: list = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # repository files, for the sitemap's lastmod
    context: dict = field(default_factory=dict)


def output_path(dist: Path, path: str) -> Path:
    rel = path.lstrip("/")
    return dist / rel / "index.html" if path.endswith("/") else dist / rel


def minify_css(css: str) -> str:
    """Comments out and whitespace collapsed; selectors and values untouched."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{};])\s*", r"\1", css)
    return css.strip() + "\n"


def short_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


class Builder:
    def __init__(self, site: Site, dist: Path):
        self.site = site
        self.dist = dist
        self.copy = site.copy
        site.mcp = McpView(site.files.get("misc/mcp/README.md", ""), site.surface, site.md)
        site.featured = site.bench_by_slug.get(site.config.site.get("featured_benchmark", ""))
        charts.attach(site)
        self.assets: dict[str, str] = {}
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        self.env.filters["host"] = lambda url: urlsplit(url).netloc.removeprefix("www.")
        self.env.filters["squash"] = lambda text: " ".join(str(text or "").split())
        self.env.filters["json_ld"] = lambda obj: Markup(
            json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
        self.env.globals.update(site=site, copy=site.copy, config=site.config, kinds=KINDS, assets=self.assets)
        self.pages: list[Page] = []

    # ---------------------------------------------------------------- pages

    def plan(self) -> list[Page]:
        s, c = self.site, self.copy
        desc_home = c.home.description
        pages = [
            Page("/", "home.html", c.home.title, desc_home, twin="/index.md",
                 json_ld=seo.home_ld(s), sources=["README.md", "misc/mcp/README.md"]),
            Page("/learn/", "learn_index.html", f"{c.learn.title} · {s.config.site['name']}",
                 " ".join(s.intro["lede"].split()[:40]), nav="/learn/", twin="/learn.md",
                 json_ld=[seo.breadcrumb(s, [(c.learn.title, "/learn/")])], sources=["README.md"]),
            Page("/learn/all/", "learn_all.html", f"{c.all.title} · {s.config.site['name']}", c.all.lede,
                 nav="/learn/", twin="/learn/all.md", noindex=True, sources=["README.md"]),
            Page("/404.html", "404.html", c.notfound.heading, c.notfound.text, noindex=True),
        ]
        for sec in s.sections:
            title = f"{sec.number}. {sec.title} · {s.config.site['name']}"
            desc = " ".join((sec.preamble or f"{sec.title}: the primary sources, in dependency order.").split())
            desc = re.sub(r"\*\*", "", desc)
            if sec.kind == "watchlist":
                pages.append(Page(sec.url, "watchlist.html", title, desc, nav="/watchlist/", twin=sec.twin,
                                  json_ld=seo.section_ld(s, sec), sources=["README.md"], context={"s": sec}))
            else:
                pages.append(Page(sec.url, "chapter.html", title, desc, nav="/learn/", twin=sec.twin,
                                  json_ld=seo.section_ld(s, sec), sources=["README.md"], context={"s": sec}))
        pages += self.plan_more()
        return pages

    def plan_more(self) -> list[Page]:
        """Benchmark, evidence, record, MCP and search pages."""
        s, c = self.site, self.copy
        name = s.config.site["name"]
        pages: list[Page] = []
        if (TEMPLATES / "benchmarks_index.html").is_file():
            pages.append(Page("/benchmarks/", "benchmarks_index.html", f"{c.benchmarks.title} · {name}",
                              s.bench_readme["lede"],
                              nav="/benchmarks/", twin="/benchmarks.md",
                              json_ld=[seo.breadcrumb(s, [(c.benchmarks.title, "/benchmarks/")])],
                              sources=["misc/benchmarks/README.md"]))
            for b in s.benchmarks:
                pages.append(Page(b.url, "benchmark.html", f"{b.title} · {c.benchmarks.title}", b.index_claim or b.claim[:160],
                                  nav="/benchmarks/", twin=b.twin, json_ld=seo.benchmark_ld(s, b),
                                  sources=[b.files["readme"], b.files["raw"], b.files["summary"]], context={"b": b}))
        if (TEMPLATES / "evidence.html").is_file():
            pages.append(Page("/evidence/", "evidence.html", f"{c.evidence.title} · {name}", c.evidence.heading,
                              nav="/evidence/", twin="/evidence.md",
                              json_ld=[seo.breadcrumb(s, [(c.evidence.title, "/evidence/")])],
                              sources=["README.md", "CONTRIBUTING.md"]))
        if (TEMPLATES / "record.html").is_file():
            pages.append(Page("/evidence/record/", "record.html", f"{c.record.title} · {name}", c.record.lede,
                              nav="/evidence/", twin="/evidence/record.md",
                              json_ld=[seo.breadcrumb(s, [(c.evidence.title, "/evidence/"), (c.record.title, "/evidence/record/")])],
                              sources=["misc/notes/sections"]))
            pages.append(Page("/evidence/record/link-notes/", "record_link_notes.html",
                              f"{c.record.link_notes} · {c.record.title}", c.record.link_notes_lede, nav="/evidence/",
                              twin="/evidence/record/link-notes.md", sources=["misc/notes/sections"]))
        if (TEMPLATES / "mcp" / "index.html").is_file():
            for slug, label, desc in (
                ("", c.mcp.nav_overview, c.mcp.title),
                ("quickstart/", c.mcp.nav_quickstart, c.mcp.quickstart_lede),
                ("tools/", c.mcp.nav_tools, c.mcp.tools_lede),
                ("resources/", c.mcp.nav_resources, c.mcp.resources_lede),
                ("workflows/", c.mcp.nav_workflows, c.mcp.workflows_lede),
                ("security/", c.mcp.nav_security, c.mcp.security_lede),
            ):
                tmpl = f"mcp/{slug.rstrip('/') or 'index'}.html"
                path = f"/mcp/{slug}"
                title = f"{c.mcp.title} · {name}" if not slug else f"{label} · {c.mcp.title}"
                twin = "/mcp.md" if not slug else f"/mcp/{slug.rstrip('/')}.md"
                pages.append(Page(path, tmpl, title, desc, nav="/mcp/", twin=twin,
                                  json_ld=seo.mcp_ld(s, path, label), sources=["misc/mcp/README.md"],
                                  context={"active": path}))
        if (TEMPLATES / "search.html").is_file():
            pages.append(Page("/search/", "search.html", f"{c.search.title} · {name}", c.search.heading,
                              nav="", noindex=True))
        return pages

    # ---------------------------------------------------------------- build

    def static(self) -> None:
        css = minify_css((STATIC / "site.css").read_text(encoding="utf-8"))
        (self.dist / "site.css").write_text(css, encoding="utf-8")
        self.assets["css"] = short_hash(css.encode())
        shutil.copytree(STATIC / "fonts", self.dist / "fonts", dirs_exist_ok=True)
        js_dir = self.dist / "js"
        js_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        for f in sorted((STATIC / "js").glob("*.js")):
            data = f.read_bytes()
            digest.update(data)
            (js_dir / f.name).write_bytes(data)
        self.assets["js"] = digest.hexdigest()[:10]
        for name in ("favicon.svg",):
            if (STATIC / name).is_file():
                shutil.copyfile(STATIC / name, self.dist / name)

    def render(self, page: Page) -> None:
        template = self.env.get_template(page.template)
        html = template.render(page=page, **page.context)
        out = output_path(self.dist, page.path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")

    def build(self) -> list[Page]:
        if self.dist.exists():
            shutil.rmtree(self.dist)
        self.dist.mkdir(parents=True)
        self.static()
        self.pages = self.plan()
        for page in self.pages:
            self.render(page)
        agents.write_all(self.site, self.dist, self.pages)
        seo.write_sitemap(self.site, self.dist, self.pages)
        images.write_all(self.site, self.dist)
        return self.pages
