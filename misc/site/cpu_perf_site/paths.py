"""Where pages live, and how a link written in a repository file becomes a
link on the site."""

from __future__ import annotations

import posixpath
import re
from urllib.parse import urlsplit

# GitHub's heading fragment as misc/scripts/check_format.py computes it.
# tests/test_paths.py checks this copy against cpu_perf.grammar.github_anchor
# for every heading in the README, so the two cannot drift apart.
HTML_TAG = re.compile(r"<[^>]+>")
EMPHASIS = re.compile(r"[`*_~]")
PUNCTUATION = re.compile(r"[^\w\- ]")
SPACES = re.compile(r"[ ]+")

BENCH_README = re.compile(r"^misc/benchmarks/(\d{2}-[a-z0-9-]+)/README\.md$")
BENCH_DIR = re.compile(r"^misc/benchmarks/(\d{2}-[a-z0-9-]+)/?$")


def slugify(title: str) -> str:
    text = HTML_TAG.sub("", title)
    text = EMPHASIS.sub("", text).strip().lower()
    text = PUNCTUATION.sub("", text)
    return SPACES.sub("-", text)


def is_external(href: str) -> bool:
    return bool(urlsplit(href).scheme)


class Links:
    """Rewrites repository-relative links. README anchors map to the page that
    now carries them; known documents map to their pages; everything else
    goes to GitHub at the exact commit the site was built from."""

    def __init__(self, repo_url: str, commit: str, readme_anchors: dict[str, str] | None = None,
                 mcp_anchors: dict[str, str] | None = None):
        self.repo_url = repo_url.rstrip("/")
        self.commit = commit
        self.readme_anchors = readme_anchors or {}
        self.mcp_anchors = mcp_anchors or {}

    def blob(self, path: str, line: int | None = None) -> str:
        suffix = f"#L{line}" if line else ""
        return f"{self.repo_url}/blob/{self.commit}/{path}{suffix}"

    def tree(self, path: str = "") -> str:
        return f"{self.repo_url}/tree/{self.commit}/{path}".rstrip("/")

    def readme_anchor(self, fragment: str) -> str:
        return self.readme_anchors.get(fragment, f"/learn/all/#{fragment}")

    def page_for(self, path: str, fragment: str = "") -> str | None:
        """The site page for a repository document, or None if it has none."""
        frag = f"#{fragment}" if fragment else ""
        if path == "README.md":
            return self.readme_anchor(fragment) if fragment else "/"
        if path == "CONTRIBUTING.md":
            return "/evidence/" + (frag or "#contributing")
        if path in ("misc/benchmarks/README.md", "misc/benchmarks", "misc/benchmarks/"):
            return "/benchmarks/" + frag
        m = BENCH_README.match(path) or BENCH_DIR.match(path)
        if m:
            return f"/benchmarks/{m.group(1)}/" + frag
        if path in ("misc/mcp/README.md", "misc/mcp", "misc/mcp/"):
            return self.mcp_anchor(fragment) if fragment else "/mcp/"
        return None

    def mcp_anchor(self, fragment: str) -> str:
        page = self.mcp_anchors.get(fragment)
        return f"{page}#{fragment}" if page else self.blob("misc/mcp/README.md") + f"#{fragment}"

    def rewrite(self, href: str, source: str) -> str:
        """`href` as written in the repository file `source`."""
        if not href or is_external(href) or href.startswith("mailto:"):
            return href
        if href.startswith("#"):
            # README fragments move to the page that carries the heading; any
            # other document is rendered whole, so its own fragments stay put.
            if source == "README.md":
                return self.readme_anchor(href[1:])
            if source == "misc/mcp/README.md":
                return self.mcp_anchor(href[1:])
            return href
        path, _, fragment = href.partition("#")
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
        if resolved.startswith("../"):
            return self.blob(source)
        page = self.page_for(resolved, fragment)
        if page:
            return page
        is_dir = path.endswith("/") or "." not in posixpath.basename(resolved)
        url = self.tree(resolved) if is_dir else self.blob(resolved)
        return url + (f"#{fragment}" if fragment else "")
