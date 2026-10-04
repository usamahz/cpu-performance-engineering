"""Turn what a model passes (an id, a URL, a title, a slug) into records."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import grammar as g
from .corpus import Corpus
from .schema import Benchmark, Entry, Section
from .search import SearchIndex

ENTRY_ID = re.compile(r"^(?:1\.(\d{1,2})|(\d{1,2})\.(\d{1,2})\.(\d{1,2}))$")
SUB_ID = re.compile(r"^(\d{1,2})\.(\d{1,2})$")
SECTION_ID = re.compile(r"^(?:section\s*)?(\d{1,2})\.?$", re.I)
RECORD_ID = re.compile(r"^([rcl])(\d{1,2})\.(\d{1,3})$")
BENCH_ID = re.compile(r"^(\d{1,2})(?:-[a-z0-9-]+)?$")


class NotFound(LookupError):
    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.suggestions = suggestions or []

    def __str__(self) -> str:
        msg = super().__str__()
        if self.suggestions:
            msg += " Did you mean: " + "; ".join(self.suggestions[:5]) + "?"
        return msg


@dataclass
class EntryMatch:
    primary: Entry
    also: list[Entry] = field(default_factory=list)  # other appearances of the same URL
    alternatives: list[Entry] = field(default_factory=list)  # when the title match was fuzzy
    how: str = "id"


class Resolver:
    def __init__(self, corpus: Corpus, index: SearchIndex):
        self.c = corpus
        self.ix = index

    def entry(self, ref: str) -> EntryMatch:
        ref = (ref or "").strip()
        if not ref:
            raise NotFound("Give an entry id (e.g. 4.3.5 or 1.7), a URL or a title.")
        m = ENTRY_ID.match(ref)
        if m:
            eid = f"1.{int(m.group(1))}" if m.group(1) else f"{int(m.group(2))}.{int(m.group(3))}.{int(m.group(4))}"
            if eid in self.c.entries:
                return self._with_also(self.c.entries[eid], "id")
            sub = eid.rsplit(".", 1)[0]
            near = self.c.subsections[sub].entry_ids if sub in self.c.subsections else []
            raise NotFound(
                f"No entry {ref}. Ids are section.subsection.position (4.3.5), or 1.N for Start here.",
                [f"{i} {self.c.entries[i].title}" for i in near],
            )
        if ref.startswith(("http://", "https://")):
            found = self.c.entries_for_url(ref)
            if found:
                return EntryMatch(primary=found[0], also=found[1:], how="url")
            raise NotFound(f"{ref} is not linked from the README.", self._entry_suggestions(ref))
        low = ref.casefold()
        exact = [e for e in (self.c.entries[i] for i in self.c.order) if e.title.casefold() == low]
        if exact:
            return self._with_also(exact[0], "title")
        hits, _ = self.ix.search(ref, scope="entries", limit=5)
        entries = [self.c.entries[h.ref] for h in hits if h.ref in self.c.entries]
        if not entries:
            raise NotFound(f"No entry matches {ref!r}.")
        top = entries[0]
        prefix = top.title.casefold().startswith(low) and len(low) >= 4
        clear = len(hits) < 2 or hits[0].score >= 1.25 * hits[1].score
        match = self._with_also(top, "title" if prefix else "search")
        if not (prefix or clear):
            match.alternatives = entries[1:4]
        return match

    def _with_also(self, e: Entry, how: str) -> EntryMatch:
        others = [x for x in self.c.entries_for_url(e.url) if x.id != e.id] if e.url else []
        return EntryMatch(primary=e, also=others, how=how)

    def _entry_suggestions(self, ref: str) -> list[str]:
        hits, _ = self.ix.search(ref, scope="entries", limit=3)
        return [f"{h.ref} {h.title}" for h in hits]

    def section(self, ref: str | int) -> Section:
        if isinstance(ref, int):
            ref = str(ref)
        ref = (ref or "").strip()
        m = SECTION_ID.match(ref)
        if m and int(m.group(1)) in self.c.sections:
            return self.c.sections[int(m.group(1))]
        low = ref.casefold().lstrip("#")
        for s in self.c.sections.values():
            if low in (s.title.casefold(), s.heading.casefold(), s.anchor):
                return s
        aliases = {"watchlist": 16, "frontier": 16, "start here": 1, "start": 1}
        if low in aliases and aliases[low] in self.c.sections:
            return self.c.sections[aliases[low]]
        sm = SUB_ID.match(ref)
        if sm and ref in self.c.subsections:
            return self.c.sections[self.c.subsections[ref].section]
        for sub in self.c.subsections.values():
            if low in (sub.title.casefold(), sub.anchor):
                return self.c.sections[sub.section]
        hits, _ = self.ix.search(ref, scope="sections", limit=3)
        if hits and hits[0].section in self.c.sections:
            return self.c.sections[hits[0].section]
        raise NotFound(f"No section matches {ref!r}.", [f"{s.number}. {s.title}" for s in self.c.sections.values()])

    def subsection_id(self, ref: str) -> str | None:
        ref = (ref or "").strip()
        if ref in self.c.subsections:
            return ref
        low = ref.casefold().lstrip("#")
        for sub in self.c.subsections.values():
            if low in (sub.title.casefold(), sub.anchor):
                return sub.id
        return None

    def benchmark(self, ref: str) -> Benchmark:
        ref = (ref or "").strip().lower()
        if ref in self.c.benchmarks:
            return self.c.benchmarks[ref]
        m = BENCH_ID.match(ref)
        if m:
            num = int(m.group(1))
            for b in self.c.benchmarks.values():
                if b.number == num:
                    return b
        for b in self.c.benchmarks.values():
            if ref in (b.title.lower(), b.slug[3:].replace("-", " ")):
                return b
        hits, _ = self.ix.search(ref, kinds={"benchmark", "code"}, limit=3)
        if hits and hits[0].ref in self.c.benchmarks:
            return self.c.benchmarks[hits[0].ref]
        raise NotFound(f"No benchmark matches {ref!r}.", [f"{b.slug} ({b.title})" for b in self.c.benchmarks.values()])

    def record(self, ref: str):
        m = RECORD_ID.match((ref or "").strip().lower())
        if not m:
            return None
        kind, sec, num = m.group(1), int(m.group(2)), int(m.group(3))
        pool = {"r": self.c.rejected, "c": self.c.claims, "l": self.c.link_notes}[kind]
        rid = f"{kind}{sec}.{num}"
        return next((x for x in pool if x.id == rid), None)

    def url_for(self, ref: str) -> tuple[str, list[Entry]]:
        """A fetchable URL for an entry id, title or URL."""
        ref = (ref or "").strip()
        if ref.startswith(("http://", "https://")):
            return ref, self.c.entries_for_url(ref)
        rec = self.record(ref)
        if rec is not None and getattr(rec, "urls", None):
            return rec.urls[0], self.c.entries_for_url(rec.urls[0])
        match = self.entry(ref)
        if not match.primary.url:
            raise NotFound(f"Entry {match.primary.id} has no link.")
        return match.primary.url, [match.primary, *match.also]


def normalise_url(url: str) -> str:
    return g.url_key(url, keep_fragment=False)
