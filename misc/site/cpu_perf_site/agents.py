"""Files for agents: a Markdown twin of every page, llms.txt and
llms-full.txt, corpus.json with its schema, search.json and anchors.json."""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path

SCHEMA_ID = "cpu-perf-site-corpus"
SCHEMA_VERSION = "1.0.0"


def front_matter(site, title: str, page: str, source: str | None = None) -> str:
    lines = ["---", f"title: {json.dumps(title, ensure_ascii=False)}", f"url: {site.absolute(page)}"]
    if source:
        lines.append(f"source: {source}")
    lines += [f"commit: {site.commit}", "---", ""]
    return "\n".join(lines)


def write(dist: Path, path: str, text: str) -> None:
    out = dist / path.lstrip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def section_twin(site, sec) -> str:
    body = site.readme_slice(sec.line, sec.end_line)
    body = site.md.absolutise(body, "README.md", site.base_url)
    src = site.links.blob("README.md", sec.line)
    return front_matter(site, f"{sec.number}. {sec.title}", sec.url, src) + body


def benchmark_twin(site, b) -> str:
    text = site.md.absolutise(b.readme, b.files["readme"], site.base_url)
    return front_matter(site, b.title, b.url, site.links.blob(b.files["readme"])) + text


def record_twin(site) -> str:
    out = [front_matter(site, site.copy.record.title, "/evidence/record/"), f"# {site.copy.record.heading}", "",
           site.copy.record.lede, ""]
    for sec in site.sections:
        rej = [r for r in site.rejected if r.section == sec.number]
        cl = [r for r in site.claims if r.section == sec.number]
        if not rej and not cl:
            continue
        out += [f"## {sec.number}. {sec.title}", ""]
        if rej:
            out += [f"### {site.copy.record.rejected}", ""]
            for r in rej:
                link = f"[{r.title}]({r.urls[0]})" if r.urls else r.title
                out.append(f"- {r.id} {link}: {strip_html(r.html)}")
            out.append("")
        if cl:
            out += [f"### {site.copy.record.claims}", ""]
            for r in cl:
                verdict = f" Verdict: {r.verdict}." if r.verdict else ""
                out.append(f"- {r.id} {strip_html(r.html)}{verdict}")
            out.append("")
    return "\n".join(out) + "\n"


def strip_html(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", html))


def learn_twin(site) -> str:
    learn = site.copy.learn
    out = [front_matter(site, learn.heading, "/learn/"), f"# {learn.heading}", "", learn.description, ""]
    for g in site.groups:
        out += [f"## {g.name}", "", g.blurb, ""]
        for s in g.sections:
            out.append(f"- [{s.number}. {s.title}]({site.absolute(s.twin)})" + (f": {strip_html(s.preamble_html)}" if s.preamble else ""))
        out.append("")
    out += [f"## {learn.questions_heading}", ""]
    for q in learn.questions:
        b = site.bench_by_slug[q["benchmark"]]
        out += [f"### {q['title']}", "", q["text"], "",
                f"- [{q['read']}]({site.absolute(q['href'])})",
                f"- [{b.title}]({site.absolute(b.url)})", ""]
    return "\n".join(out)


def home_twin(site) -> str:
    readme = site.files.get("README.md", "")
    lines = readme.splitlines()
    contents = next((h[0] for h in site.corpus["headings"] if h[3] == "contents"), len(lines))
    body = "\n".join(lines[: contents - 1]).strip() + "\n"
    return front_matter(site, site.config.site["name"], "/", site.links.blob("README.md")) + site.md.absolutise(body, "README.md", site.base_url)


def llms_txt(site, pages) -> str:
    name = site.config.site["name"]
    pages = {p.path: p for p in pages}
    out = [f"# {name}", "", f"> {site.copy.home.description}", "",
           f"{site.counts['sections']} sections, {site.counts['entries']} primary-source entries and "
           f"{site.counts['benchmarks']} runnable C benchmarks with committed results.",
           "",
           "Cite the HTML page for the reading list or a benchmark. Cite the linked paper, manual or specification "
           "for a source claim. Benchmark pages state what was measured, on which machine, and where the result applies. "
           "Markdown copies include the canonical HTML URL and the source commit."]

    def add(path: str, label: str) -> None:
        page = pages[path]
        out.append(f"- [{label}]({site.absolute(path)}): {page.description.rstrip('.')}."
                   f" [Markdown]({site.absolute(page.twin)})")

    out += ["", "## Start here", ""]
    add("/learn/", site.copy.learn.search_title)
    add("/benchmarks/", site.copy.benchmarks.search_title)
    add("/evidence/", site.copy.evidence.search_title)
    out += ["", "## Reading list", ""]
    for s in site.sections:
        add(s.url, f"{s.number}. {pages[s.url].title}")
    out += ["", "## Benchmarks", ""]
    for b in site.benchmarks:
        add(b.url, site.copy.benchmark_search.get(b.slug, b.title))
    out += ["", "## MCP server", ""]
    add("/mcp/", site.copy.mcp.search_title)
    for path in ("/mcp/quickstart/", "/mcp/tools/", "/mcp/resources/", "/mcp/workflows/", "/mcp/security/"):
        add(path, pages[path].title)
    out += ["", "## Data", ""]
    out.append(f"- [corpus.json]({site.absolute('/corpus.json')}): The parsed reading list, benchmark results and editorial record. "
               f"[JSON Schema]({site.absolute('/schema/corpus-v1.json')})")
    out += ["", "## Optional", ""]
    add("/evidence/record/", site.copy.record.title)
    out.append(f"- [llms-full.txt]({site.absolute('/llms-full.txt')}): The complete reading entries, benchmark reports, evidence rules and MCP overview.")
    return "\n".join(out) + "\n"


def corpus_json(site) -> dict:
    export = site.export
    corpus = {k: v for k, v in export["corpus"].items() if k not in ("by_url",)}
    derived_entries = {
        e.id: {"key": e.key, "progress_key": e.progress_key, "page": e.page, "kind": e.badge,
               "also_in": [o.id for o in e.also_in], "markdown": e.readme_line}
        for e in site.entries.values()
    }
    derived_sections = {
        str(s.number): {"slug": s.slug, "group": s.group.id if s.group else None, "page": s.url,
                        "twin": s.twin, "mcp_resource": s.mcp_resource}
        for s in site.sections
    }
    derived_bench = {
        b.slug: {"page": b.url, "threads": b.threads, "neon": b.neon, "results": b.results}
        for b in site.benchmarks
    }
    return {
        "schema": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "source": export["source"],
        "generator": export["generator"],
        "counts": export["counts"],
        "corpus": corpus,
        "derived": {"entries": derived_entries, "sections": derived_sections, "anchors": site.anchors,
                    "benchmarks": derived_bench, "kind_method": "host-and-path rules, a reading aid"},
    }


def corpus_schema() -> dict:
    """The envelope's shape. The corpus itself follows cpu_perf.schema's dataclasses."""
    obj = {"type": "object"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_ID}/{SCHEMA_VERSION}",
        "title": "cpuperf.com corpus",
        "type": "object",
        "required": ["schema", "schema_version", "source", "counts", "corpus", "derived"],
        "properties": {
            "schema": {"const": SCHEMA_ID},
            "schema_version": {"type": "string"},
            "source": {"type": "object", "required": ["repo", "commit"],
                       "properties": {"repo": {"type": "string"}, "commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                                      "committed_at": {"type": "string"}, "dirty": {"type": "boolean"}}},
            "generator": obj,
            "counts": {"type": "object", "additionalProperties": {"type": "integer"}},
            "corpus": {"type": "object", "required": ["sections", "subsections", "entries", "order", "benchmarks",
                                                       "rejected", "claims", "link_notes"]},
            "derived": {"type": "object", "required": ["entries", "sections", "anchors", "benchmarks"]},
        },
    }


def search_index(site) -> list[dict]:
    rows: list[dict] = []
    for s in site.sections:
        rows.append({"y": "section", "t": f"{s.number_label} {s.title}", "x": strip_html(s.preamble_html), "u": s.url})
        for sub in s.subsections:
            rows.append({"y": "part", "t": f"{s.number_label} {s.title} › {sub.title}", "x": "", "u": f"{s.url}#{sub.anchor}"})
    for e in site.entries.values():
        sec = site.section_by_number[e.section]
        where = sec.title
        if e.subsection:
            sub = next((x for x in sec.subsections if x.id == e.subsection), None)
            where = f"{sec.number_label} {sub.title if sub else sec.title}"
        rows.append({"y": "source", "t": e.title, "x": e.reason, "u": e.page, "k": e.badge, "i": where, "h": e.host})
    for b in site.benchmarks:
        rows.append({"y": "benchmark", "t": b.title, "x": f"{b.index_claim} {b.slug}", "u": b.url})
    for r in site.rejected:
        if r.title:
            rows.append({"y": "record", "t": r.title, "x": strip_html(r.html)[:220], "u": f"/evidence/record/#{r.id}"})
    return rows


def _mcp_sections(site, anchors: list[str], level: int = 2) -> str:
    """Sections of the server's README, by anchor, with their H3 children."""
    mv, out = site.mcp, []
    for anchor in anchors:
        s = mv.find(anchor)
        if s is None:
            continue
        out.append(f"{'#' * level} {s.title}\n\n{s.body}")
        for c in s.children if s.level == 2 and anchor != "the-first-run-building-the-library" else []:
            out.append(f"{'#' * (level + 1)} {c.title}\n\n{c.body}")
    return site.md.absolutise("\n\n".join(out), "misc/mcp/README.md", site.base_url)


def mcp_twins(site) -> dict[str, str]:
    """The MCP pages as Markdown: README sections where a page quotes the
    README, and the server's own tool, resource and prompt lists where a page
    lists them."""
    mv, c = site.mcp, site.copy.mcp
    src = site.links.blob("misc/mcp/README.md")
    twins = {}
    twins["/mcp/quickstart.md"] = (front_matter(site, c.quickstart_heading, "/mcp/quickstart/", src) + f"# {c.quickstart_heading}\n\n"
                                   + _mcp_sections(site, ["connect-it", "the-first-run-building-the-library", "configuration"]))
    tools = [front_matter(site, c.tools_heading, "/mcp/tools/", src), f"# {c.tools_heading}", "", c.tools_lede, ""]
    for t in mv.tools:
        tools.append(f"## {t['name']}")
        tools.append("")
        tools.append(f"{t.get('title', '')}. {c.access}: {c.access_network if mv.tool_access(t) == 'network' else c.access_read}.")
        tools.append("")
        tools.append(" ".join(str(t.get("description", "")).split()))
        tools.append("")
        for prm in mv.params(t):
            req = f" ({c.required})" if prm["required"] else ""
            tools.append(f"- `{prm['name']}`{req}, {prm['type']}: {' '.join(prm['description'].split())}")
        tools.append("")
    twins["/mcp/tools.md"] = "\n".join(tools) + "\n"
    res = [front_matter(site, c.resources_heading, "/mcp/resources/", src), f"# {c.resources_heading}", "", c.resources_lede, "",
           f"## {c.fixed}", ""]
    res += [f"- `{r['uri']}`: {r.get('title') or r.get('name', '')}" for r in mv.resources]
    res += ["", f"## {c.templates}", ""]
    res += [f"- `{t['uriTemplate']}`: {t.get('title') or t.get('name', '')}" for t in mv.templates]
    twins["/mcp/resources.md"] = "\n".join(res) + "\n"
    wf = [front_matter(site, c.workflows_heading, "/mcp/workflows/", src), f"# {c.workflows_heading}", "", c.workflows_lede, ""]
    for p in mv.prompts:
        wf += [f"## {p['name']}", "", f"{p.get('title', '')}: {' '.join(str(p.get('description', '')).split())}", ""]
        wf += [f"- `{a['name']}`" + (f" ({c.required})" if a.get("required") else "") for a in p.get("arguments", [])]
        wf.append("")
    twins["/mcp/workflows.md"] = "\n".join(wf) + "\n" + _mcp_sections(site, ["use-it-for-your-own-work"]) + "\n"
    twins["/mcp/security.md"] = (front_matter(site, c.security_heading, "/mcp/security/", src) + f"# {c.security_heading}\n\n"
                                 + _mcp_sections(site, ["how-it-stays-honest", "safety-of-fetching", "copyright-and-politeness",
                                                        "keeping-the-list-current", "serving-over-http"]) + "\n")
    return twins


def write_all(site, dist: Path, pages) -> None:
    write(dist, "/index.md", home_twin(site))
    learn_md = learn_twin(site)
    write(dist, "/learn.md", learn_md)
    all_md = [front_matter(site, site.copy.all.title, "/learn/all/", site.links.blob("README.md"))]
    for s in site.sections:
        all_md.append(section_twin(site, s).split("---\n", 2)[-1])
        write(dist, s.twin, section_twin(site, s))
    write(dist, "/learn/all.md", "\n".join(all_md))
    index = llms_txt(site, pages)
    full = [index, learn_md]
    for s in site.sections:
        full.append(section_twin(site, s))
    for b in site.benchmarks:
        write(dist, b.twin, benchmark_twin(site, b))
        full.append(benchmark_twin(site, b))
        out = dist / b.url.lstrip("/")
        out.mkdir(parents=True, exist_ok=True)
        (out / "raw.txt").write_text(b.raw, encoding="utf-8")
        (out / "results.json").write_text(json.dumps({"benchmark": b.slug, "commit": site.commit, "results": b.results},
                                                     ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    contributing = site.md.absolutise(site.files.get("CONTRIBUTING.md", ""), "CONTRIBUTING.md", site.base_url)
    admission = site.md.absolutise(site.corpus["admission"], "README.md", site.base_url)
    evidence = (front_matter(site, site.copy.evidence.title, "/evidence/", site.links.blob("CONTRIBUTING.md"))
                + "# What earns a place\n\n" + admission + "\n\n" + contributing)
    write(dist, "/evidence.md", evidence)
    full.append(evidence)
    write(dist, "/evidence/record.md", record_twin(site))
    notes = [front_matter(site, site.copy.record.link_notes, "/evidence/record/link-notes/"), f"# {site.copy.record.link_notes}", ""]
    notes += [f"- {n.id} (§{n.section}) {strip_html(n.html)}" for n in site.link_notes]
    write(dist, "/evidence/record/link-notes.md", "\n".join(notes) + "\n")
    mcp_md = front_matter(site, "cpu-perf", "/mcp/", site.links.blob("misc/mcp/README.md")) + site.md.absolutise(
        site.files.get("misc/mcp/README.md", ""), "misc/mcp/README.md", site.base_url)
    write(dist, "/mcp.md", mcp_md)
    full.append(mcp_md)
    for path, text in mcp_twins(site).items():
        write(dist, path, text)
    if any(p.path == "/benchmarks/" for p in pages):
        bench_index = site.md.absolutise(site.files.get("misc/benchmarks/README.md", ""), "misc/benchmarks/README.md", site.base_url)
        write(dist, "/benchmarks.md", front_matter(site, site.copy.benchmarks.title, "/benchmarks/",
                                                   site.links.blob("misc/benchmarks/README.md")) + bench_index)
    write(dist, "/llms.txt", index)
    write(dist, "/llms-full.txt", "\n\n".join(full))
    write(dist, "/corpus.json", json.dumps(corpus_json(site), ensure_ascii=False, separators=(",", ":")) + "\n")
    write(dist, "/schema/corpus-v1.json", json.dumps(corpus_schema(), indent=1) + "\n")
    write(dist, "/search.json", json.dumps(search_index(site), ensure_ascii=False, separators=(",", ":")) + "\n")
    write(dist, "/anchors.json", json.dumps(site.anchors, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
