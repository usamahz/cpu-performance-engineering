"""The README grammar. HEADING, ENTRY, WATCH, TOC_LINE and github_anchor are
copied from misc/scripts/check_format.py (lines 36-45 and 70-76); a test
keeps them identical, so the linter and this server read the list the same way."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
HTML_TAG = re.compile(r"<[^>]+>")
EMPHASIS = re.compile(r"[`*_~]")
PUNCTUATION = re.compile(r"[^\w\- ]")
SPACES = re.compile(r"[ ]+")
ENTRY = re.compile(r"^(?:- |(\d+)\. )\[(?P<title>[^\]]+)\]\((?P<url>https?://[^\s)]+)\) - (?P<reason>\S.*)$")
WATCH = re.compile(r"^- (?:\[(?P<title>[^\]]+)\]\((?P<url>https?://[^\s)]+)\) - )?(?P<reason>\S.*)$")
TOC_LINE = re.compile(r"^\s*- \[(?P<text>[^\]]+)\]\(#(?P<anchor>[^)]+)\)\s*$")

# Our own additions.
REPRO = re.compile(r"^Reproduce it: \[(misc/benchmarks/(\d{2}-[a-z0-9-]+))\]\(\1/README\.md\), (.+\.)$")
CONDITION = re.compile(r"^(?P<what>.*),\s*(?P<kw>pending|once|until|when)\b\s*(?P<cond>.+)\.$")
WATCH_DATE = re.compile(r"Last checked \*\*(\d{4}-\d{2}-\d{2})\*\*")
INLINE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
NUMBERED_H2 = re.compile(r"^(\d+)\.\s+(.+)$")
BARE_URL = re.compile(r"https?://[^\s`<>\"\]]+")


def github_anchor(title: str) -> str:
    """The fragment GitHub gives a heading: drop inline HTML and markdown
    emphasis, lower-case, delete punctuation, then hyphenate the spaces."""
    text = HTML_TAG.sub("", title)
    text = EMPHASIS.sub("", text).strip().lower()
    text = PUNCTUATION.sub("", text)
    return SPACES.sub("-", text)


def clean_url(url: str) -> str:
    """Strip prose punctuation that follows a URL written in running text."""
    while url and url[-1] in ".,;:)'\"":
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def url_key(url: str, keep_fragment: bool = True) -> str:
    """A comparison key: scheme folded to https, host lower-cased without
    www., trailing slash dropped. Fragments are kept by default because three
    distinct entries differ only by fragment (clang UsersManual.html)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/") or ""
    fragment = parts.fragment if keep_fragment else ""
    return urlunsplit(("https", host, path, parts.query, fragment))


def find_urls(text: str) -> list[str]:
    seen: list[str] = []
    for raw in BARE_URL.findall(text):
        url = clean_url(raw)
        if url not in seen:
            seen.append(url)
    return seen
