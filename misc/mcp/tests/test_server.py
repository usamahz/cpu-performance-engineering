"""The MCP surface, in process: tools, resources, prompts, completions."""

from __future__ import annotations

import socket
from types import SimpleNamespace

import anyio
import pytest
from mcp import Client

from cpu_perf import render
from cpu_perf.brain import Brain
from cpu_perf.corpus import CrawlTarget
from cpu_perf.library.service import LibraryService
from cpu_perf.net import Fetcher
from cpu_perf.server import create_server

from fixture_site import Site

TOOLS = {
    "ask", "lookup", "search", "fetch", "get_section", "get_entry", "reading_path", "get_benchmark", "editorial_record",
    "check_evidence", "read_source", "read_file", "library_status",
}


def run(coro_fn):
    return anyio.run(coro_fn)


@pytest.fixture(scope="module")
def site():
    with Site() as s:
        yield s


@pytest.fixture(scope="module")
def brain(corpus, index, tmp_path_factory, site):
    """A brain whose library crawled two fixture pages standing in for two real entries."""
    data = tmp_path_factory.mktemp("lib")
    fake_targets = [
        CrawlTarget(url=site.url("/papers/false-sharing.pdf"), entry_ids=["4.3.5"], sections=[4], title="C2C"),
        CrawlTarget(url=site.url("/content-details/manual.html"), entry_ids=["2.4.2"], sections=[2], title="Manual"),
    ]
    def offline(host, port, type=0):
        # every host resolves to the fixture's loopback; nothing leaves the machine
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    fetcher = Fetcher(allow_private=True, per_host_interval=0, resolver=offline, use_proxy=False, connect_timeout=2, read_timeout=2)
    lib = LibraryService(
        SimpleNamespace(targets=fake_targets), index.expand, data_dir=data, embed_model="hashing",
        auto_index=False, live_fetch=True, fetcher=fetcher, workers=2,
    )
    lib.load_embedder()
    lib.crawler.run()
    lib.corpus = corpus  # the server sees the real corpus; the store holds the fixture sources
    return Brain(corpus, index, lib)


@pytest.fixture(scope="module")
def server(brain):
    # structured output on, so the tests can read the results as data
    return create_server(brain, structured=True)


def call(server, name, args=None):
    async def go():
        async with Client(server) as c:
            return await c.call_tool(name, args or {})

    return run(go)


def test_tools_listed_with_annotations(server):
    async def go():
        async with Client(server) as c:
            return (await c.list_tools()).tools

    tools = run(go)
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.output_schema is not None, t.name
        assert t.annotations.read_only_hint is True
    rs = next(t for t in tools if t.name == "read_source")
    assert rs.annotations.open_world_hint is True


def test_instructions(server):
    async def go():
        async with Client(server) as c:
            return c.instructions

    text = run(go)
    assert "call `ask` first" in text.lower() and len(text) < 2000
    assert "load testing" in text and "compilers" in text  # the scope the list covers, beyond the core itself


def test_ask(server):
    r = call(server, "ask", {"question": "false sharing between cores on one cache line"})
    assert not r.is_error
    sc = r.structured_content
    assert sc["passages"] and sc["passages"][0]["cite_url"].endswith("#page=1") or sc["passages"][0]["page"]
    assert any(e["id"] == "4.3.5" for e in sc["entries"])
    assert sc["benchmark"]["slug"] == "09-false-sharing"
    text = r.content[0].text
    assert "Passages from the linked sources" in text and "Untrusted" in text


def test_search_scopes(server):
    r = call(server, "lookup", {"query": "coordinated omission"})
    assert r.structured_content["hits"][0]["title"] in ("Coordinated Omission", "Coordinated omission")
    r = call(server, "lookup", {"query": "store forwarding", "scope": "sources"})
    assert r.structured_content["passages"]
    r = call(server, "lookup", {"query": "cppreference", "scope": "record"})
    assert r.structured_content["hits"][0]["ref"] == "r9.14"


def test_sections_and_entries(server):
    toc = call(server, "get_section").structured_content["contents"]
    assert len(toc["sections"]) == 16 and toc["watchlist_checked"]
    sec = call(server, "get_section", {"section": "watchlist"}).structured_content["section"]
    assert sec["number"] == 16 and all(e["condition"] for s in sec["subsections"] for e in s["entries"])
    e = call(server, "get_entry", {"ref": "1.7"}).structured_content
    assert e["entry"]["title"].startswith("Roofline") and e["also_listed"][0]["id"] == "6.1.1"
    bad = call(server, "get_entry", {"ref": "99.9.9"})
    assert bad.is_error and "Ids are" in bad.content[0].text


def test_reading_path_benchmark_record_evidence(server):
    p = call(server, "reading_path").structured_content
    assert [s["ref"] for s in p["steps"][:2]] == ["1.1", "1.2"]
    p = call(server, "reading_path", {"topic": "false sharing"}).structured_content
    assert any(s["kind"] == "benchmark" and s["ref"] == "09-false-sharing" for s in p["steps"])
    b = call(server, "get_benchmark", {"slug": "9", "parts": ["machine", "code"]}).structured_content["detail"]
    assert len(b["machine"]) == 7 and "pthread" in b["parts"]["code"]
    assert len(call(server, "get_benchmark").structured_content["benchmarks"]) == 14
    rec = call(server, "editorial_record", {"rule": "1", "section": 9}).structured_content
    assert rec["items"] and all(1 in i["rules"] for i in rec["items"])
    ev = call(server, "check_evidence", {"claim": "Graviton4 is 30% faster than Graviton3"}).structured_content
    assert ev["verdict"] == "drop_number" and ev["precedents"]


def test_read_source_and_file(server, site):
    r = call(server, "read_source", {"ref": "4.3.5"}).structured_content  # not in the fixture library: live read
    assert r["listed_as"][0]["id"] == "4.3.5"
    assert r["status"] in ("unreachable", "dead", "blocked")  # offline in tests: reported, never faked
    r = call(server, "read_source", {"ref": site.url("/papers/false-sharing.pdf")})
    assert r.is_error  # not a URL the repository mentions
    f = call(server, "read_file", {"path": "misc/benchmarks/09-false-sharing/run.sh"}).structured_content
    assert f["text"].startswith("#!") and f["url"].endswith("run.sh")
    assert call(server, "read_file", {"path": "../../etc/passwd"}).is_error
    st = call(server, "library_status", {"detail": True}).structured_content
    assert st["enabled"] and st["passages"] > 0 and st["embedder"].startswith("hashing")


def test_resources_prompts_completions(server):
    async def go():
        async with Client(server) as c:
            readme = await c.read_resource("cpuperf://readme")
            sec = await c.read_resource("cpuperf://section/4")
            f = await c.read_resource("cpuperf://file/misc/notes/voice.md")
            rules = await c.read_resource("cpuperf://rules")
            templates = await c.list_resource_templates()
            resources = await c.list_resources()
            prompts = await c.list_prompts()
            diag = await c.get_prompt("diagnose", {"symptom": "high p99 latency", "platform": "Graviton4"})
            comp = await c.complete(ResourceTemplateReference(type="ref/resource", uri="cpuperf://benchmark/{slug}"), {"name": "slug", "value": "09"})
            errors = []
            for bad in ("cpuperf://file/../README.md", "cpuperf://section/77"):
                try:
                    await c.read_resource(bad)
                except Exception as exc:
                    errors.append(type(exc).__name__)
            return readme, sec, f, rules, templates, resources, prompts, diag, comp, errors

    from mcp.types import ResourceTemplateReference

    readme, sec, f, rules, templates, resources, prompts, diag, comp, errors = run(go)
    assert readme.contents[0].text.startswith("# CPU Performance Engineering")
    assert "4. Memory hierarchy" in sec.contents[0].text
    assert "One voice" in f.contents[0].text
    assert "CPU model and microarchitecture" in rules.contents[0].text
    assert {t.uri_template for t in templates.resource_templates} >= {"cpuperf://section/{number}", "cpuperf://file/{+path}"}
    assert len(resources.resources) > 30
    assert {p.name for p in prompts.prompts} >= {"ask_the_list", "diagnose", "study_plan", "review_candidate"}
    assert "The USE Method" in diag.messages[0].content.text
    assert comp.completion.values == ["09-false-sharing"]
    assert len(errors) == 2


def test_brief_answers_fit_the_budget_and_full_ones_carry_more(server):
    from cpu_perf.brain import BRIEF_BUDGET, FULL_BUDGET

    q = {"question": "false sharing between cores on one cache line"}
    brief = call(server, "ask", q)
    full = call(server, "ask", {**q, "detail": "full"})
    # the markdown is what the model reads (structured output is off by default)
    assert len(brief.content[0].text) <= BRIEF_BUDGET and len(full.content[0].text) <= FULL_BUDGET
    assert brief.structured_content["detail"] == "brief" and full.structured_content["detail"] == "full"
    assert all(p["id"] for p in brief.structured_content["passages"])
    assert full.structured_content["record"]  # the editorial record comes with full answers


def test_brief_answers_add_the_record_and_benchmark_only_when_relevant(server):
    plain = call(server, "ask", {"question": "what is store forwarding"}).structured_content
    assert plain["record"] == []
    about_list = call(server, "ask", {"question": "why is cppreference not in the list"}).structured_content
    assert any(r["id"] == "r9.14" for r in about_list["record"])
    measuring = call(server, "ask", {"question": "how do I measure false sharing"}).structured_content
    assert measuring["benchmark"]["slug"] == "09-false-sharing"
    assert any("Apple M4 Pro" in g for g in measuring["guidance"])
    assert not any("Apple M4 Pro" in g for g in plain["guidance"]) or plain["benchmark"]


def quoted_numbers(note: str) -> list[int]:
    import re

    return [int(n) for n in re.findall(r"\[(\d+)\]", note)]


@pytest.fixture()
def grounded(corpus, index, tmp_path):
    """A library holding text under the entries' own URLs, as a real crawl stores it."""
    from cpu_perf.library.chunk import Chunk

    lib = LibraryService(corpus, index.expand, data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=False)
    lib.store.replace_chunks(
        corpus.entries["4.3.5"].url,
        [Chunk(i, None, None, f"False sharing: two cores write one cache line and the line moves between them. Part {i}.")
         for i in range(3)],
        status="indexed", title="Joe Mario's blog", kind="html",
    )
    return Brain(corpus, index, lib)


def test_ask_says_which_sources_it_read(grounded, corpus):
    """Each entry says whether the answer carries its text: a model cannot tell a quoted source from a
    link it was never given unless the answer says so."""
    out = grounded.ask("false sharing between cores on one cache line")
    c2c = next(e for e in out.entries if e.id == "4.3.5")
    assert c2c.source_text == "quoted" and c2c.source_note.startswith("quoted in passages [")
    assert all(1 <= n <= len(out.passages) for n in quoted_numbers(c2c.source_note))
    others = [e for e in out.entries if e.id != "4.3.5"]
    assert others and all(e.source_text == "not_read" and e.source_note.startswith("not read") for e in others)
    assert "4.3.5" in out.coverage and "Not read on this machine" in out.coverage
    # the list's title, not the document's own
    assert {p.title for p in out.passages if p.source_url == c2c.url} == {corpus.entries["4.3.5"].title}
    assert any("only through a passage above" in g for g in out.guidance)
    assert any("marked not read" in g for g in out.guidance)
    text = render.ask(out)
    assert "**Sources:** Quoted below" in text and "Source text: quoted in passages [" in text
    assert "Source text: not read" in text


def test_a_cut_passage_is_never_named_by_an_entry(grounded):
    """The budget drops passages from the end; the entries are marked again after each drop."""
    from cpu_perf.brain import fit_budget

    out = grounded.ask("false sharing between cores on one cache line", detail="full")
    out.passages = [p.model_copy(update={"n": k, "text": p.text * 40}) for k, p in enumerate(out.passages * 3, 1)]
    grounded.mark_sources(out)
    assert max(quoted_numbers(next(e for e in out.entries if e.id == "4.3.5").source_note)) > 3
    fit_budget(out, 3000, grounded.mark_sources)
    assert len(out.passages) == 2
    for e in out.entries:
        if e.source_text == "quoted":
            assert all(1 <= n <= len(out.passages) for n in quoted_numbers(e.source_note))


def test_ask_leads_a_listed_paper_with_its_abstract_and_marks_what_did_not_match(corpus, index, tmp_path):
    from cpu_perf.library.chunk import Chunk

    lib = LibraryService(corpus, index.expand, data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=False)
    paper = corpus.entries["4.4.1"].url  # Cache-Conscious Structure Definition
    abstract = (
        "Appears in Proceedings of PLDI 1999. ABSTRACT A program’s cache perfor￾mance can be improved by "
        "changing the organization and layout of its data. This paper describes two techniques, structure splitting "
        "and field reordering, that improve the cache behavior of structures larger than a cache block. In five "
        "programs, structure splitting reduced cache miss rates and improved performance beyond earlier layout "
        "techniques. Keywords cache-conscious definition, structure splitting 1. INTRODUCTION An effective way"
    )
    lib.store.replace_chunks(
        paper,
        [Chunk(0, 1, None, abstract), Chunk(1, 9, None, "Hot fields and cold fields: splitting a class by field access counts.")],
        status="indexed", title="Untitled Document", kind="pdf", pages=12,
    )
    sf = corpus.entries["2.4.2"].url  # in the library, but about something else entirely
    lib.store.replace_chunks(sf, [Chunk(0, None, None, "Release notes for a gardening app.")], status="indexed", title="SF")
    brain = Brain(corpus, index, lib)

    out = brain.ask("hot and cold fields of a large struct: structure splitting")
    lead = next(p for p in out.passages if "abstract" in p.signals)
    assert lead.page == 1 and not lead.trimmed  # the whole abstract, not a keyword window of it
    assert lead.text.startswith("A program’s cache performance can be improved")  # U+FFFE joined
    assert "INTRODUCTION" not in lead.text and "Keywords" not in lead.text
    assert {p.title for p in out.passages if p.source_url == paper} == {corpus.entries["4.4.1"].title}  # not "Untitled Document"
    e = next(e for e in out.entries if e.id == "4.4.1")
    assert e.source_text == "quoted" and ("page 1" in e.source_note or "pages 1," in e.source_note)
    assert "abstract, page 1" in render.ask(out)

    # nothing matched but the abstract: it is added, ahead of the other sources' passages
    out = brain.ask("cache-conscious structure definition: which layout techniques does it propose?")
    assert out.passages and "abstract" in out.passages[0].signals

    out = brain.ask("store forwarding size mismatch")
    e = next(e for e in out.entries if e.id == "2.4.2")
    assert e.source_text == "in_library" and 'read_source("2.4.2", query=...)' in e.source_note
    assert any("marked in the library" in g for g in out.guidance)
    assert brain.lib.retriever.lead_passage(sf) is None  # not a PDF: no abstract to lead with


def test_a_passage_id_reads_back_in_full(corpus, index, tmp_path):
    from cpu_perf.library.chunk import Chunk
    from cpu_perf.resolve import NotFound

    lib = LibraryService(corpus, index.expand, data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=False)
    sf, c2c = corpus.entries["2.4.2"].url, corpus.entries["4.3.5"].url
    texts = ["Intro to forwarding.", "A size mismatch between the store and the load blocks forwarding.", "Disambiguation."]
    lib.store.replace_chunks(sf, [Chunk(i, None, None, t) for i, t in enumerate(texts)], status="indexed", title="SF")
    lib.store.replace_chunks(c2c, [Chunk(0, None, None, "perf c2c finds contended lines.")], status="indexed", title="C2C")
    brain = Brain(corpus, index, lib)
    p = next(p for p in brain.ask("store forwarding size mismatch").passages if p.source_url == sf)
    out = brain.read_source("2.4.2", passage=p.id)
    assert [x.text for x in out.passages] == texts  # the passage with its neighbours, in order
    assert any(x.id == p.id and "requested" in x.signals for x in out.passages)
    with pytest.raises(NotFound, match="is not part of"):
        brain.read_source("4.3.5", passage=p.id)


def test_ask_reads_pasted_output(server):
    import context_fixtures as F

    r = call(server, "ask", {"question": "my service got slower, what is going on?", "context": F.PERF6_HYBRID})
    assert not r.is_error
    sc = r.structured_content
    ctx = sc["context"]
    be = next(m for m in ctx["metrics"] if m["name"].startswith("Backend_Bound (level 1) [cpu_core]"))
    assert be["flag"] == "above Intel's threshold > 0.2" and "TMA_Metrics_5.2-full" in be["source"]
    assert any(e["id"].startswith("6.2.") for e in sc["entries"])
    assert sc["topics"][0].startswith("6.2 ")
    text = r.content[0].text
    assert "Your pasted output (perf stat, Intel)" in text and "| Metric | Value | From |" in text

    r = call(server, "ask", {"question": "why won't this loop vectorise?", "context": F.GCC_REMARKS})
    sc = r.structured_content
    assert sc["topics"][0].startswith("8.3 ")
    assert any(e["id"].startswith("8.3.") for e in sc["entries"])
    assert sc["benchmark"] and sc["benchmark"]["slug"] in ("08-autovectorization-aliasing", "07-aos-vs-soa-simd")



def test_ask_keeps_to_the_machine_the_output_came_from(server):
    """Intel output gets no AMD or Arm sources, AMD output no Intel ones; a
    memory-bound run is sent to the memory hierarchy."""
    import context_fixtures as F

    def ids(r):
        return [e["id"] for e in r.structured_content["entries"]]

    r = call(server, "ask", {"question": "Compiling this one big file takes forever. What does this perf stat say?",
                             "context": F.RPL_HYBRID_MUX})
    got = ids(r)
    assert r.structured_content["context"]["vendor"] == "intel"
    assert any(i.startswith("6.2.") for i in got)
    assert not {"6.2.4", "6.2.5", "5.2.2", "5.2.4", "5.2.5", "5.3.3"} & set(got)
    assert r.structured_content["topics"][1].startswith("2.1 ")  # Frontend_Bound: fetch and decode

    r = call(server, "ask", {"question": "My bytecode interpreter runs slower than I expected on this EPYC. What is the bottleneck?",
                             "context": F.PERF_ERR_METRICGROUP})
    got = ids(r)
    assert "6.2.4" in got[:2] and not {"6.2.2", "6.2.3"} & set(got)
    assert "no metric group PipelineL1" in r.content[0].text

    r = call(server, "ask", {"question": "My hash join got 3x slower once the table outgrew the L3. Where is the time going?",
                             "context": F.SPR_MEMORY})
    topics = r.structured_content["topics"]
    assert topics[0].startswith("6.2 ") and topics[1].startswith("4.1 ")
    got = ids(r)
    assert any(i.startswith("4.1.") for i in got) and "6.2.4" not in got and "3.4.2" not in got

    # no vendor in the output or the question: the vendor-neutral method leads
    r = call(server, "ask", {"question": "Our service's p99 latency doubled on these VMs; does anything stand out?",
                             "context": F.VM_CSV_INTERVALS})
    assert r.structured_content["context"]["vendor"] is None
    assert ids(r)[0] == "6.2.1"


def test_default_results_are_markdown_for_every_client(brain):
    """Claude Code and Codex show the model only structured content when there
    is any, so by default the rich tools return markdown alone."""
    plain = create_server(brain)

    async def go():
        async with Client(plain) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            r = await c.call_tool("ask", {"question": "store forwarding stall"})
            return tools, r

    tools, r = run(go)
    assert set(tools) == TOOLS
    assert all(tools[n].output_schema is None for n in TOOLS - {"search", "fetch"})
    assert tools["search"].output_schema and tools["fetch"].output_schema
    assert all(t.annotations.read_only_hint and t.annotations.destructive_hint is False and t.title for t in tools.values())
    assert r.structured_content is None and r.content[0].text.startswith("# Evidence for:")


def test_search_and_fetch_follow_the_deep_research_contract(server):
    import json

    r = call(server, "search", {"query": "false sharing perf c2c"})
    assert not r.is_error
    as_text = json.loads(r.content[0].text)
    assert as_text == r.structured_content  # the same object twice, as ChatGPT asks
    results = r.structured_content["results"]
    assert results and all(set(x) == {"id", "title", "url"} and x["url"].startswith("http") for x in results)
    assert results[0]["id"] == "entry:4.3.5"
    for doc_id in ("entry:4.3.5", "section:6.2", "benchmark:09-false-sharing", "record:r9.14"):
        d = call(server, "fetch", {"id": doc_id})
        assert not d.is_error, (doc_id, d.content[0].text)
        doc = d.structured_content
        assert doc["id"] == doc_id and doc["text"] and doc["url"].startswith("http")
        assert json.loads(d.content[0].text) == doc
    passage = next((x for x in results if x["id"].startswith("passage:")), None)
    if passage:
        doc = call(server, "fetch", {"id": passage["id"]}).structured_content
        assert "untrusted" in doc["metadata"]["note"]
    bad = call(server, "fetch", {"id": "nonsense"})
    assert bad.is_error and "search" in bad.content[0].text


def test_out_of_range_arguments_get_a_clear_error(server):
    """Codex strips minimum/maximum from schemas, so the server must say what is wrong."""
    r = call(server, "lookup", {"query": "roofline", "limit": 500})
    assert r.is_error
    assert "limit" in r.content[0].text
