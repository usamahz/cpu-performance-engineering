"""Check that the site's heading anchors are the ones GitHub renders.

Every in-page id the site gives a README heading is computed the way
misc/scripts/check_format.py computes GitHub's anchors, so that a link to
README.md#some-heading lands on the right page. This script asks GitHub
itself: it renders README.md as a document (the /markdown endpoint's
"markdown" mode, as a README is rendered; the "gfm" mode renders it as a
comment, whose headings carry no anchors), falling back to the repository's
own rendered README at this commit, and compares the anchors GitHub
generates with the corpus's. A heading with an unusual character (an
underscore, an ampersand, an emoji) is where the two could part.

A network failure, or a rendering with no anchors in it at all, only warns:
the check is about GitHub's renderer, not about the commit being built.

    python misc/site/scripts/check_github_anchors.py --export misc/site/build/export.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API = "https://api.github.com"


# GitHub has marked heading anchors two ways: an <a id="user-content-x"
# class="anchor" href="#x"> after the heading (since 2023) and the same link
# inside the heading before that. Both carry the user-content- id.
ANCHOR_ID = re.compile(r'\bid="user-content-([^"]+)"')
ANCHOR_HREF = re.compile(r'<a\b(?=[^>]*\bclass="anchor")[^>]*\bhref="#([^"]+)"')


def anchors_in(html: str) -> set[str]:
    return set(ANCHOR_ID.findall(html)) | set(ANCHOR_HREF.findall(html))


def request(url: str, accept: str, body: bytes | None = None) -> str:
    req = urllib.request.Request(url, data=body, method="POST" if body else "GET", headers={
        "Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "cpu-perf-site-anchor-check",
    })
    if body:
        req.add_header("Content-Type", "application/json")
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def renderings(text: str, repo: str, ref: str | None):
    """GitHub's HTML for the README: the text rendered as a document, then
    the repository's own rendered README at this commit."""
    body = json.dumps({"text": text, "mode": "markdown", "context": repo}).encode()
    yield "the markdown API", request(f"{API}/markdown", "application/vnd.github+json", body)
    query = f"?ref={ref}" if ref else ""
    yield "the rendered README", request(f"{API}/repos/{repo}/readme{query}", "application/vnd.github.html+json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--export", type=Path, default=ROOT / "misc" / "site" / "build" / "export.json")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "usamahz/cpu-performance-engineering"))
    ap.add_argument("--ref", default=os.environ.get("GITHUB_SHA"), help="commit for the rendered-README fallback")
    args = ap.parse_args(argv)
    export = json.loads(args.export.read_text(encoding="utf-8"))
    ours = {h[3] for h in export["corpus"]["headings"]}
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    theirs: set[str] = set()
    source, sample = "", ""
    try:
        for source, html in renderings(readme, args.repo, args.ref):
            theirs = anchors_in(html)
            if theirs:
                break
            m = re.search(r"<h[1-6]\b", html)
            sample = html[m.start(): m.start() + 300] if m else html[:300]
            print(f"{source} returned no heading anchors; its first heading reads: {sample!r}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"::warning::GitHub's renderer was not reachable ({exc}); anchors not compared")
        return 0
    if not theirs:
        print("::warning::GitHub's renderings carried no heading anchors to compare; see the samples above")
        return 0
    missing = sorted(ours - theirs)
    for anchor in missing:
        print(f"::error::README heading anchor #{anchor} is not one GitHub renders")
    print(f"{len(ours)} README anchors, {len(ours) - len(missing)} match the anchors in {source}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
