#!/usr/bin/env python3
"""Export the repository, as cpu_perf reads it, for the website build.

This is the only file in misc/site that imports cpu_perf. The README is
parsed once, by the MCP server's parser, which a test keeps identical to the
grammar of misc/scripts/check_format.py; everything the site shows comes from
the JSON written here, so the site cannot read the list a different way.

    python3 misc/site/scripts/export_corpus.py --out misc/site/build

Standard library only: cpu_perf's corpus modules import nothing else, and
this script puts misc/mcp/src on the path itself.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "misc" / "mcp" / "src"))

from cpu_perf import grammar as g  # noqa: E402
from cpu_perf.corpus import Corpus, load  # noqa: E402
from cpu_perf.locate import locate  # noqa: E402
from cpu_perf.parse_benchmarks import RESULT, parse_tables  # noqa: E402

SCHEMA = "cpu-perf-site-export"
SCHEMA_VERSION = 1

# Files the site renders verbatim, besides what the corpus parses.
EXTRA_FILES = ("README.md", "CONTRIBUTING.md", "misc/benchmarks/README.md", "misc/mcp/README.md")
BANNER = "misc/banner-pinnacle-ridge.avif"
INDEX_ROW = re.compile(r"^\| \[(?P<slug>\d{2}-[a-z0-9-]+)\]\([^)]+\) \| (?P<section>[^|]+) \| (?P<claim>[^|]+) \|$")


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def lastmod(paths: list[str]) -> dict[str, str]:
    """Commit date of the last change to each path, for the sitemap."""
    out = {}
    for p in paths:
        stamp = git("log", "-1", "--format=%cI", "--", p)
        if stamp:
            out[p] = stamp
    return out


def plain(obj):
    """Dataclasses to JSON-ready values; sets sorted, int keys as strings."""
    if dataclasses.is_dataclass(obj):
        return {f.name: plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    if isinstance(obj, set):
        return sorted(plain(v) for v in obj)
    return obj


def corpus_dict(c: Corpus) -> dict:
    keep = (
        "sections", "subsections", "entries", "order", "drafts", "rejected", "claims", "link_notes",
        "benchmarks", "seven_fields", "admission", "intro", "rules", "badge_entries", "badge_benchmarks",
        "headings", "by_url", "related", "warnings",
    )
    return {name: plain(getattr(c, name)) for name in keep}


def results(raw: str) -> list[dict]:
    """RESULT lines with the segment they sit in. A line of three hyphens starts
    a new segment; any text after it is that segment's label (08, 13, 14 repeat
    keys across segments, so a chart has to say which one it means)."""
    rows, segment, label = [], 0, None
    for n, line in enumerate(raw.splitlines(), 1):
        if line == "---" or line.startswith("--- "):
            segment += 1
            label = line[4:].strip() or None
            continue
        m = RESULT.match(line)
        if not m:
            continue
        key, value, unit = m.groups()
        try:
            number = float(value)
        except ValueError:
            number = None
        rows.append({"segment": segment, "segment_label": label, "key": key, "value": value,
                     "number": number, "unit": unit, "line": n})
    return rows


def benchmark_extra(c: Corpus, index_md: str) -> dict:
    claims = {}
    for line in index_md.splitlines():
        m = INDEX_ROW.match(line.strip())
        if m:
            claims[m.group("slug")] = m.group("claim").strip()
    out = {}
    for slug, b in c.benchmarks.items():
        code = c.reader.read_text(b.files["code"]) if c.reader.has(b.files["code"]) else ""
        raw = c.reader.read_text(b.files["raw"]) if c.reader.has(b.files["raw"]) else ""
        build = c.reader.read_text(b.files["build"]) if c.reader.has(b.files["build"]) else ""
        cflags = re.search(r'^(?:CFLAGS|BASE)="([^"]+)"', build, re.M)
        out[slug] = {
            "index_claim": claims.get(slug, ""),
            "threads": "multi-threaded" if "pthread_create" in code else "single-threaded",
            "neon": "arm_neon.h" in code,
            "cflags": cflags.group(1) if cflags else "",
            "results": results(raw),
            "raw": raw,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(ROOT), help="repository checkout to read (default: this one)")
    ap.add_argument("--out", default=str(ROOT / "misc" / "site" / "build"), help="output directory")
    ap.add_argument("--require-clean", action="store_true", help="fail when the checkout has uncommitted changes")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    reader = locate(repo)
    corpus = load(reader)
    if corpus.warnings:
        for w in corpus.warnings:
            print(f"warning: {w}", file=sys.stderr)

    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    if args.require_clean and dirty:
        print("error: the checkout has uncommitted changes", file=sys.stderr)
        return 1

    files = {}
    for rel in EXTRA_FILES:
        path = repo / rel
        if path.is_file():
            files[rel] = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    for slug, b in corpus.benchmarks.items():
        for role in ("readme", "summary"):
            rel = b.files[role]
            if reader.has(rel):
                files[rel] = reader.read_text(rel)

    pyproject = repo / "misc" / "mcp" / "pyproject.toml"
    mcp_version = tomllib.loads(pyproject.read_text())["project"]["version"] if pyproject.is_file() else None

    stats = corpus.stats()
    linked = [e for e in corpus.entries.values() if e.url]
    extra = benchmark_extra(corpus, files.get("misc/benchmarks/README.md", ""))
    counts = {
        "sections": stats["sections"],
        "subsections": stats["subsections"],
        "entries": stats["linked_entries"],
        "unlinked": stats["entries"] - stats["linked_entries"],
        "unique_urls": len({g.url_key(e.url) for e in linked}),
        "reproduce_lines": stats["reproduce_lines"],
        "benchmarks": stats["benchmarks"],
        "rejected": stats["rejected"],
        "claims": stats["claims"],
        "link_notes": stats["link_notes"],
        "result_lines": sum(len(x["results"]) for x in extra.values()),
    }

    sources = list(EXTRA_FILES) + [f for f in reader.files if f.startswith(("misc/benchmarks/", "misc/notes/sections/"))]
    envelope = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "source": {
            "repo": "usamahz/cpu-performance-engineering",
            "commit": git("rev-parse", "HEAD") or corpus.commit,
            "committed_at": git("log", "-1", "--format=%cI"),
            "dirty": dirty,
        },
        "generator": {"cpu_perf": mcp_version, "exporter": "1"},
        "counts": counts,
        "corpus": corpus_dict(corpus),
        "benchmarks_extra": extra,
        "files": files,
        "lastmod": lastmod(sorted(set(sources))),
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "export.json").write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    assets = out / "assets"
    assets.mkdir(exist_ok=True)
    if (repo / BANNER).is_file():
        shutil.copyfile(repo / BANNER, assets / "banner.avif")

    width = max(len(k) for k in counts)
    for k, v in counts.items():
        print(f"{k:<{width}}  {v}")
    print(f"commit {envelope['source']['commit'][:12]}{' (dirty)' if dirty else ''} -> {out / 'export.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
