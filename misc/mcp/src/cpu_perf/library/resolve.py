"""Where a README link's real content lives: the main document behind it.

Depth is one hop by design: an arXiv abstract page becomes its PDF, a GitHub
repository its README, a pull request its description, a vendor landing page
the manual it offers. Nothing is crawled beyond that."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

LANDING_HOSTS = ("intel.com", "docs.amd.com", "support.arm.com", "developer.arm.com")
DOC_CDNS = (
    "cdrdv2.intel.com",
    "cdrdv2-public.intel.com",
    "documentation-service.arm.com",
    "developer.arm.com",
    "docs.amd.com",
    "www.amd.com",
    "amd.com",
)
BOOK_PATTERNS = (
    re.compile(r"shop\.elsevier\.com/books/"),
    re.compile(r"informit\.com/store/"),
    re.compile(r"brendangregg\.com/.*book.*\.html"),
    re.compile(r"oreilly\.com/library/view/"),
)
GH = re.compile(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)(?:/(blob|tree|pull|discussions|issues)/(.+?))?/?(?:[#?].*)?$")
ARXIV = re.compile(r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/([^?#]+?)(?:\.pdf)?/?(?:[?#].*)?$")
README_NAMES = ("README.md", "readme.md", "README.rst", "README.markdown", "README.txt", "README")


@dataclass
class Plan:
    url: str
    kind: str  # html | pdf | arxiv | github_readme | github_file | github_pr | landing | video | book | xlsx | unsupported
    fetch: list[str] = field(default_factory=list)  # candidates for the main document, in order
    meta_url: str | None = None  # page fetched for title or abstract
    accept: str | None = None
    note: str = ""


def _raw(owner: str, repo: str, ref: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}".rstrip("/")


def plan_for(url: str) -> Plan:
    low = url.lower()
    host = (urlsplit(url).hostname or "").lower()
    path = urlsplit(url).path.lower()

    m = ARXIV.match(url)
    if m:
        ident = m.group(1)
        return Plan(url, "arxiv", fetch=[f"https://arxiv.org/pdf/{ident}"], meta_url=f"https://arxiv.org/abs/{ident}")

    m = GH.match(url)
    if m:
        owner, repo, kind, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        repo = repo.removesuffix(".git")
        if kind is None:
            cands = [_raw(owner, repo, "HEAD", n) for n in README_NAMES]
            cands.append(f"https://api.github.com/repos/{owner}/{repo}/readme")
            return Plan(url, "github_readme", fetch=cands, accept="application/vnd.github.raw")
        if kind == "blob":
            ref, _, fpath = rest.partition("/")
            kind_out = "xlsx" if fpath.lower().endswith(".xlsx") else "github_file"
            return Plan(url, kind_out, fetch=[_raw(owner, repo, ref, fpath)])
        if kind == "tree":
            ref, _, dpath = rest.partition("/")
            cands = [_raw(owner, repo, ref, f"{dpath}/{n}") for n in README_NAMES[:4]]
            cands.append(f"https://api.github.com/repos/{owner}/{repo}/readme/{dpath}?ref={ref}")
            return Plan(url, "github_readme", fetch=cands, accept="application/vnd.github.raw")
        if kind == "pull":
            number = rest.split("/")[0]
            return Plan(
                url,
                "github_pr",
                fetch=[f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}", url],
                accept="application/vnd.github+json",
            )
        return Plan(url, "html", fetch=[url])

    if "youtube.com" in host or "youtu.be" in host:
        return Plan(url, "video", fetch=[url], note="video: title and description only, no transcript")
    if any(p.search(low) for p in BOOK_PATTERNS):
        return Plan(url, "book", fetch=[url], note="book: the publisher's page only")
    if path.endswith((".ps.gz", ".ps", ".gz", ".zip", ".tar")):
        return Plan(url, "unsupported", note="compressed PostScript or archive: no text extraction")
    if path.endswith(".xlsx"):
        return Plan(url, "xlsx", fetch=[url])
    if path.endswith(".pdf"):
        return Plan(url, "pdf", fetch=[url])
    if any(host == h or host.endswith("." + h) for h in LANDING_HOSTS) and (
        "content-details" in path or host.startswith("docs.amd.com") or "documentation" in path
    ):
        return Plan(url, "landing", fetch=[url], note="vendor landing page: the manual it offers is followed")
    return Plan(url, "html", fetch=[url])


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            a = dict(attrs)
            self._href = a.get("href") or a.get("data-href")
            self._text = [a.get("title") or "", a.get("aria-label") or ""]

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(t.strip() for t in self._text if t).strip()))
            self._href = None


def _registrable(host: str) -> str:
    parts = host.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def primary_document_links(page_url: str, html: str, limit: int = 3) -> list[str]:
    """The likeliest 'main document' links on a landing page (PDF or download)."""
    parser = _LinkParser()
    try:
        parser.feed(html)
    except Exception:  # malformed markup should never stop a crawl
        pass
    base_host = (urlsplit(page_url).hostname or "").lower()
    scored: list[tuple[int, int, str]] = []
    for order, (href, text) in enumerate(parser.links):
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        url = urljoin(page_url, href)
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            continue
        host = (parts.hostname or "").lower()
        p = parts.path.lower()
        t = text.lower()
        score = 0
        if p.endswith(".pdf") or ".pdf?" in url.lower() or "/pdf/" in p:
            score += 3
        if "download" in t or "pdf" in t:
            score += 2
        if "/content" in p and host.endswith("amd.com"):
            score += 1
        if score == 0:
            continue
        if host in DOC_CDNS or _registrable(host) == _registrable(base_host):
            score += 2
        else:
            score -= 2
        if score > 1:
            scored.append((-score, order, url))
    scored.sort()
    out: list[str] = []
    for _, _, url in scored:
        if url not in out and url != page_url:
            out.append(url)
        if len(out) >= limit:
            break
    return out
