"""Unit tests for the site generator. No network, no browser.

Tests that need the repository's data build it themselves into a temporary
directory (scripts/export_corpus.py, then the site), and the check tests
seed one defect each into a copy of that build and assert the matching
check fails. The MCP surface comes from build/mcp-surface.json when
scripts/export_mcp.py has run, as in CI; without it the MCP checks are
skipped rather than failed.

    python -m unittest discover -s misc/site/tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
ROOT = SITE.parents[1]
sys.path.insert(0, str(SITE))
sys.path.insert(0, str(ROOT / "misc" / "mcp" / "src"))

from cpu_perf_site import check  # noqa: E402
from cpu_perf_site.charts.spec import ChartError, build_chart  # noqa: E402
from cpu_perf_site.config import load_config  # noqa: E402
from cpu_perf_site.data import load_site  # noqa: E402
from cpu_perf_site.pages import Builder  # noqa: E402
from cpu_perf_site.paths import Links, slugify  # noqa: E402

COMMIT = "0" * 40


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------


class Anchors(unittest.TestCase):
    def test_slugify_is_github_anchor(self):
        """The site's ids, cpu_perf's grammar and check_format.py agree on
        every heading in the README."""
        from cpu_perf.grammar import github_anchor

        check_format = load_module(ROOT / "misc" / "scripts" / "check_format.py", "check_format")
        headings = re.findall(r"^#{1,6}\s+(.+?)\s*$", (ROOT / "README.md").read_text(encoding="utf-8"), re.M)
        self.assertGreater(len(headings), 70)
        for h in headings + ["Store buffers, ordering & `cache_line` contention", "<b>x86</b> *SIMD*: AVX-512"]:
            self.assertEqual(slugify(h), github_anchor(h), h)
            self.assertEqual(slugify(h), check_format.github_anchor(h), h)


class GitHubAnchors(unittest.TestCase):
    def test_both_heading_formats(self):
        script = load_module(SITE / "scripts" / "check_github_anchors.py", "check_github_anchors")
        new = ('<div class="markdown-heading" dir="auto"><h2 tabindex="-1" class="heading-element" dir="auto">'
               '4. Memory hierarchy</h2><a id="user-content-4-memory-hierarchy" class="anchor" '
               'aria-label="Permalink: 4. Memory hierarchy" href="#4-memory-hierarchy"><span aria-hidden="true" '
               'class="octicon octicon-link"></span></a></div>')
        old = ('<h3><a id="user-content-tlbs-page-walks-and-prefetchers" class="anchor" aria-hidden="true" '
               'href="#tlbs-page-walks-and-prefetchers"><svg></svg></a>TLBs, page walks and prefetchers</h3>')
        self.assertEqual(script.anchors_in(new + old), {"4-memory-hierarchy", "tlbs-page-walks-and-prefetchers"})
        self.assertEqual(script.anchors_in("<h2>Comment heading</h2>"), set())


class Paths(unittest.TestCase):
    def setUp(self):
        self.links = Links("https://github.com/o/r", COMMIT, {"tlbs": "/learn/memory/#tlbs"}, {"connect-it": "/mcp/quickstart/"})

    def test_readme_fragment_moves_to_its_page(self):
        self.assertEqual(self.links.rewrite("#tlbs", "README.md"), "/learn/memory/#tlbs")
        self.assertEqual(self.links.rewrite("README.md#tlbs", "CONTRIBUTING.md"), "/learn/memory/#tlbs")

    def test_documents_map_to_pages(self):
        self.assertEqual(self.links.rewrite("misc/benchmarks/04-cache-latency/README.md", "README.md"), "/benchmarks/04-cache-latency/")
        self.assertEqual(self.links.rewrite("../../README.md", "misc/benchmarks/README.md"), "/")
        self.assertEqual(self.links.rewrite("../README.md", "misc/benchmarks/README.md"),
                         f"https://github.com/o/r/blob/{COMMIT}/misc/README.md")
        self.assertEqual(self.links.rewrite("misc/mcp/README.md#connect-it", "README.md"), "/mcp/quickstart/#connect-it")
        self.assertEqual(self.links.rewrite("#connect-it", "misc/mcp/README.md"), "/mcp/quickstart/#connect-it")
        self.assertEqual(self.links.rewrite("CONTRIBUTING.md", "README.md"), "/evidence/#contributing")

    def test_everything_else_goes_to_github_at_the_commit(self):
        self.assertEqual(self.links.rewrite("misc/scripts/check_links.py", "README.md"),
                         f"https://github.com/o/r/blob/{COMMIT}/misc/scripts/check_links.py")
        self.assertEqual(self.links.rewrite("misc/notes/", "README.md"), f"https://github.com/o/r/tree/{COMMIT}/misc/notes")
        self.assertEqual(self.links.rewrite("#development", "misc/mcp/README.md"),
                         f"https://github.com/o/r/blob/{COMMIT}/misc/mcp/README.md#development")
        self.assertEqual(self.links.rewrite("https://example.org/x", "README.md"), "https://example.org/x")


class Recount(unittest.TestCase):
    def test_token_walk(self):
        text = "\n".join([
            "# T", "", "## Contents", "", "- [1. A](#1-a)", "",
            "## 1. A", "", "1. [P](https://p.example) - Why.", "2. [Q](https://q.example) - Why.", "",
            "## 2. B", "", "### Part", "", "- [R](https://r.example) - Why.", "  - [nested](https://n.example) - no.", "",
            "Reproduce it: [x](misc/benchmarks/x/README.md), what.", "",
            "## 16. Watchlist", "", "- Something with no link, pending a part.", "",
            "## What earns a place", "", "- [S](https://s.example) - not counted.",
        ])
        self.assertEqual(check.recount(text), {"sections": 3, "subsections": 1, "entries": 3, "unlinked": 1, "reproduce_lines": 1})


ROWS = [
    {"key": "line_4096_ns", "value": "0.665", "number": 0.665, "unit": "ns/load", "segment": 0, "segment_label": None, "line": 1},
    {"key": "line_8192_ns", "value": "0.7", "number": 0.7, "unit": "ns/load", "segment": 0, "segment_label": None, "line": 2},
    {"key": "page_8192_ns", "value": "0", "number": 0.0, "unit": "ns/load", "segment": 0, "segment_label": None, "line": 3},
    {"key": "clock", "value": "4.5", "number": 4.5, "unit": "GHz", "segment": 1, "segment_label": None, "line": 4},
    {"key": "clock", "value": "4.4", "number": 4.4, "unit": "GHz", "segment": 2, "segment_label": None, "line": 5},
]


def spec(**over):
    s = {"id": "c", "title": "T", "type": "line", "x": {"from": "b", "scale": "log2"}, "y": {"unit": "ns/load"},
         "series": [{"name": "line", "match": r"^line_(?P<b>\d+)_ns$"}]}
    s.update(over)
    return s


class ChartSpecs(unittest.TestCase):
    def test_a_valid_spec(self):
        chart = build_chart(spec(), "04", ROWS, {})
        self.assertEqual([(p.x, p.y) for p in chart.points], [(4096.0, 0.665), (8192.0, 0.7)])

    def assertFails(self, s, words):
        with self.assertRaises(ChartError) as cm:
            build_chart(s, "04", ROWS, {})
        self.assertIn(words, str(cm.exception))

    def test_series_that_matches_nothing(self):
        self.assertFails(spec(series=[{"name": "x", "match": r"^nope_(?P<b>\d+)$"}]), "matches no RESULT line")

    def test_unit_disagrees_with_the_axis(self):
        self.assertFails(spec(y={"unit": "cycles"}), "the axis is in 'cycles'")

    def test_value_on_a_log_axis(self):
        self.assertFails(spec(y={"unit": "ns/load", "scale": "log10"},
                              series=[{"name": "p", "match": r"^page_(?P<b>\d+)_ns$"}]), "cannot sit on a log axis")

    def test_key_repeated_across_segments(self):
        self.assertFails(spec(y={"unit": "GHz"}, x={"from": "k", "scale": "category"},
                              series=[{"name": "c", "match": r"^(?P<k>clock)$"}]), "repeats across segments")

    def test_category_missing_from_the_order(self):
        self.assertFails(spec(type="bar", x={"from": "b", "order": ["4096"]}), "not in x.order")

    def test_five_series(self):
        self.assertFails(spec(series=[{"name": str(i), "match": r"^line_(?P<b>\d+)_ns$"} for i in range(5)]), "has 4 slots")

    def test_reference_from_a_missing_header_line(self):
        self.assertFails(spec(refs=[{"axis": "x", "header": "P-core L1d", "pattern": r"(\d+)"}]), "raw.txt header has no line")


class CopyLint(unittest.TestCase):
    def test_rules_fire(self):
        lint = load_module(SITE / "scripts" / "check_copy.py", "check_copy")
        bad = "Optimize your code! A comprehensive guide — coming soon."
        hits = {why for rx, why in lint.RULES if rx.search(bad)}
        self.assertEqual(hits, {"addresses the reader", "exclamation mark", "adjective of praise", "em dash",
                                "placeholder text", "American spelling"})
        self.assertFalse([why for rx, why in lint.RULES if rx.search("Quantization, optimisation and colour.")])

    def test_site_copy_is_clean(self):
        lint = load_module(SITE / "scripts" / "check_copy.py", "check_copy")
        self.assertEqual(lint.lint(), [])


class ClientTabs(unittest.TestCase):
    """A client the README sets up through another ("configured as below")
    shows that setup in its own tab, until its section has a command."""

    def view(self, chatgpt: str):
        from cpu_perf_site.mcp import McpView
        readme = ("# cpu-perf\n\n## Connect it\n\n### ChatGPT\n\n" + chatgpt
                  + "\n\n### Codex\n\n    codex mcp add cpu-perf -- uvx cpu-perf\n")
        return McpView(readme, None, None)

    def test_borrows_the_setup_it_points_to(self):
        self.assertEqual(self.view("Runs local servers through its Codex host, configured as below.").setup_via("chatgpt").anchor, "codex")

    def test_its_own_command_wins(self):
        self.assertIsNone(self.view("Through Codex:\n\n    chatgpt mcp add cpu-perf").setup_via("chatgpt"))
        self.assertIsNone(self.view("Through Codex:\n\n```toml\n[x]\n```").setup_via("chatgpt"))

    def test_only_mapped_clients_borrow(self):
        self.assertIsNone(self.view("Configured as below.").setup_via("codex"))


# --------------------------------------------------------------------------
# Against a real build of this checkout.


class Built(unittest.TestCase):
    tmp: Path
    build: Path
    dist: Path

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="cpu-perf-site-test-"))
        cls.build = cls.tmp / "build"
        subprocess.run([sys.executable, str(SITE / "scripts" / "export_corpus.py"), "--out", str(cls.build)],
                       check=True, capture_output=True)
        surface = Path(os.environ.get("SITE_MCP_SURFACE", SITE / "build" / "mcp-surface.json"))
        if surface.is_file():
            shutil.copy(surface, cls.build / "mcp-surface.json")
        cls.dist = cls.tmp / "dist"
        Builder(load_site(cls.build, load_config()), cls.dist).build()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_checks(self, dist: Path) -> check.Report:
        check.run_checks(load_site(self.build, load_config()), dist, quiet=True)
        return check.run_checks.last_report

    def failures(self, report: check.Report) -> set[str]:
        return {e.split(":", 1)[0] for e in report.errors}

    def test_clean_build_passes(self):
        report = self.run_checks(self.dist)
        allowed = set() if (self.build / "mcp-surface.json").is_file() else {"record and MCP"}
        self.assertEqual(self.failures(report) - allowed, set(), report.errors)

    def test_build_is_deterministic(self):
        again = self.tmp / "again"
        Builder(load_site(self.build, load_config()), again).build()
        diff = subprocess.run(["diff", "-rq", str(self.dist), str(again)], capture_output=True, text=True)
        self.assertEqual(diff.stdout, "")

    def seeded(self, name: str, mutate) -> set[str]:
        """Copy the build, apply one defect, and return the checks that fail."""
        dist = self.tmp / f"seed-{name}"
        shutil.copytree(self.dist, dist)
        mutate(dist)
        return self.failures(self.run_checks(dist))

    @staticmethod
    def edit(path: Path, old: str, new: str, count: int = 1) -> None:
        text = path.read_text(encoding="utf-8")
        assert old in text, (path, old[:60])
        path.write_text(text.replace(old, new, count), encoding="utf-8")

    def test_dropped_entry(self):
        def drop(dist):
            page = next((dist / "learn").glob("*/index.html"))
            text = page.read_text(encoding="utf-8")
            text = re.sub(r'<li id="e-[^"]+" data-entry="[^"]+".*?</li>', "", text, count=1, flags=re.S)
            page.write_text(text, encoding="utf-8")
        self.assertIn("entry parity", self.seeded("entry", drop))

    def test_lost_heading_anchor(self):
        site = load_site(self.build, load_config())
        sub = next(s for sec in site.sections for s in sec.subsections)
        sec = site.section_by_number[sub.section]
        self.assertIn("README anchors", self.seeded(
            "anchor", lambda d: self.edit(d / sec.url.strip("/") / "index.html", f'id="{sub.anchor}"', 'id="moved"')))

    def test_broken_internal_link(self):
        self.assertIn("internal links", self.seeded(
            "link", lambda d: self.edit(d / "index.html", 'href="/learn/"', 'href="/lern/"')))

    def test_inline_style_and_third_party_script(self):
        def inject(d):
            self.edit(d / "index.html", "</main>", '<p style="color:red">x</p><script src="https://cdn.example/x.js"></script></main>')
        self.assertIn("security and budgets", self.seeded("style", inject))

    def test_chart_loses_a_table_row(self):
        def drop(d):
            page = d / "benchmarks" / "04-cache-latency" / "index.html"
            text = page.read_text(encoding="utf-8")
            text = re.sub(r'(<table class="data">.*?<tbody>)<tr>.*?</tr>', r"\1", text, count=1, flags=re.S)
            page.write_text(text, encoding="utf-8")
        self.assertIn("benchmarks", self.seeded("chart", drop))

    def test_missing_twin(self):
        site = load_site(self.build, load_config())
        self.assertIn("twins and data files", self.seeded(
            "twin", lambda d: (d / site.sections[0].twin.lstrip("/")).unlink()))

    def test_twin_drifts_from_the_readme(self):
        site = load_site(self.build, load_config())
        twin = site.sections[1].twin.lstrip("/")
        self.assertIn("twins and data files", self.seeded(
            "drift", lambda d: (d / twin).write_text((d / twin).read_text(encoding="utf-8") + "\n- an extra line\n", encoding="utf-8")))

    def test_record_item_missing(self):
        site = load_site(self.build, load_config())
        rid = site.claims[0].id
        self.assertIn("record and MCP", self.seeded(
            "record", lambda d: self.edit(d / "evidence" / "record" / "index.html", f'id="{rid}"', 'id="gone"')))


if __name__ == "__main__":
    unittest.main()
