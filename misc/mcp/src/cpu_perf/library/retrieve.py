"""Hybrid passage search over the library.

Three ranked lists are fused with reciprocal rank fusion: the reader's own
terms (FTS5 BM25), their expansions (synonym phrases and stems, at a lower
weight) and vector similarity. On top of that: the sources the list links for
the topic are tried first and nudged up, spreadsheet rows give way to prose
unless they name the exact identifier asked about, and no source takes more
than its share of the answer."""

from __future__ import annotations

import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from .. import grammar as g
from .. import text as tx
from .extract import clean_text
from .store import STEM_PREFIX, Store

RRF_K = 60
LIST_BOOST = 1.25
EXPANSION_WEIGHT = 0.4
TABLE_PRIOR = 0.6
COMMON_SHARE = 0.25  # a term in more of the passages than this is dropped when rarer ones remain
MAX_TERMS = 24  # long pasted questions keep their rarest terms
PREFER_FLOOR = 0.5  # a listed source's best passage needs this share of the best keyword score
SEMANTIC_TRUST = 5  # a passage among the top few by meaning passes the term floor on its own


@dataclass
class Passage:
    chunk_id: int
    source_url: str
    doc_url: str | None
    title: str
    kind: str | None
    page: int | None
    heading: str | None
    text: str
    score: float
    entry_ids: list[str] = field(default_factory=list)
    sections: list[int] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)  # keyword, expansion, semantic, listed-for-topic, listed-first, abstract

    def __post_init__(self) -> None:
        self.text = clean_text(self.text)  # libraries built before pdf extraction 2 still hold U+FFFE

    @property
    def cite_url(self) -> str:
        """What a reader should open: the listed URL, or the PDF behind it at the cited page."""
        url = self.doc_url or self.source_url
        if self.page and (self.kind == "pdf" or url.lower().endswith(".pdf")):
            return f"{url}#page={self.page}"
        return self.source_url


@dataclass
class QueryPlan:
    primary: list[str]
    expansions: list[tuple[str, ...]]
    stems: list[str]
    identifiers: list[str]  # compound names as typed, lower case: cycle_activity.stalls_l3_miss
    dropped: list[str] = field(default_factory=list)
    concepts: list[list[tuple[str, ...]]] = field(default_factory=list)
    domain: list[list[tuple[str, ...]]] = field(default_factory=list)  # the synonym-group concepts

    def primary_expr(self) -> str:
        return " OR ".join(f'"{t}"' for t in self.primary)

    def expansion_expr(self) -> str:
        parts = [f'"{" ".join(p)}"' for p in self.expansions] + [f'"{s}"' for s in self.stems]
        return " OR ".join(dict.fromkeys(parts))


def _synonym_table() -> dict[tuple[str, ...], list[tuple[str, ...]]]:
    table: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for phrase, expansions in tx.synonym_phrases():
        for e in expansions:
            if e not in table.setdefault(phrase, []):
                table[phrase].append(e)
    return table


IDENT = re.compile(r"[a-z0-9]+(?:[._\-/][a-z0-9]+)+")
ABSTRACT = re.compile(r"\b(ABSTRACT|Abstract)\b")
ABSTRACT_END = re.compile(
    r"\b(keywords|index terms|ccs concepts|categories and subject descriptors|(1|I)\.?\s+introduction)\b", re.I
)
ABSTRACT_CHARS = 1600


def _is_table(row) -> bool:
    return row["kind"] == "xlsx" or row["text"].count(" | ") > 12


def _has(alternatives: list[tuple[str, ...]], norm: set[str], seq: str) -> bool:
    """A word (or its stem) anywhere; a phrase only as adjacent words."""
    for alt in alternatives:
        if len(alt) == 1:
            if alt[0] in norm or (STEM_PREFIX + tx.stem(alt[0])) in norm:
                return True
        elif f" {' '.join(alt)} " in seq:
            return True
    return False


def _passes(plan: "QueryPlan", norm_text: str) -> bool:
    """Does a passage carry the question rather than a stray word of it?

    Concepts are the question's words, with a phrase and its synonyms
    counting as one (a stem match counts). When the question names a domain
    concept (false sharing, top-down, coordinated omission), the passage
    must carry it; and it must carry enough of the rest."""
    n = len(plan.concepts)
    if not n:
        return True
    norm = set(norm_text.split())
    seq = f" {norm_text} "
    covered = [c for c in plan.concepts if _has(c, norm, seq)]
    if plan.domain and not any(c in covered for c in plan.domain):
        return False
    floor = 1 if n <= 2 else 2
    return len(covered) >= floor


def _passage(row, score: float, signals) -> Passage:
    return Passage(
        chunk_id=row["id"],
        source_url=row["url"],
        doc_url=row["doc_url"],
        title=row["title"] or row["url"],
        kind=row["kind"],
        page=row["page"],
        heading=row["heading"],
        text=row["text"],
        score=round(score * 1000, 3),
        entry_ids=json.loads(row["entry_ids"] or "[]"),
        sections=json.loads(row["sections"] or "[]"),
        signals=sorted(signals),
    )


def _drop_overlap(prev: str, text: str) -> str:
    """Neighbouring passages repeat up to the chunker's overlap; keep one copy."""
    for k in range(min(300, len(text)), 20, -1):
        if prev.endswith(text[:k]):
            return text[k:].lstrip()
    return text


class Retriever:
    def __init__(self, store: Store, embedder_getter=lambda: None, expander=None):
        self.store = store
        self.embedder_getter = embedder_getter
        self.expander = expander  # kept for callers; the library uses the full synonym table
        self.synonyms = _synonym_table()
        self._sources: tuple[int, dict[int, object], dict[str, object]] | None = None
        self._sources_guard = threading.Lock()
        self._embeddings: OrderedDict = OrderedDict()  # query embeddings, recent first out

    # ----- the query --------------------------------------------------------------

    def plan(self, query: str) -> QueryPlan:
        qtoks = tx.tokens(query)
        primary = list(dict.fromkeys(qtoks))
        dropped: list[str] = []
        if len(primary) > 1:
            df = self.store.term_df(primary)
            n = max(1, self.store.chunk_count())
            present = [t for t in primary if df.get(t, 0) > 0]
            rare = [t for t in present if df[t] / n <= COMMON_SHARE]
            if rare and len(rare) < len(present):
                dropped = [t for t in present if t not in rare]
                primary = [t for t in primary if t not in dropped]
            if len(primary) > MAX_TERMS:
                keep = set(sorted(primary, key=lambda t: df.get(t, 0))[:MAX_TERMS])
                dropped += [t for t in primary if t not in keep]
                primary = [t for t in primary if t in keep]
        expansions: list[tuple[str, ...]] = []
        concepts: list[list[tuple[str, ...]]] = []
        in_phrase: set[str] = set()
        for size in (3, 2, 1):
            for i in range(len(qtoks) - size + 1):
                phrase = tuple(qtoks[i : i + size])
                exps = self.synonyms.get(phrase, [])
                for exp in exps:
                    if exp not in expansions and not (len(exp) == 1 and exp[0] in primary):
                        expansions.append(exp)
                if exps and not set(phrase) & in_phrase:
                    concepts.append([phrase, *exps])
                    in_phrase.update(phrase)
        for t in primary:
            if t not in in_phrase and len(t) >= 3:
                concepts.append([(t,)])
        stems = []
        for t in primary:
            if t.isalpha():
                stem = STEM_PREFIX + tx.stem(t)
                if stem not in stems:
                    stems.append(stem)
        normal = tx._normalise(query)
        idents = list(dict.fromkeys(m.group(0) for m in IDENT.finditer(normal) if re.search(r"[._]", m.group(0))))
        domain = [c for c in concepts if len(c) > 1]
        return QueryPlan(primary, expansions[:32], stems[:MAX_TERMS], idents, dropped, concepts, domain)

    def _embed(self, emb, query: str):
        key = (getattr(emb, "name", ""), query)
        with self._sources_guard:
            hit = self._embeddings.get(key)
            if hit is not None:
                self._embeddings.move_to_end(key)
                return hit
        vec = emb.encode([query])[0]
        with self._sources_guard:
            self._embeddings[key] = vec
            while len(self._embeddings) > 512:
                self._embeddings.popitem(last=False)
        return vec

    # ----- source metadata, cached per library generation ---------------------------

    def _source_maps(self):
        gen = self.store.generation()
        with self._sources_guard:
            if self._sources is None or self._sources[0] != gen:
                rows = self.store.sources()
                self._sources = (gen, {r.id: r for r in rows}, {r.url: r for r in rows})
            return self._sources[1], self._sources[2]

    def source_row(self, url: str):
        _, by_url = self._source_maps()
        return by_url.get(url.split("#", 1)[0])

    def lead_passage(self, url: str) -> Passage | None:
        """A paper's abstract, where it states what it shows: from the word Abstract on its first
        pages to the keywords or the introduction, joined across passages when it runs over.
        None for a PDF without one (a manual, a datasheet) and for anything that is not a PDF."""
        row = self.source_row(url)
        if row is None or row.kind != "pdf" or not row.chunks:
            return None
        first = [r for r in self.store.source_chunks(row.id, limit=4) if (r["page"] or 1) <= 2]
        start = next((i for i, r in enumerate(first) if ABSTRACT.search(r["text"])), None)
        if start is None:
            return None
        text = clean_text(first[start]["text"])
        text = text[ABSTRACT.search(text).end() :].lstrip(" :.-—\n")
        for r in first[start + 1 :]:
            if ABSTRACT_END.search(text) or len(text) >= ABSTRACT_CHARS:
                break
            text = f"{text} {_drop_overlap(text, clean_text(r['text']))}"
        end = ABSTRACT_END.search(text)
        text = (text[: end.start()] if end else text).strip()
        if len(text) > ABSTRACT_CHARS:
            cut = text.rfind(". ", 0, ABSTRACT_CHARS)
            text = text[: cut + 1] if cut > ABSTRACT_CHARS // 2 else text[:ABSTRACT_CHARS]
        if len(text) < 200:
            return None
        full = self.store.chunk_rows([first[start]["id"]]).get(first[start]["id"])
        if full is None:
            return None
        p = _passage(full, 0.0, {"abstract"})
        p.text, p.heading = text, "Abstract"
        return p

    # ----- search ----------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        boost_urls: set[str] | None = None,
        sections: set[int] | None = None,
        source_url: str | None = None,
        per_source: int = 2,
        candidates: int = 60,
        prefer_urls: list[str] | None = None,
        listed_only: bool = False,
    ) -> tuple[list[Passage], dict]:
        t0 = time.perf_counter()
        plan = self.plan(query)
        meta: dict = {"keyword": 0, "semantic": 0, "dropped_terms": plan.dropped, "unfetched": []}
        by_id, by_url = self._source_maps()

        span = None
        source_ids = None
        if source_url:
            row = by_url.get(source_url.split("#", 1)[0])
            span = self.store.chunk_span(row.id) if row else None
            if span is None:
                meta["took_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                return [], meta
            candidates = max(candidates, limit * 4)
        elif sections:
            source_ids = [r.id for r in by_id.values() if set(r.sections) & sections]

        ranks: dict[int, float] = {}
        signals: dict[int, set[str]] = {}

        semantic_rank: dict[int, int] = {}

        def fuse(hits, weight: float, label: str) -> None:
            for rank, (cid, _score) in enumerate(hits):
                ranks[cid] = ranks.get(cid, 0.0) + weight / (RRF_K + rank + 1)
                signals.setdefault(cid, set()).add(label)
                if label == "semantic":
                    semantic_rank[cid] = rank

        primary_hits = self.store.fts_query(plan.primary_expr(), limit=candidates, span=span, source_ids=source_ids)
        fuse(primary_hits, 1.0, "keyword")
        meta["keyword"] = len(primary_hits)
        best_keyword = primary_hits[0][1] if primary_hits else 0.0
        fuse(
            self.store.fts_query(plan.expansion_expr(), limit=candidates, span=span, source_ids=source_ids),
            EXPANSION_WEIGHT,
            "expansion",
        )

        emb = self.embedder_getter()
        if emb is not None:
            mat = self.store.vector_matrix()
            if mat is not None:
                import numpy as np

                ids, m = mat
                q = self._embed(emb, query)
                if q.shape[0] == m.shape[1]:
                    if span is not None:
                        lo, hi = np.searchsorted(ids, span[0]), np.searchsorted(ids, span[1], side="right")
                        ids, m = ids[lo:hi], m[lo:hi]
                    if len(ids):
                        sims = self.store.similarities(m, q)
                        k = min(candidates if source_ids is None else candidates * 4, len(sims))
                        top = np.argpartition(-sims, k - 1)[:k]
                        top = top[np.argsort(-sims[top])]
                        fuse([(int(ids[i]), 0.0) for i in top], 1.0, "semantic")
                        meta["semantic"] = int(k)

        # the sources the list itself chose for this topic go first, when they answer
        preferred: list[int] = []
        if prefer_urls and not source_url:
            for url in prefer_urls:
                row = by_url.get(url.split("#", 1)[0])
                span_u = self.store.chunk_span(row.id) if row else None
                if span_u is None:
                    meta["unfetched"].append(url)
                    continue
                hits = self.store.fts_query(plan.primary_expr(), limit=1, span=span_u)
                if hits and hits[0][1] >= PREFER_FLOOR * best_keyword:
                    preferred.append(hits[0][0])

        rows = self.store.chunk_rows(list(dict.fromkeys(preferred + list(ranks))))
        boost_keys = {g.url_key(u, keep_fragment=False) for u in (boost_urls or set())}
        # a passage must carry the question, not one stray word of it
        check = not source_url
        meta["below_floor"] = 0
        scored: list[tuple[float, int]] = []
        for cid, base in ranks.items():
            row = rows.get(cid)
            if row is None or cid in preferred:
                continue
            exact = any(i in row["text"].casefold() for i in plan.identifiers)
            if check and not exact and semantic_rank.get(cid, SEMANTIC_TRUST) >= SEMANTIC_TRUST:
                if not _passes(plan, row["norm"] or ""):
                    meta["below_floor"] += 1
                    continue
            if source_url and span and not (span[0] <= cid <= span[1]):
                continue
            secs = json.loads(row["sections"] or "[]")
            if sections and not (set(secs) & sections):
                continue
            if listed_only and not json.loads(row["entry_ids"] or "[]"):
                continue
            score = base
            if _is_table(row) and not exact:
                score *= TABLE_PRIOR
            if boost_keys and g.url_key(row["url"], keep_fragment=False) in boost_keys:
                score *= LIST_BOOST
                signals.setdefault(cid, set()).add("listed-for-topic")
            scored.append((score, cid))
        scored.sort(reverse=True)

        out: list[Passage] = []
        per: dict[str, int] = {}

        def take(cid: int, score: float, extra: str | None = None) -> None:
            row = rows[cid]
            per[row["url"]] = per.get(row["url"], 0) + 1
            sig = set(signals.get(cid, ()))
            if extra:
                sig.add(extra)
            out.append(_passage(row, score, sig))

        for cid in preferred:
            if cid in rows and len(out) < limit:
                take(cid, ranks.get(cid, 0.0), "listed-first")
        for score, cid in scored:
            if len(out) >= limit:
                break
            if per.get(rows[cid]["url"], 0) >= per_source:
                continue
            take(cid, score)
        meta["took_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        meta["semantic_enabled"] = emb is not None
        return out, meta
