"""A newer list swapped in under a running server: every handler sees it on
its next call, moved ids are flagged, removed files and links disappear."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import anyio
from mcp import Client

from cpu_perf import manifest
from cpu_perf.brain import Brain, BrainHolder
from cpu_perf.corpus import CrawlTarget, load
from cpu_perf.library.chunk import Chunk
from cpu_perf.library.service import LibraryService
from cpu_perf.locate import CorpusReader
from cpu_perf.server import create_server


def edited_copy(corpus, root: Path) -> CorpusReader:
    """The list with entries 4.3.4 and 4.3.5 swapped and one note removed."""
    for rel in corpus.reader.files:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(corpus.reader.read_text(rel), encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8").split("\n")
    a = next(i for i, ln in enumerate(readme) if corpus.entries["4.3.4"].url in ln and ln.startswith("- ["))
    b = next(i for i, ln in enumerate(readme) if corpus.entries["4.3.5"].url in ln and ln.startswith("- ["))
    readme[a], readme[b] = readme[b], readme[a]
    (root / "README.md").write_text("\n".join(readme), encoding="utf-8")
    (root / "misc" / "notes" / "status.md").unlink()
    return CorpusReader(source="test", root=root, files=manifest.select(root))


def text(result) -> str:
    return result.content[0].text


def test_a_swapped_list_is_served_on_the_next_call(corpus, index, tmp_path):
    new_corpus = load(edited_copy(corpus, tmp_path / "corpus"))
    assert new_corpus.entries["4.3.5"].url == corpus.entries["4.3.4"].url
    holder = BrainHolder(Brain(corpus, index))
    server = create_server(holder)

    async def go():
        async with Client(server) as c:
            before = text(await c.call_tool("get_entry", {"ref": "4.3.5"}))
            status_before = await c.read_resource("cpuperf://file/misc/notes/status.md")
            holder.swap(Brain(new_corpus))
            after = text(await c.call_tool("get_entry", {"ref": "4.3.5"}))
            done = await c.complete(
                ref={"type": "ref/resource", "uri": "cpuperf://file/{+path}"}, argument={"name": "path", "value": "misc/notes/sta"}
            )
            try:
                await c.read_resource("cpuperf://file/misc/notes/status.md")
                gone = False
            except Exception:
                gone = True
            return before, status_before, after, done, gone

    before, status_before, after, done, gone = anyio.run(go)
    assert "C2C" in before and "Note:" not in before
    assert "Everything You Always Wanted" in after and "The list was updated: id 4.3.5" in after
    assert status_before.contents
    assert "misc/notes/status.md" not in done.completion.values
    assert gone


def test_dropped_links_leave_answers(tmp_path):
    keep = CrawlTarget(url="https://a.example/keep", entry_ids=["1.1"], sections=[1], title="keep")
    drop = CrawlTarget(url="https://a.example/drop", entry_ids=["1.2"], sections=[1], title="drop")
    lib = LibraryService(
        SimpleNamespace(targets=[keep, drop]), data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=False
    )
    for t in (keep, drop):
        lib.store.replace_chunks(t.url, [Chunk(0, None, None, "roofline ridge point and bandwidth")], status="indexed", title=t.title)
    found, _ = lib.retriever.search("roofline ridge point", listed_only=True)
    assert {p.source_url for p in found} == {keep.url, drop.url}
    lib.set_corpus(SimpleNamespace(targets=[keep]))
    found, _ = lib.retriever.search("roofline ridge point", listed_only=True)
    assert [p.source_url for p in found] == [keep.url]
    assert lib.crawler.corpus.targets == [keep]
