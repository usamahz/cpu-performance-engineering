"""Layer 1: the repository parsed into records. Counts are checked against the
repository's own artefacts (badges, the changelog totals), not hard-coded, so
legitimate README edits do not break this suite."""

from __future__ import annotations

import re

from cpu_perf import grammar as g
from cpu_perf.parse_benchmarks import parse_metrics


# ----- grammar parity with misc/scripts/check_format.py ---------------------


def test_grammar_matches_linter(check_format, corpus):
    cf, root = check_format
    for name in ("HEADING", "ENTRY", "WATCH", "TOC_LINE"):
        assert getattr(g, name).pattern == getattr(cf, name).pattern, name
    for _, _, title, _ in corpus.headings:
        assert g.github_anchor(title) == cf.github_anchor(title)


def test_linter_passes_readme(check_format, corpus):
    cf, root = check_format
    errors = cf.lint(root / "README.md")
    if corpus.source == "bundled":
        # the wheel leaves out non-text files such as the banner image
        errors = [e for e in errors if "relative link target does not exist" not in e or corpus.reader.has(e.rsplit(": ", 1)[-1])]
    assert errors == []


# ----- README -----------------------------------------------------------------


def test_entry_count_matches_badge(corpus):
    linked = [e for e in corpus.entries.values() if e.url]
    assert corpus.badge_entries == len(linked)
    assert not corpus.warnings


def test_every_entry_line_is_parsed(corpus):
    text = corpus.reader.read_text("README.md").splitlines()
    for e in corpus.entries.values():
        line = text[e.line - 1]
        assert e.reason in line
        if e.url:
            assert f"[{e.title}]({e.url}) - " in line


def test_sections_and_ids(corpus):
    assert sorted(corpus.sections) == list(range(1, len(corpus.sections) + 1))
    start = corpus.sections[1]
    assert start.kind == "start_here"
    assert [corpus.entries[i].position for i in start.entry_ids] == list(range(1, len(start.entry_ids) + 1))
    for sub in corpus.subsections.values():
        assert sub.entry_ids, sub.title
    assert corpus.entries["4.3.5"].title.startswith("C2C - False Sharing")  # title contains " - "


def test_watchlist(corpus):
    watch = corpus.sections[16]
    assert watch.kind == "watchlist"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", watch.watch_checked or "")
    entries = [corpus.entries[i] for i in watch.entry_ids]
    assert all(e.kind == "watch" and e.condition for e in entries)
    unlinked = [e for e in entries if e.url is None]
    assert unlinked and unlinked[0].title.startswith("SME in a Neoverse core")


def test_reproduce_lines_resolve(corpus):
    reps = [r for s in corpus.sections.values() for r in s.reproduce] + [
        r for s in corpus.subsections.values() for r in s.reproduce
    ]
    assert reps
    assert all(r.slug in corpus.benchmarks for r in reps)
    assert corpus.badge_benchmarks == len(corpus.benchmarks)


def test_shared_urls_are_grouped(corpus):
    shared = {k: v for k, v in corpus.by_url.items() if len(v) > 1}
    assert shared
    for ids in shared.values():
        reasons = {corpus.entries[i].reason for i in ids}
        assert len(reasons) == len(ids)  # each appearance names a different mechanism
    clang = [e for e in corpus.entries.values() if e.url and "UsersManual.html#" in e.url]
    assert len({e.url for e in clang}) == len(clang)  # fragments keep these apart


def test_seven_fields(corpus):
    assert len(corpus.seven_fields) == 7
    assert corpus.seven_fields[0].startswith("CPU model")


# ----- drafts (the editorial record) -------------------------------------------


def test_record_totals_match_changelog(corpus):
    text = corpus.reader.read_text("misc/notes/changelog.md")
    m = re.search(r"Totals: (\d+) entries included, (\d+) rejected, (\d+) numbers examined", text)
    assert m
    assert len(corpus.rejected) == int(m.group(2))
    assert len(corpus.claims) == int(m.group(3))
    assert set(corpus.drafts) == set(corpus.sections)


def test_rejected_shapes(corpus):
    by_title = {r.title: r for r in corpus.rejected}
    cpp = by_title["std::memory_order at cppreference"]
    assert cpp.category == "rule" and cpp.rules == [1]
    hp = next(r for r in corpus.rejected if r.unlinked_ref and "hpl.hp.com" in r.unlinked_ref)
    assert hp.category == "rule" and 4 in hp.rules
    assert all(r.reason for r in corpus.rejected)


def test_claims(corpus):
    verdicts = {c.verdict for c in corpus.claims}
    assert {"core", "watchlist", "cut"} <= verdicts
    hoard = next(c for c in corpus.claims if c.quote and "factor of 60" in c.quote)
    assert hoard.verdict == "core"
    assert sum(1 for c in corpus.claims if c.urls) > len(corpus.claims) * 0.9


def test_record_joins_entries(corpus):
    joined = sum(1 for e in corpus.entries.values() if e.url and corpus.record_for_url(e.url)["link_notes"])
    assert joined > 100


# ----- benchmarks ---------------------------------------------------------------


def test_benchmarks(corpus):
    for b in corpus.benchmarks.values():
        assert b.number in corpus.sections
        assert len(b.machine) == 7, b.slug
        summary = corpus.reader.read_text(b.files["summary"]).strip()
        assert b.results_md == summary, b.slug
        assert b.tables and all(len(r) == len(t.header) for t in b.tables for r in t.rows)
        raw = corpus.reader.read_text(b.files["raw"])
        assert len(parse_metrics(raw)) == raw.count("\nRESULT ")
        assert b.reproduced_from
        assert b.supports and all(corpus.entries[i] for i in b.supports)


def test_rules_from_owner_brief(corpus):
    assert sorted(corpus.rules) == [1, 2, 3, 4, 5, 6, 7]
    assert "Primary sources" in corpus.rules[1]


def test_load_is_fast(corpus):
    assert corpus.load_ms < 2000
