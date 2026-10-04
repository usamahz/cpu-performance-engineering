"""Plain records for everything the repository says. Built once at start-up and
treated as read-only afterwards."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Reproduce:
    slug: str
    description: str
    line: int
    section: int
    subsection: str | None


@dataclass(slots=True)
class Companion:
    """A prose line in a section that links a source without being an entry
    (README L123, Performance Ninja)."""

    title: str
    url: str
    text: str
    line: int
    section: int


@dataclass(slots=True)
class Entry:
    id: str  # "4.3.5"; Start here uses its own number, "1.7"
    kind: str  # start_here | entry | watch
    section: int
    subsection: str | None  # "4.3"; None for Start here
    position: int
    title: str
    url: str | None
    reason: str
    line: int
    host: str = ""
    condition: str | None = None
    condition_kw: str | None = None


@dataclass(slots=True)
class Subsection:
    id: str
    section: int
    position: int
    title: str
    anchor: str
    line: int
    entry_ids: list[str] = field(default_factory=list)
    reproduce: list[Reproduce] = field(default_factory=list)


@dataclass(slots=True)
class Section:
    number: int
    title: str
    heading: str
    anchor: str
    line: int
    kind: str  # start_here | core | watchlist
    preamble: str = ""
    subsection_ids: list[str] = field(default_factory=list)
    entry_ids: list[str] = field(default_factory=list)
    reproduce: list[Reproduce] = field(default_factory=list)
    companions: list[Companion] = field(default_factory=list)
    benchmarks: list[str] = field(default_factory=list)
    draft: str | None = None
    owner: str | None = None
    watch_checked: str | None = None


@dataclass(slots=True)
class Rejected:
    id: str  # "r9.17"
    section: int
    line: int
    source: str
    title: str
    urls: list[str]
    reason: str
    category: str
    rules: list[int]
    unlinked_ref: str | None = None
    note: str | None = None
    left_to: int | None = None
    listed_in: list[int] = field(default_factory=list)
    raw: str = ""


@dataclass(slots=True)
class Claim:
    id: str  # "c9.2"
    section: int
    line: int
    source: str
    text: str
    quote: str | None
    urls: list[str]
    fields_text: str | None
    missing_text: str | None
    missing_fields: list[int]
    verdict: str | None  # core | watchlist | cut | not_quoted | other | None
    verdict_text: str | None


@dataclass(slots=True)
class LinkNote:
    id: str  # "l9.5"
    section: int
    line: int
    source: str
    urls: list[str]
    text: str


@dataclass(slots=True)
class Draft:
    number: int
    path: str
    owner: str | None
    heading: str
    proposal: str


@dataclass(slots=True)
class Table:
    caption: str
    header: list[str]
    rows: list[list[str]]


@dataclass(slots=True)
class Benchmark:
    slug: str
    number: int
    title: str
    description: str
    claim: str
    supports_text: str
    supports: list[str]
    machine: dict[str, str]
    parts: dict[str, str]  # claim, method, generated_code, machine, ..., results, analysis, limits, reproduce
    results_md: str
    tables: list[Table]
    raw_header: dict[str, str]
    files: dict[str, str]  # role -> repository path
    reproduced_from: list[tuple[int, str | None]] = field(default_factory=list)


@dataclass(slots=True)
class NoteChunk:
    id: str
    path: str
    heading: str
    level: int
    line: int
    text: str
