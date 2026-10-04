"""Browser tests of a built site: every page type at desktop and phone
widths with an accessibility scan, the same pages with JavaScript off, and
each script the site ships (filters, progress, tabs, copy, search, chart
tooltips, README anchor redirects).

Needs a built dist/ (SITE_DIST, default misc/site/dist) and the e2e extra:

    pip install -e "misc/site[e2e]"
    python -m unittest discover -s misc/site/tests/e2e

E2E_CHANNEL=chrome uses the system Chrome, as CI does. A failing test saves
a screenshot under misc/site/test-results/.
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import json
import os
import threading
import unittest
from pathlib import Path

from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import expect, sync_playwright

SITE = Path(__file__).resolve().parents[2]
DIST = Path(os.environ.get("SITE_DIST", SITE / "dist"))
RESULTS = SITE / "test-results"
SERIOUS = {"serious", "critical"}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Smoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (DIST / "index.html").is_file():
            raise unittest.SkipTest(f"no built site at {DIST}")
        handler = functools.partial(Quiet, directory=str(DIST))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel=os.environ.get("E2E_CHANNEL") or None)
        chapters = sorted(p.parent.name for p in (DIST / "learn").glob("*/index.html") if p.parent.name != "all")
        cls.chapter = f"/learn/{chapters[0]}/"
        cls.anchors = json.loads((DIST / "anchors.json").read_text(encoding="utf-8"))
        cls.axe = Axe()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()

    def setUp(self):
        self.contexts = []

    def tearDown(self):
        for ctx in self.contexts:
            ctx.close()

    def page(self, width=1280, js=True, **kw):
        ctx = self.browser.new_context(viewport={"width": width, "height": 900}, java_script_enabled=js, **kw)
        self.contexts.append(ctx)
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
        return page

    @contextlib.contextmanager
    def shot(self, page, name):
        try:
            yield
        except Exception:
            RESULTS.mkdir(exist_ok=True)
            page.screenshot(path=str(RESULTS / f"{name}.png"), full_page=True)
            raise

    @property
    def pages(self):
        return ["/", "/learn/", self.chapter, "/learn/all/", "/watchlist/", "/benchmarks/",
                "/benchmarks/04-cache-latency/", "/benchmarks/06-roofline/", "/evidence/", "/evidence/record/",
                "/mcp/", "/mcp/quickstart/", "/mcp/tools/", "/mcp/resources/", "/mcp/workflows/", "/mcp/security/",
                "/search/?q=roofline", "/404.html"]

    def test_every_page_type(self):
        """No script or console errors at either width, no horizontal page
        scroll on a phone, and no serious or critical axe findings."""
        for width in (1280, 390):
            page = self.page(width)
            for path in self.pages:
                with self.subTest(path=path, width=width), self.shot(page, f"page{path.replace('/', '_')}{width}"):
                    page.errors.clear()
                    page.goto(self.base + path, wait_until="networkidle")
                    self.assertEqual(page.errors, [])
                    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    self.assertLessEqual(overflow, 0, "the page scrolls sideways")
                    if width == 1280 or path in ("/", self.chapter, "/benchmarks/04-cache-latency/", "/mcp/quickstart/"):
                        found = [v for v in self.axe.run(page).response["violations"] if v.get("impact") in SERIOUS]
                        self.assertEqual([f"{v['id']}: {v['help']}" for v in found], [])

    def test_dark_scheme(self):
        """The dark palette is its own set of tokens, so it gets its own scan."""
        page = self.page(color_scheme="dark")
        for path in ("/", self.chapter, "/benchmarks/06-roofline/", "/evidence/record/link-notes/", "/mcp/"):
            with self.subTest(path=path), self.shot(page, f"dark{path.replace('/', '_')}"):
                page.goto(self.base + path, wait_until="networkidle")
                found = [v for v in self.axe.run(page).response["violations"] if v.get("impact") in SERIOUS]
                self.assertEqual([f"{v['id']}: {v['help']}" for v in found], [])

    def test_without_javascript(self):
        page = self.page(js=False)
        page.goto(self.base + self.chapter)
        with self.shot(page, "nojs-chapter"):
            self.assertGreater(page.locator("li[data-entry]").count(), 0)
            expect(page.locator("[data-filter-for]")).to_be_hidden()
            expect(page.locator("li[data-entry]").first).to_be_visible()
        page.goto(self.base + "/benchmarks/04-cache-latency/")
        with self.shot(page, "nojs-bench"):
            expect(page.locator("figure.figure svg.chart").first).to_be_visible()
        page.goto(self.base + "/mcp/quickstart/")
        with self.shot(page, "nojs-tabs"):
            for panel in ("#claude", "#codex", "#cursor-and-vs-code"):
                expect(page.locator(panel)).to_be_visible()

    def test_chapter_filter_and_progress(self):
        page = self.page()
        page.goto(self.base + self.chapter, wait_until="networkidle")
        with self.shot(page, "filter-progress"):
            entries = page.locator("li[data-entry]")
            total = entries.count()
            title = entries.first.locator(".entry-title").inner_text()
            page.fill("[data-filter-text]", title)
            expect(page.locator("li[data-entry]:visible")).not_to_have_count(total)
            page.fill("[data-filter-text]", "")
            expect(page.locator("li[data-entry]:visible")).to_have_count(total)
            entries.first.locator(".entry-read input").check()
            stored = page.evaluate("JSON.parse(localStorage.getItem('cpe:progress:v1'))")
            self.assertEqual(len(stored), 1)
            page.goto(self.base + "/learn/", wait_until="networkidle")
            expect(page.locator("[data-meter]:visible")).to_have_count(1)

    def test_benchmark_and_record_filters(self):
        page = self.page()
        page.goto(self.base + "/benchmarks/", wait_until="networkidle")
        with self.shot(page, "bench-filter"):
            want = page.locator('tr[data-item][data-threads="multi-threaded"]').count()
            page.select_option('select[data-filter-field="threads"]', "multi-threaded")
            expect(page.locator("tr[data-item]:visible")).to_have_count(want)
        page.goto(self.base + "/evidence/record/", wait_until="networkidle")
        with self.shot(page, "record-filter"):
            want = page.locator('li[data-item][data-verdict="core"]').count()
            page.select_option('select[data-filter-field="verdict"]', "core")
            expect(page.locator("li[data-item]:visible")).to_have_count(want)

    def test_client_tabs(self):
        page = self.page()
        page.goto(self.base + "/mcp/quickstart/", wait_until="networkidle")
        with self.shot(page, "tabs"):
            expect(page.locator("[role=tablist]")).to_be_visible()
            page.click("#tab-codex")
            expect(page.locator("#codex")).to_be_visible()
            expect(page.locator("#claude")).to_be_hidden()
            self.assertTrue(page.url.endswith("#codex"))
        page.goto(self.base + "/mcp/quickstart/#cursor-and-vs-code", wait_until="networkidle")
        with self.shot(page, "tabs-hash"):
            expect(page.locator("#cursor-and-vs-code")).to_be_visible()
            expect(page.locator("#claude")).to_be_hidden()

    def test_copy_button(self):
        page = self.page(permissions=["clipboard-read", "clipboard-write"])
        page.goto(self.base + "/mcp/", wait_until="networkidle")
        with self.shot(page, "copy"):
            button = page.locator('[data-copy="uvx cpu-perf"]').first
            button.click()
            self.assertEqual(page.evaluate("navigator.clipboard.readText()"), "uvx cpu-perf")

    def test_search(self):
        page = self.page()
        page.goto(self.base + "/search/?q=false%20sharing", wait_until="networkidle")
        with self.shot(page, "search"):
            results = page.locator("[data-results] li")
            expect(results.first).to_be_visible()
            hrefs = [a.get_attribute("href") for a in page.locator("[data-results] a.t").all()]
            self.assertIn("/benchmarks/09-false-sharing/", hrefs)

    def test_chart_keyboard_tooltip(self):
        page = self.page()
        page.goto(self.base + "/benchmarks/04-cache-latency/", wait_until="networkidle")
        with self.shot(page, "tooltip"):
            mark = page.locator(".chart .mark[tabindex='0']").locator("visible=true").first
            mark.focus()
            tip = page.locator(".tooltip")
            expect(tip).to_be_visible()
            first = tip.inner_text()
            self.assertIn("ns/load", first)
            page.keyboard.press("ArrowRight")
            expect(tip).not_to_have_text(first)

    def test_readme_anchor_lands_on_its_page(self):
        anchor, dest = next((a, d) for a, d in sorted(self.anchors.items()) if d.startswith("/learn/") and "#" in d)
        page = self.page()
        page.goto(f"{self.base}/#{anchor}")
        with self.shot(page, "anchor"):
            page.wait_for_url(f"{self.base}{dest}")
            expect(page.locator(f'[id="{anchor}"]')).to_be_visible()


if __name__ == "__main__":
    unittest.main()
