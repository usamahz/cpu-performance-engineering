"""In-memory BM25F over everything the repository says.

Each term's weight already folds in its IDF, field weights, length
normalisation and the document kind's prior, so a query only sums postings."""

from __future__ import annotations

import difflib
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import text as tx
from .corpus import Corpus

K1 = 1.2
FIELDS = {  # name: (weight, b)
    "title": (3.0, 0.2),
    "body": (1.0, 0.75),
    "path": (1.0, 0.3),
    "url": (0.5, 0.0),
}
STEM_WEIGHT = 0.4
SYNONYM_WEIGHT = 0.6
PRIORS = {
    "entry": 1.0,
    "watch": 0.95,
    "companion": 0.9,
    "subsection": 0.9,
    "benchmark": 0.85,
    "section": 0.8,
    "note": 0.6,
    "rejected": 0.6,
    "claim": 0.55,
    "proposal": 0.5,
    "code": 0.45,
    "link_note": 0.35,
}
SCOPES = {
    "list": {"entry", "watch", "companion", "subsection", "section", "benchmark"},
    "entries": {"entry", "watch", "companion"},
    "sections": {"section", "subsection"},
    "benchmarks": {"benchmark", "code"},
    "record": {"rejected", "claim", "link_note", "proposal"},
    "rejected": {"rejected"},
    "claims": {"claim"},
    "link_notes": {"link_note"},
    "notes": {"note"},
    "code": {"code"},
    "watchlist": {"watch"},
    "all": set(PRIORS),
}
C_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
C_SIGNATURE = re.compile(r"^(?:static\s+)?(?:inline\s+)?[A-Za-z_][\w\s\*]*\b(\w+)\s*\([^;{]*\)\s*\{?\s*$", re.M)


@dataclass(slots=True)
class Doc:
    kind: str
    ref: str  # entry id, "4.3", "9", benchmark slug, record id, note id
    title: str
    body: str
    path: str = ""
    url: str | None = None
    section: int | None = None
    subsection: str | None = None
    group: str | None = None  # collapse key (URL or benchmark slug)
    part: str | None = None  # benchmark part name


@dataclass(slots=True)
class Hit:
    kind: str
    ref: str
    title: str
    url: str | None
    section: int | None
    subsection: str | None
    location: str
    score: float
    snippet: str
    part: str | None = None
    also: list[str] = field(default_factory=list)


def url_words(url: str | None) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    return f"{parts.hostname or ''} {parts.path}".replace("/", " ")


def build_docs(c: Corpus) -> list[Doc]:
    docs: list[Doc] = []
    for eid in c.order:
        e = c.entries[eid]
        sec = c.sections[e.section]
        path = sec.title + (" / " + c.subsections[e.subsection].title if e.subsection else "")
        body = e.reason
        docs.append(
            Doc(
                kind="watch" if e.kind == "watch" else "entry",
                ref=e.id,
                title=e.title,
                body=body,
                path=path,
                url=e.url,
                section=e.section,
                subsection=e.subsection,
                group=e.url,
            )
        )
    for s in c.sections.values():
        docs.append(Doc(kind="section", ref=str(s.number), title=s.title, body=s.preamble, section=s.number))
        for comp in s.companions:
            docs.append(
                Doc(kind="companion", ref=f"{s.number}.companion", title=comp.title, body=comp.text, path=s.title, url=comp.url, section=s.number)
            )
    for sub in c.subsections.values():
        titles = "; ".join(c.entries[i].title for i in sub.entry_ids)
        docs.append(
            Doc(kind="subsection", ref=sub.id, title=sub.title, body=titles, path=c.sections[sub.section].title, section=sub.section, subsection=sub.id)
        )
    for b in c.benchmarks.values():
        main = f"{b.description} {b.claim} {b.supports_text}"
        docs.append(Doc(kind="benchmark", ref=b.slug, title=b.title, body=main, path=c.sections[b.number].title if b.number in c.sections else "", section=b.number, group=b.slug, part="claim"))
        for part, body in b.parts.items():
            if part in ("claim",) or not body:
                continue
            docs.append(
                Doc(kind="benchmark", ref=b.slug, title=part.replace("_", " "), body=body, path=b.title, section=b.number, group=b.slug, part=part)
            )
        code = c.reader.read_text(b.files["code"]) if c.reader.has(b.files["code"]) else ""
        if code:
            comments = " ".join(m.group(0).strip("/* ") for m in C_COMMENT.finditer(code))
            sigs = " ".join(m.group(1) for m in C_SIGNATURE.finditer(code))
            docs.append(Doc(kind="code", ref=b.slug, title=f"{b.slug} bench.c", body=f"{comments} {sigs}", path=b.title, section=b.number, group=b.slug, part="code"))
    for r in c.rejected:
        docs.append(Doc(kind="rejected", ref=r.id, title=r.title, body=r.reason, path=c.sections[r.section].title if r.section in c.sections else "", url=(r.urls[0] if r.urls else None), section=r.section))
    for cl in c.claims:
        title = cl.quote or cl.text[:90]
        docs.append(Doc(kind="claim", ref=cl.id, title=title, body=cl.text, path=c.sections[cl.section].title if cl.section in c.sections else "", url=(cl.urls[0] if cl.urls else None), section=cl.section))
    for ln in c.link_notes:
        hosts = " ".join(urlsplit(u).hostname or "" for u in ln.urls)
        docs.append(Doc(kind="link_note", ref=ln.id, title=hosts, body=ln.text, url=(ln.urls[0] if ln.urls else None), section=ln.section))
    for d in c.drafts.values():
        if d.proposal:
            docs.append(Doc(kind="proposal", ref=f"p{d.number}", title=f"Benchmark proposal, section {d.number}", body=d.proposal, section=d.number))
    for n in c.notes:
        docs.append(Doc(kind="note", ref=n.id, title=n.heading, body=n.text, path=n.path))
    return docs


class SearchIndex:
    def __init__(self, corpus: Corpus):
        t0 = time.perf_counter()
        self.corpus = corpus
        self.docs = build_docs(corpus)
        self.postings: dict[str, list[tuple[int, float]]] = {}
        self.title_tokens: list[tuple[str, ...]] = []
        self.vocab: set[str] = set()
        self._by_letter: dict[str, list[str]] | None = None
        self._build()
        self.synonyms = self._synonyms()
        self.build_ms = (time.perf_counter() - t0) * 1000

    # ----- build ---------------------------------------------------------

    def _build(self) -> None:
        n_docs = len(self.docs)
        field_tf: list[dict[str, Counter]] = []
        field_len: dict[str, list[int]] = {f: [] for f in FIELDS}
        for d in self.docs:
            per: dict[str, Counter] = {}
            values = {"title": d.title, "body": d.body, "path": d.path, "url": url_words(d.url)}
            for f, val in values.items():
                toks = tx.tokens(val) if val else []
                if f == "title":
                    self.title_tokens.append(tuple(toks))
                cnt = Counter(toks)
                cnt.update("~" + tx.stem(t) for t in toks)
                per[f] = cnt
                field_len[f].append(len(toks))
            field_tf.append(per)
        avg = {f: (sum(v) / max(1, len(v))) or 1.0 for f, v in field_len.items()}

        df: Counter = Counter()
        for per in field_tf:
            terms = set()
            for cnt in per.values():
                terms.update(cnt)
            df.update(terms)

        postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for i, (d, per) in enumerate(zip(self.docs, field_tf)):
            prior = PRIORS.get(d.kind, 0.5)
            combined: dict[str, float] = defaultdict(float)
            for f, cnt in per.items():
                w, b = FIELDS[f]
                norm = 1 - b + b * (field_len[f][i] / avg[f])
                for term, tf in cnt.items():
                    combined[term] += w * tf / norm
            for term, tfp in combined.items():
                idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
                postings[term].append((i, idf * (tfp * (K1 + 1)) / (tfp + K1) * prior))
        self.postings = dict(postings)
        self.vocab = {t for t in self.postings if not t.startswith("~")}

    def _synonyms(self) -> dict[tuple[str, ...], list[tuple[str, ...]]]:
        table: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
        for phrase, expansions in tx.synonym_phrases():
            useful = [e for e in expansions if all(t in self.vocab for t in e)]
            if useful:
                table.setdefault(phrase, []).extend(x for x in useful if x not in table.get(phrase, []))
        return table

    # ----- query ---------------------------------------------------------

    def expand(self, qtoks: list[str]) -> tuple[dict[str, float], list[str]]:
        weights: dict[str, float] = {}
        for t in qtoks:
            weights[t] = max(weights.get(t, 0.0), 1.0)
            weights["~" + tx.stem(t)] = max(weights.get("~" + tx.stem(t), 0.0), STEM_WEIGHT)
        expanded: list[str] = []
        n = len(qtoks)
        for size in (3, 2, 1):
            for i in range(n - size + 1):
                phrase = tuple(qtoks[i : i + size])
                for exp in self.synonyms.get(phrase, []):
                    for t in exp:
                        if weights.get(t, 0.0) < SYNONYM_WEIGHT:
                            weights[t] = SYNONYM_WEIGHT
                            weights.setdefault("~" + tx.stem(t), STEM_WEIGHT * 0.6)
                    label = " ".join(exp)
                    if label not in expanded:
                        expanded.append(label)
        return weights, expanded

    def did_you_mean(self, qtoks: list[str]) -> list[str]:
        if self._by_letter is None:
            by: dict[str, list[str]] = defaultdict(list)
            for v in self.vocab:
                if v.isalpha() and len(v) >= 3:
                    by[v[0]].append(v)
            self._by_letter = dict(by)
        out = []
        for t in qtoks:
            if len(t) < 4 or t in self.vocab or not t.isalpha():
                continue
            cands = difflib.get_close_matches(t, self._by_letter.get(t[0], []), n=3, cutoff=0.8)
            out.extend(c for c in cands if c not in out)
        return out

    def search(
        self,
        query: str,
        scope: str = "list",
        section: int | None = None,
        limit: int = 10,
        kinds: set[str] | None = None,
    ) -> tuple[list[Hit], dict]:
        t0 = time.perf_counter()
        qtoks = tx.tokens(query)
        meta: dict = {"expanded": [], "did_you_mean": []}
        if not qtoks:
            return [], meta
        dym = self.did_you_mean(qtoks)
        if dym:
            qtoks = qtoks + [d for d in dym if d not in qtoks]
            meta["did_you_mean"] = dym
        weights, expanded = self.expand(qtoks)
        meta["expanded"] = expanded
        allowed = kinds or SCOPES.get(scope, SCOPES["list"])
        scores: dict[int, float] = defaultdict(float)
        for term, w in weights.items():
            for i, s in self.postings.get(term, ()):
                scores[i] += w * s
        cand = sorted(
            (
                i
                for i in scores
                if self.docs[i].kind in allowed and (section is None or self.docs[i].section == section)
            ),
            key=lambda i: -scores[i],
        )[:80]
        base = [t for t in qtoks]
        for i in cand:
            tt = self.title_tokens[i]
            if len(base) >= 2 and _contains(tt, tuple(base)):
                scores[i] *= 1.35
            elif tt and set(base) >= set(tt):
                scores[i] *= 1.2
        cand.sort(key=lambda i: -scores[i])

        hits: list[Hit] = []
        groups: dict[str, Hit] = {}
        for i in cand:
            d = self.docs[i]
            key = d.group if d.group and d.kind in ("entry", "watch", "benchmark", "code") else None
            if key and key in groups:
                ref = f"{d.ref}#{d.part}" if d.part and d.part != "claim" else d.ref
                if ref not in groups[key].also and ref != groups[key].ref:
                    groups[key].also.append(ref)
                continue
            hit = Hit(
                kind=d.kind,
                ref=d.ref,
                title=d.title if d.kind != "benchmark" or d.part == "claim" else f"{self.corpus.benchmarks[d.ref].title} ({d.title})",
                url=d.url,
                section=d.section,
                subsection=d.subsection,
                location=self._location(d),
                score=round(scores[i], 3),
                snippet=self._snippet(d, base),
                part=d.part,
            )
            hits.append(hit)
            if key:
                groups[key] = hit
            if len(hits) >= limit:
                break
        meta["took_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return hits, meta

    def _location(self, d: Doc) -> str:
        c = self.corpus
        if d.kind in ("entry", "watch"):
            return c.location(c.entries[d.ref])
        if d.kind == "subsection":
            return f"{d.section}. {c.sections[d.section].title} / {d.title}"
        if d.kind == "section":
            return f"{d.section}. {d.title}"
        if d.kind in ("benchmark", "code"):
            return f"misc/benchmarks/{d.ref}"
        if d.kind in ("rejected", "claim", "link_note", "proposal"):
            draft = c.drafts.get(d.section or -1)
            return f"{draft.path if draft else 'misc/notes/sections'} (section {d.section})"
        if d.kind == "note":
            return d.path
        return ""

    def _snippet(self, d: Doc, qtoks: list[str], width: int = 280) -> str:
        if d.kind in ("entry", "watch", "companion", "section"):
            return d.body
        if d.kind == "subsection":
            return d.body[:width]
        q = set(qtoks)
        best, best_score = "", -1
        for s in tx.sentences(d.body)[:200]:
            st = set(tx.tokens(s))
            score = len(q & st)
            if score > best_score:
                best, best_score = s, score
        if len(best) > width:
            best = best[: width - 1].rsplit(" ", 1)[0] + "…"
        return best


def _contains(seq: tuple[str, ...], sub: tuple[str, ...]) -> bool:
    n = len(sub)
    return any(seq[i : i + n] == sub for i in range(len(seq) - n + 1))
