"""Structured data, the sitemap and robots.txt."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape


def breadcrumb(site, trail: list[tuple[str, str]]) -> dict:
    items = [("Home", "/")] + trail
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": site.absolute(path)}
            for i, (name, path) in enumerate(items, 1)
        ],
    }


def home_ld(site) -> list[dict]:
    name = site.config.site["name"]
    return [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": name,
            "url": site.absolute("/"),
            "description": site.copy.home.description,
            "potentialAction": {
                "@type": "SearchAction",
                "target": site.absolute("/search/?q={query}"),
                "query-input": "required name=query",
            },
        },
        {
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": f"{name}: the reading list as data",
            "description": site.intro["lede"],
            "url": site.absolute("/"),
            "license": "https://opensource.org/licenses/MIT",
            "isBasedOn": site.repo_url,
            "version": site.commit_short,
            "dateModified": site.source.get("committed_at") or None,
            "distribution": [{
                "@type": "DataDownload",
                "encodingFormat": "application/json",
                "contentUrl": site.absolute("/corpus.json"),
            }],
        },
    ]


def section_ld(site, sec) -> list[dict]:
    return [
        breadcrumb(site, [(site.copy.learn.title, "/learn/"), (f"{sec.number}. {sec.title}", sec.url)])
        if sec.kind != "watchlist" else breadcrumb(site, [(sec.title, sec.url)]),
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": f"{sec.number}. {sec.title}",
            "url": site.absolute(sec.url),
            "isPartOf": site.absolute("/"),
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": sec.entry_count,
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": i,
                        "item": {
                            "@type": "CreativeWork",
                            "name": e.title,
                            **({"url": e.url} if e.url else {}),
                            "description": e.reason,
                        },
                    }
                    for i, e in enumerate(sec.all_entries, 1)
                ],
            },
        },
    ]


def benchmark_ld(site, b) -> list[dict]:
    method = b.machine.get("Method", "")
    return [
        breadcrumb(site, [(site.copy.benchmarks.title, "/benchmarks/"), (b.title, b.url)]),
        {
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": b.title,
            "description": b.index_claim or b.claim,
            "url": site.absolute(b.url),
            "license": "https://opensource.org/licenses/MIT",
            "measurementTechnique": method,
            "isBasedOn": {"@type": "SoftwareSourceCode", "codeRepository": site.repo_url,
                          "url": b.file_urls.get("code", "")},
            "distribution": [
                {"@type": "DataDownload", "encodingFormat": "text/plain",
                 "contentUrl": site.absolute(f"{b.url}raw.txt")},
                {"@type": "DataDownload", "encodingFormat": "application/json",
                 "contentUrl": site.absolute(f"{b.url}results.json")},
            ],
        },
    ]


def mcp_ld(site, path: str, label: str) -> list[dict]:
    out = [breadcrumb(site, [(site.copy.mcp.title, "/mcp/")] + ([(label, path)] if path != "/mcp/" else []))]
    if path == "/mcp/":
        server = site.mcp.server if getattr(site, "mcp", None) else {}
        out.append({
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "cpu-perf",
            "applicationCategory": "DeveloperApplication",
            "operatingSystem": "Linux, macOS, Windows",
            "softwareVersion": server.get("version") or site.generator.get("cpu_perf") or "",
            "description": server.get("description") or site.copy.mcp.title,
            "url": site.absolute("/mcp/"),
            "codeRepository": f"{site.repo_url}/tree/main/misc/mcp",
            "license": "https://opensource.org/licenses/MIT",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        })
    return out


def lastmod_for(site, sources: list[str]) -> str | None:
    stamps = []
    for src in sources:
        for path, stamp in site.lastmod.items():
            if path == src or path.startswith(src.rstrip("/") + "/"):
                stamps.append(stamp)
    return max(stamps)[:10] if stamps else (site.source.get("committed_at") or "")[:10] or None


def write_sitemap(site, dist: Path, pages) -> None:
    rows = []
    for p in pages:
        if p.noindex or not p.path.endswith("/"):
            continue
        mod = lastmod_for(site, p.sources)
        rows.append(f"  <url><loc>{escape(site.absolute(p.path))}</loc>" + (f"<lastmod>{mod}</lastmod>" if mod else "") + "</url>")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n"
    (dist / "sitemap.xml").write_text(xml, encoding="utf-8")
    robots = f"User-agent: *\nAllow: /\n\nSitemap: {site.absolute('/sitemap.xml')}\n"
    (dist / "robots.txt").write_text(robots, encoding="utf-8")
