"""The daily list update against a local stand-in for GitHub: one check a
day across processes, only the list's files kept, nothing unsafe written,
nothing run, a bad list kept off, and the new list served on the next call."""

from __future__ import annotations

import dataclasses
import io
import json
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from cpu_perf.__main__ import start_daily_update, validate_corpus
from cpu_perf.brain import Brain, BrainHolder
from cpu_perf.corpus import load
from cpu_perf.corpus_update import CorpusUpdater, UpdateError, extract
from cpu_perf.library.service import LibraryService
from cpu_perf.net import Fetcher
from cpu_perf.search import SearchIndex

REPO = "usamahz/cpu-performance-engineering"
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
OLD_DATE = "2026-01-01T00:00:00Z"
NEW_MTIME = 1_790_000_000  # 2026-09


def member(tar, name, data=b"", kind=tarfile.REGTYPE, mtime=NEW_MTIME, linkname=""):
    ti = tarfile.TarInfo(name)
    ti.type, ti.mtime, ti.linkname, ti.size = kind, mtime, linkname, len(data) if kind == tarfile.REGTYPE else 0
    tar.addfile(ti, io.BytesIO(data) if kind == tarfile.REGTYPE else None)


def tarball(corpus, sha=NEW_SHA, edit=None, extra=(), mtime=NEW_MTIME) -> bytes:
    buf = io.BytesIO()
    top = f"cpu-performance-engineering-{sha}"
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in corpus.reader.files:
            data = corpus.reader.read_text(rel).encode("utf-8")
            if edit and rel in edit:
                data = edit[rel](data)
            member(tar, f"{top}/{rel}", data, mtime=mtime)
        member(tar, f"{top}/misc/mcp/src/evil.py", b"raise SystemExit('ran')", mtime=mtime)  # not the list's
        for args in extra:
            member(tar, *args)
    return buf.getvalue()


class GitHub:
    """Commit API, git refs and codeload, served locally."""

    def __init__(self, body: bytes, sha: str = NEW_SHA):
        self.body, self.sha, self.api_status, self.hits = body, sha, 200, []
        gh = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                gh.hits.append(self.path)
                if self.path == f"/repos/{REPO}/commits/main":
                    if gh.api_status != 200:
                        return self._send(gh.api_status, b"rate limited")
                    if self.headers.get("If-None-Match") == '"e1"':
                        return self._send(304, b"")
                    return self._send(200, gh.sha.encode(), {"ETag": '"e1"'})
                if self.path.startswith(f"/{REPO}.git/info/refs"):
                    return self._send(200, f"003f{gh.sha} refs/heads/main\n0000".encode())
                if self.path == f"/{REPO}/tar.gz/{gh.sha}":
                    return self._send(200, gh.body, {"Content-Type": "application/x-gzip"})
                self._send(404, b"")

            def _send(self, code, body, headers=None):
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def updater(self, data_dir) -> CorpusUpdater:
        f = Fetcher(allow_private=True, per_host_interval=0, use_proxy=False)
        return CorpusUpdater(data_dir, f, repo=REPO, api_base=self.base, web_base=self.base, codeload_base=self.base)


@pytest.fixture()
def serving(corpus):
    return dataclasses.replace(corpus.reader, source="bundled", commit=OLD_SHA, commit_date=OLD_DATE, built_at=None)


def add_entry(data: bytes) -> bytes:
    text = data.decode("utf-8")
    line = next(ln for ln in text.split("\n") if "joemario.github.io" in ln and ln.startswith("- ["))
    new = "- [A New Contention Study](https://example.org/new-contention-study.pdf) - Measures line transfers again."
    return text.replace(line, line + "\n" + new, 1).encode("utf-8")


def test_a_newer_list_is_downloaded_validated_and_served(corpus, index, serving, tmp_path):
    gh = GitHub(tarball(corpus, edit={"README.md": add_entry}))
    try:
        installed = load(serving)  # the copy installed with the wheel
        lib = LibraryService(installed, index.expand, data_dir=tmp_path, embed_model="none", auto_index=False, live_fetch=False)
        holder = BrainHolder(Brain(installed, SearchIndex(installed), lib))
        args = SimpleNamespace(no_auto_update=False, data_dir=str(tmp_path))
        up = start_daily_update(holder, args, updater=gh.updater(tmp_path))
        assert up is not None and lib.on_tick is not None
        lib.on_tick()
        new = holder.current
        assert new.c.reader.source == "downloaded" and new.c.reader.commit == NEW_SHA
        assert any(e.url == "https://example.org/new-contention-study.pdf" for e in new.c.entries.values())
        assert any(t.url == "https://example.org/new-contention-study.pdf" for t in lib.crawler.corpus.targets)
        on_disk = tmp_path / "corpus" / NEW_SHA
        assert not (on_disk / "misc" / "mcp").exists()  # only the list's own files
        info = json.loads((on_disk / "_build_info.json").read_text())
        assert info["commit"] == NEW_SHA and info["commit_date"].startswith("2026-09")
        assert "on; last checked" in new.update_line()
        # another process sharing the data dir: no request, it picks up the same copy
        hits = len(gh.hits)
        other = gh.updater(tmp_path).run(serving)
        assert other is not None and other.commit == NEW_SHA and len(gh.hits) == hits
        # and the next tick on this process asks nothing until a day has passed
        lib.on_tick()
        assert len(gh.hits) == hits
    finally:
        gh.close()


def test_a_list_that_does_not_parse_is_kept_off(corpus, serving, tmp_path):
    gh = GitHub(tarball(corpus, edit={"README.md": lambda d: b"# hello\n"}))
    try:
        up = gh.updater(tmp_path)
        out = up.run(serving, validate=lambda r: validate_corpus(r, corpus))
        assert out is None
        st = up.state()
        assert st["rejected"] == NEW_SHA and "upgrade the server" in st["error"]
        assert not (tmp_path / "corpus" / "current.json").exists()
        up.interval = 0  # due again: the same bad commit is not fetched twice
        n = len([h for h in gh.hits if "tar.gz" in h])
        assert up.run(serving, validate=lambda r: validate_corpus(r, corpus)) is None
        assert len([h for h in gh.hits if "tar.gz" in h]) == n
    finally:
        gh.close()


def test_rate_limited_api_falls_back_to_git(corpus, serving, tmp_path):
    gh = GitHub(tarball(corpus))
    gh.api_status = 403
    try:
        out = gh.updater(tmp_path).run(serving)
        assert out is not None and out.commit == NEW_SHA
        assert any("info/refs" in h for h in gh.hits)
    finally:
        gh.close()


def test_checkouts_older_copies_and_opt_out_never_update(corpus, serving, tmp_path):
    gh = GitHub(tarball(corpus, mtime=1_700_000_000))  # 2023: older than what is served
    try:
        checkout = dataclasses.replace(serving, source="checkout")
        assert gh.updater(tmp_path).run(checkout) is None and gh.hits == []
        assert gh.updater(tmp_path).run(serving) is None  # downloaded, but older than the installed copy
        assert not (tmp_path / "corpus" / "current.json").exists()
        holder = BrainHolder(Brain(corpus))
        assert start_daily_update(holder, SimpleNamespace(no_auto_update=True, data_dir=str(tmp_path))) is None
    finally:
        gh.close()


def test_unsafe_archives_are_refused(corpus, tmp_path):
    top = "repo-x"

    def build(*members):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            member(tar, f"{top}/README.md", b"# list\n")
            for m in members:
                member(tar, *m)
        return buf.getvalue()

    out = tmp_path / "out"
    out.mkdir()
    files, _ = extract(
        build(
            ("../escape.md", b"x"),
            (f"{top}/../../misc/notes/up.md", b"x"),
            ("/etc/misc/notes/abs.md", b"x"),
            (f"{top}/misc/notes/link.md", b"", tarfile.SYMTYPE, NEW_MTIME, "/etc/passwd"),
            (f"{top}/misc/scripts/check_format.py", b"print('kept as data, never run')"),
            (f"{top}/misc/mcp/src/x.py", b"x"),
        ),
        out,
    )
    assert files == ["README.md", "misc/scripts/check_format.py"]
    assert not (tmp_path / "escape.md").exists() and not (out / "misc" / "notes" / "link.md").exists()
    with pytest.raises(UpdateError, match="collides"):
        extract(build((f"{top}/misc/notes/a.md", b"x"), (f"{top}/misc/notes/A.md", b"y")), tmp_path / "o2")
    with pytest.raises(UpdateError, match="larger"):
        extract(build((f"{top}/misc/notes/big.md", b"x" * (5 * 1024 * 1024 + 1))), tmp_path / "o3")


def test_fork_names_are_checked(monkeypatch):
    from cpu_perf.corpus_update import DEFAULT_UPSTREAM, upstream

    monkeypatch.setenv("CPU_PERF_UPSTREAM", "someone/their-fork")
    assert upstream() == "someone/their-fork"
    for bad in ("../../etc", "a/b/c", "x y/z", "owner/.."):
        monkeypatch.setenv("CPU_PERF_UPSTREAM", bad)
        assert upstream() == DEFAULT_UPSTREAM
