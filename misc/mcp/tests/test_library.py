"""Layer 2, the source library, against a local fixture site (no internet)."""

from __future__ import annotations

import socket
import time
from types import SimpleNamespace

import pytest

from cpu_perf.corpus import CrawlTarget
from cpu_perf.library.chunk import chunk
from cpu_perf.library.crawler import CrawlLock, Crawler
from cpu_perf.library.embed import HashingEmbedder, get_embedder
from cpu_perf.library.extract import extract_html, extract_pdf, extract_text, extract_xlsx
from cpu_perf.library.resolve import plan_for, primary_document_links
from cpu_perf.library.retrieve import Retriever
from cpu_perf.library.store import Store
from cpu_perf.net import Fetcher, _ip_is_public

from fixture_site import ARTICLE, LANDING, PAPER_PAGES, Site, make_pdf, make_xlsx


@pytest.fixture()
def site():
    with Site() as s:
        yield s


def local_fetcher(**kw):
    return Fetcher(allow_private=True, per_host_interval=0, **kw)


def target(url, ids=("9.9.1",), sections=(9,), title="t"):
    return CrawlTarget(url=url, entry_ids=list(ids), sections=list(sections), title=title)


# ----- resolver ------------------------------------------------------------------------


def test_plans_for_real_url_shapes():
    assert plan_for("https://arxiv.org/abs/1902.08318").fetch == ["https://arxiv.org/pdf/1902.08318"]
    p = plan_for("https://github.com/google/highway")
    assert p.kind == "github_readme" and p.fetch[0] == "https://raw.githubusercontent.com/google/highway/HEAD/README.md"
    p = plan_for("https://github.com/intel/perfmon/blob/main/TMA_Metrics-full.xlsx")
    assert p.kind == "xlsx" and p.fetch == ["https://raw.githubusercontent.com/intel/perfmon/main/TMA_Metrics-full.xlsx"]
    p = plan_for("https://github.com/llvm/llvm-project/tree/main/bolt")
    assert p.fetch[0] == "https://raw.githubusercontent.com/llvm/llvm-project/main/bolt/README.md"
    p = plan_for("https://github.com/ggml-org/llama.cpp/pull/1684")
    assert p.kind == "github_pr" and p.fetch[0].endswith("/repos/ggml-org/llama.cpp/pulls/1684")
    assert plan_for("https://www.youtube.com/watch?v=bSkpMdDe4g4").kind == "video"
    assert plan_for("https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-443-15406-5").kind == "book"
    assert plan_for("https://www.fftw.org/~athena/papers/cilk5.ps.gz").kind == "unsupported"
    assert plan_for("https://docs.amd.com/v/u/en-US/58455_1.00").kind == "landing"
    assert plan_for("https://www.akkadia.org/drepper/cpumemory.pdf").kind == "pdf"


def test_primary_document_links():
    links = primary_document_links("https://www.intel.com/content-details/1/x.html", LANDING)
    assert links == ["https://www.intel.com/docs/manual.pdf"]
    html = '<a href="https://evil.example/x.pdf">PDF</a><a href="https://cdrdv2.intel.com/v1/dl/getContent/671488">Download</a>'
    assert primary_document_links("https://www.intel.com/a.html", html)[0].startswith("https://cdrdv2.intel.com/")


def test_all_corpus_targets_have_plans(corpus):
    kinds = {plan_for(t.url).kind for t in corpus.targets}
    assert {"pdf", "arxiv", "github_readme", "html"} <= kinds


# ----- network guards ----------------------------------------------------------------------


def test_address_checks():
    for ip in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "64:ff9b::a9fe:a9fe", "0.0.0.0", "fd00:ec2::254", "100.100.100.200"):
        assert not _ip_is_public(ip), ip
    assert _ip_is_public("151.101.3.42")


def test_refusals():
    f = Fetcher(per_host_interval=0)
    for url in ("file:///etc/passwd", "ftp://example.com/x", "http://localhost/", "http://169.254.169.254/latest", "http://[::1]/", "https://example.com:8443/", "http://user:pw@example.com/"):
        assert f.fetch(url).status == "refused", url


def test_redirect_to_private_address_is_refused(site):
    def resolver(host, port, type=0):
        if host == "public.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    f = Fetcher(per_host_interval=0, resolver=resolver)
    # check_url is what every hop goes through
    assert f.check_url("http://public.test/")[3] == ["93.184.216.34"]
    from cpu_perf.net import Refused

    with pytest.raises(Refused):
        f.check_url("http://internal.test/")


def test_fetch_classification(site):
    f = local_fetcher()
    assert f.fetch(site.url("/article.html")).status == "ok"
    moved = f.fetch(site.url("/moved"))
    assert moved.status == "ok" and moved.redirects and moved.final_url.endswith("/article.html")
    assert f.fetch(site.url("/forbidden")).status == "blocked"
    assert f.fetch(site.url("/nowhere")).status == "dead"
    wall = f.fetch(site.url("/wall.html"))
    assert wall.status == "blocked" and "bot check" in wall.detail
    assert f.fetch(site.url("/papers/false-sharing.pdf"), max_bytes=100).status == "too_large"
    gz = f.fetch(site.url("/gz.html"))
    assert gz.status == "ok" and b"Roofline in practice" in gz.body
    assert f.fetch(site.url("/papers/false-sharing.pdf"), headers={"If-None-Match": '"v1"'}).status == "not_modified"


def test_robots(site):
    f = local_fetcher()
    assert f.robots_allows(site.url("/article.html"))
    assert not f.robots_allows(site.url("/private/secret.html"))
    assert f.fetch(site.url("/private/secret.html"), use_robots=True).status == "blocked"
    assert f.fetch(site.url("/private/secret.html")).status == "ok"  # user-initiated reads ignore robots


# ----- extraction and chunking ---------------------------------------------------------------


def test_extract_pdf_pages():
    ex = extract_pdf(make_pdf(PAPER_PAGES))
    assert ex.pages == 3 and [s.page for s in ex.segments] == [1, 2, 3]
    assert "cache line" in ex.segments[0].text
    capped = extract_pdf(make_pdf(PAPER_PAGES), max_pages=2)
    assert capped.partial and len(capped.segments) == 2


def test_extract_html_prefers_main():
    ex = extract_html(ARTICLE.encode(), "text/html")
    text = " ".join(s.text for s in ex.segments)
    assert ex.title == "Roofline in practice"
    assert "site menu" not in text and "copyright" not in text
    assert any(s.heading and "Measuring the roofs" in s.heading for s in ex.segments)


def test_extract_xlsx_and_text():
    ex = extract_xlsx(make_xlsx([["Metric", "Formula"], ["Frontend_Bound", "=A/B"]]))
    assert "Frontend_Bound" in ex.segments[0].text and "=A/B" in ex.segments[0].text
    t = extract_text("# Title\n\nintro\n\n## Part\n\nbody")
    assert t.title == "Title" and t.segments[-1].heading == "Title > Part"


def test_chunks_respect_pages_and_size():
    long_page = ("Sentence about cache lines and coherence traffic. " * 80).strip()
    ex = extract_pdf(make_pdf([long_page, "short page two with enough characters to keep"]))
    chunks = chunk(ex)
    assert all(len(c.text) <= 1700 for c in chunks)
    assert {c.page for c in chunks} == {1, 2}
    assert len([c for c in chunks if c.page == 1]) >= 2


# ----- store, crawl and retrieval --------------------------------------------------------------


def build(tmp_path, site, embedder=None, respect_robots=False):
    targets = [
        target(site.url("/papers/false-sharing.pdf"), ("4.3.5",), (4,), "False sharing paper"),
        target(site.url("/content-details/manual.html"), ("2.4.2",), (2,), "Optimization manual"),
        target(site.url("/article.html"), ("6.1.1",), (6,), "Roofline article"),
        target(site.url("/forbidden"), ("5.1.1",), (5,), "Blocked page"),
        target(site.url("/private/secret.html"), ("5.1.2",), (5,), "Robots-protected"),
        target(site.url("/sheet.xlsx"), ("6.2.2",), (6,), "TMA sheet"),
        target(site.url("/notes.txt"), ("4.2.1",), (4,), "Notes"),
    ]
    corpus = SimpleNamespace(targets=targets)
    store = Store(tmp_path / "library.sqlite")
    crawler = Crawler(corpus, store, local_fetcher(), embedder, workers=3, respect_robots=respect_robots)
    return corpus, store, crawler


def test_crawl_index_and_search(tmp_path, site):
    emb = HashingEmbedder()
    corpus, store, crawler = build(tmp_path, site, emb)
    summary = crawler.run()
    assert summary["done"] == len(corpus.targets)
    rows = {r.url: r for r in store.sources()}
    paper = rows[site.url("/papers/false-sharing.pdf")]
    assert paper.status == "indexed" and paper.pages == 3 and paper.chunks >= 1
    landing = rows[site.url("/content-details/manual.html")]
    assert landing.status == "indexed" and landing.doc_url.endswith("/docs/manual.pdf")
    assert rows[site.url("/forbidden")].status == "blocked"
    assert rows[site.url("/private/secret.html")].status == "indexed"  # a listed link is read, robots.txt or not
    assert rows[site.url("/sheet.xlsx")].status == "indexed"
    counts = store.counts()
    assert counts["vectors"] == counts["chunks"] > 0

    r = Retriever(store, lambda: emb)
    passages, meta = r.search("store forwarding size mismatch stall", limit=3)
    assert passages and passages[0].doc_url.endswith("/docs/manual.pdf") and passages[0].page == 2
    assert passages[0].cite_url.endswith("#page=2")
    assert meta["semantic"] > 0 and "keyword" in passages[0].signals

    # British spelling in the query still matches American text through FTS normalisation
    passages, _ = r.search("optimisation manual", limit=3)
    assert passages

    # list-aware boost and section filter
    boosted, _ = r.search("cache line", boost_urls={site.url("/papers/false-sharing.pdf")}, limit=3)
    assert boosted[0].source_url.endswith("false-sharing.pdf") and "listed-for-topic" in boosted[0].signals
    only6, _ = r.search("roofline bandwidth", sections={6}, limit=5)
    assert only6 and all(6 in p.sections for p in only6)


def test_robots_txt_on_request(tmp_path, site):
    _, store, crawler = build(tmp_path, site, None, respect_robots=True)
    crawler.run(only=[site.url("/private/secret.html"), site.url("/article.html")])
    row = store.source(site.url("/private/secret.html"))
    assert row.status == "blocked" and "robots.txt" in (row.detail or "")
    assert store.source(site.url("/article.html")).status == "indexed"


def test_keyword_only_and_resume(tmp_path, site):
    corpus, store, crawler = build(tmp_path, site, None)
    crawler.run(only=[site.url("/article.html")])
    assert store.source(site.url("/article.html")).status == "indexed"
    assert store.source(site.url("/papers/false-sharing.pdf")).status == "pending"
    # a second run picks up only what is still pending
    todo = {t.url for t in crawler.select()}
    assert site.url("/article.html") not in todo and site.url("/papers/false-sharing.pdf") in todo
    r = Retriever(store, lambda: None)
    passages, meta = r.search("operational intensity ridge point")
    assert passages and meta["semantic"] == 0


def test_conditional_refresh(tmp_path, site):
    corpus, store, crawler = build(tmp_path, site, None)
    url = site.url("/papers/false-sharing.pdf")
    crawler.run(only=[url])
    first = store.source(url)
    assert crawler.process(corpus.targets[0], force=False) == "not_modified"
    assert store.source(url).chunks == first.chunks


def test_a_failed_refresh_keeps_the_copy(tmp_path, site, monkeypatch):
    """Offline, or a host that now refuses: the text already read stays readable. A document that is
    gone is gone."""
    corpus, store, crawler = build(tmp_path, site, None)
    url = site.url("/papers/false-sharing.pdf")
    crawler.run(only=[url])
    good = store.source(url)
    routes = site.routes()

    def serve(path_status):
        monkeypatch.setattr(site, "routes", lambda: {**routes, "/papers/false-sharing.pdf": path_status})

    serve((403, "text/html", b"no", {}))
    assert crawler.process(corpus.targets[0], force=True) == "blocked"
    kept = store.source(url)
    assert kept.status == "indexed" and kept.chunks == good.chunks and kept.detail.startswith("copy from ")
    assert "last refresh failed" in kept.detail and kept.next_try > time.time()
    store.update_source(url, extract_version=1)  # outdated, but its retry is not due yet
    assert url not in {t.url for t in crawler.select()}
    store.update_source(url, next_try=0)
    assert url in {t.url for t in crawler.select()}

    serve((404, "text/html", b"gone", {}))
    assert crawler.process(corpus.targets[0], force=True) == "dead"
    assert store.source(url).status == "dead"


def test_pdf_text_and_titles_come_out_clean():
    from cpu_perf.library.extract import EXTRACT_VERSIONS, PLACEHOLDER_TITLE, clean_text
    from cpu_perf.library.retrieve import Passage

    # PDFium marks a hyphen that breaks a word at a line end as U+FFFE
    assert clean_text("cache perfor￾mance of the orga￾\nnization") == "cache performance of the organization"
    p = Passage(chunk_id=1, source_url="u", doc_url=None, title="t", kind="pdf", page=1, heading=None,
                text="perfor￾mance", score=0.0)
    assert p.text == "performance"  # libraries extracted before the fix read clean too
    assert EXTRACT_VERSIONS["pdf"] >= 2  # and are extracted again by the next maintenance pass
    for placeholder in ("Untitled Document", "untitled", "Microsoft Word - paper.doc", "main.tex", "Document1"):
        assert PLACEHOLDER_TITLE.match(placeholder), placeholder
    for real in ("Cache-Conscious Structure Definition", "Untitled Spaces in Cache Design", "Word Count on CPUs"):
        assert not PLACEHOLDER_TITLE.match(real), real


def test_embed_missing_backfills(tmp_path, site):
    corpus, store, crawler = build(tmp_path, site, None)
    crawler.run(only=[site.url("/article.html")])
    assert store.counts()["vectors"] == 0
    crawler.embedder = HashingEmbedder()
    assert crawler.embed_missing() == store.counts()["chunks"]


def test_lock(tmp_path):
    a, b = CrawlLock(tmp_path / "crawl.lock"), CrawlLock(tmp_path / "crawl.lock")
    assert a.acquire()
    assert not b.acquire()
    a.release()
    assert b.acquire()
    b.release()
    # a dead holder's lock is taken over
    (tmp_path / "crawl.lock").write_text('{"pid": 999999999, "host": "%s", "heartbeat": 0}' % socket.gethostname())
    assert a.acquire()
    a.release()


def test_embedder_selection():
    assert get_embedder("none") is None
    assert get_embedder("hashing").dim == 256
