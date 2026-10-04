"""Structured outputs of the tools (published as output schemas)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntryRef(BaseModel):
    id: str
    title: str
    url: str | None = None
    reason: str
    location: str
    anchor_url: str
    kind: str = "entry"
    condition: str | None = None
    # ask only: whether this answer carries the source's own text. quoted (passages above), in_library
    # (indexed, nothing matched), not_read (no text on this machine), and why, in `source_note`
    source_text: str | None = None
    source_note: str | None = None


class RecordItem(BaseModel):
    id: str
    kind: str  # rejected | claim | link_note | proposal
    section: int | None = None
    title: str = ""
    text: str
    url: str | None = None
    category: str | None = None
    rules: list[int] = Field(default_factory=list)
    verdict: str | None = None
    missing_fields: list[int] = Field(default_factory=list)
    file_url: str | None = None


class BenchmarkBrief(BaseModel):
    slug: str
    title: str
    section: int
    description: str = ""
    claim: str
    machine_cpu: str = ""
    url: str


class PassageOut(BaseModel):
    n: int
    id: int | None = None  # read_source(ref, passage=id) returns it in full
    title: str
    cite_url: str
    source_url: str
    page: int | None = None
    heading: str | None = None
    text: str
    trimmed: bool = False
    entry_ids: list[str] = Field(default_factory=list)
    why_listed: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)


class SearchHitOut(BaseModel):
    kind: str
    ref: str
    title: str
    url: str | None = None
    location: str = ""
    snippet: str = ""
    score: float = 0.0
    section: int | None = None
    subsection: str | None = None
    part: str | None = None
    also: list[str] = Field(default_factory=list)


class SearchOut(BaseModel):
    query: str
    scope: str
    took_ms: float = 0.0
    expanded: list[str] = Field(default_factory=list)
    did_you_mean: list[str] = Field(default_factory=list)
    hits: list[SearchHitOut] = Field(default_factory=list)
    passages: list[PassageOut] = Field(default_factory=list)
    library: str = ""


class MetricOut(BaseModel):
    name: str
    value: float
    unit: str = ""
    formula: str = ""
    inputs: list[str] = Field(default_factory=list)
    flag: str | None = None  # only when a listed source states the threshold
    source: str | None = None


class ContextOut(BaseModel):
    kinds: list[str] = Field(default_factory=list)
    vendor: str | None = None  # intel | amd | arm, from the PMUs and events printed
    metrics: list[MetricOut] = Field(default_factory=list)
    counters: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    remarks: list[str] = Field(default_factory=list)
    unparsed: list[str] = Field(default_factory=list)


class AskOut(BaseModel):
    question: str
    detail: str = "brief"
    library: str
    coverage: str = ""  # which of the sources this answer rests on were read, and which were not
    context: ContextOut | None = None
    passages: list[PassageOut] = Field(default_factory=list)
    entries: list[EntryRef] = Field(default_factory=list)
    benchmark: BenchmarkBrief | None = None
    record: list[RecordItem] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)


class SubsectionOut(BaseModel):
    id: str
    title: str
    anchor_url: str
    entries: list[EntryRef] = Field(default_factory=list)
    reproduce: list[str] = Field(default_factory=list)


class SectionOut(BaseModel):
    number: int
    title: str
    kind: str
    preamble: str
    anchor_url: str
    entries: list[EntryRef] = Field(default_factory=list)  # Start here: the numbered list
    subsections: list[SubsectionOut] = Field(default_factory=list)
    reproduce: list[str] = Field(default_factory=list)
    companions: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    watch_checked: str | None = None
    record_counts: dict[str, int] = Field(default_factory=dict)
    related_sections: list[int] = Field(default_factory=list)
    draft: str | None = None


class TocSection(BaseModel):
    number: int
    title: str
    entries: int
    subsections: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)


class TocOut(BaseModel):
    sections: list[TocSection]
    totals: dict[str, int]
    watchlist_checked: str | None = None
    corpus: str
    version: str
    library: str = ""


class SectionResult(BaseModel):
    contents: TocOut | None = None
    section: SectionOut | None = None


class EntryOut(BaseModel):
    entry: EntryRef
    matched_by: str
    also_listed: list[EntryRef] = Field(default_factory=list)
    alternatives: list[EntryRef] = Field(default_factory=list)
    before: list[EntryRef] = Field(default_factory=list)
    after: list[EntryRef] = Field(default_factory=list)
    section_preamble: str = ""
    benchmarks: list[BenchmarkBrief] = Field(default_factory=list)
    claims: list[RecordItem] = Field(default_factory=list)
    rejected_alternatives: list[RecordItem] = Field(default_factory=list)
    link_notes: list[RecordItem] = Field(default_factory=list)
    library_status: str | None = None
    related_sections: list[int] = Field(default_factory=list)
    note: str | None = None


class PathStep(BaseModel):
    n: int
    kind: str  # entry | benchmark | watch | note
    ref: str
    title: str
    url: str | None = None
    why: str
    location: str = ""


class PathOut(BaseModel):
    topic: str | None
    steps: list[PathStep]
    prerequisites: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BenchmarkDetail(BaseModel):
    slug: str
    title: str
    section: int
    description: str
    claim: str
    supports: list[EntryRef] = Field(default_factory=list)
    machine: dict[str, str] = Field(default_factory=dict)
    parts: dict[str, str] = Field(default_factory=dict)
    reproduced_from: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    next_offset: int | None = None


class BenchmarkOut(BaseModel):
    benchmarks: list[BenchmarkBrief] = Field(default_factory=list)
    detail: BenchmarkDetail | None = None


class RecordOut(BaseModel):
    query: str | None = None
    listed_as: list[EntryRef] = Field(default_factory=list)
    items: list[RecordItem] = Field(default_factory=list)
    totals: dict[str, dict[str, int]] = Field(default_factory=dict)


class FieldOut(BaseModel):
    number: int
    name: str
    status: str
    found: list[str] = Field(default_factory=list)
    note: str = ""
    question: str = ""


class EvidenceOut(BaseModel):
    claim: str
    numbers: list[str]
    fields: list[FieldOut]
    verdict: str
    summary: str
    rule: str
    precedents: list[RecordItem] = Field(default_factory=list)


class SourceOut(BaseModel):
    url: str
    doc_url: str | None = None
    title: str
    kind: str | None = None
    status: str
    detail: str | None = None
    pages: int | None = None
    partial: bool = False
    from_library: bool = False
    offset: int = 0
    next_offset: int | None = None
    total_chars: int = 0
    text: str = ""
    passages: list[PassageOut] = Field(default_factory=list)
    listed_as: list[EntryRef] = Field(default_factory=list)
    link_notes: list[RecordItem] = Field(default_factory=list)


class FileOut(BaseModel):
    path: str | None = None
    url: str | None = None
    offset: int = 0
    next_offset: int | None = None
    total_chars: int = 0
    text: str = ""
    files: list[str] = Field(default_factory=list)


class LibraryStatusOut(BaseModel):
    data_dir: str
    targets: int
    indexed: int
    by_status: dict[str, int]
    passages: int
    vectors: int
    embedder: str
    bytes: int
    last_crawl: str | None = None
    crawl: dict
    lock_held_elsewhere: bool = False
    auto_index: bool = True
    live_fetch: bool = True
    sources: list[dict] = Field(default_factory=list)
    enabled: bool = True
    corpus: str = ""  # which copy of the list is served
    list_update: str = ""  # the daily update: off, last check, error


class DocResult(BaseModel):
    id: str
    title: str
    url: str


class DocResults(BaseModel):
    """search: what ChatGPT deep research and company knowledge expect."""

    results: list[DocResult] = Field(default_factory=list)


class Document(BaseModel):
    """fetch: one document in full, with a URL the reader can open."""

    id: str
    title: str
    text: str
    url: str
    metadata: dict[str, str] | None = None
