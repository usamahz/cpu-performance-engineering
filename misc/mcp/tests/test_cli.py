"""The command line as a person meets it: a client quitting, Ctrl-C, and
`cpu-perf index` stopped halfway."""

from __future__ import annotations

import _thread
import signal
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import cpu_perf.__main__ as cli
import cpu_perf.server as server_mod
from cpu_perf.corpus import CrawlTarget
from cpu_perf.library.crawler import Crawler
from cpu_perf.library.store import Store
from cpu_perf.net import Fetcher

from fixture_site import Site


class Left(SystemExit):
    pass


@pytest.fixture()
def no_exit(monkeypatch):
    """os._exit would end the test run; record the code instead."""

    def fake_exit(code):
        raise Left(code)

    monkeypatch.setattr(cli.os, "_exit", fake_exit)


def test_serve_leaves_when_the_client_closes_stdin(monkeypatch, no_exit, tmp_path):
    """The client quits by closing stdin; downloads still in flight must not
    keep the process alive, so serve exits at once."""
    seen = {}

    class Stub:
        def run(self, transport, **kw):
            seen["transport"] = transport
            seen["sigint"] = signal.getsignal(signal.SIGINT)

    monkeypatch.setattr(server_mod, "create_server", lambda *a, **k: Stub())
    monkeypatch.setenv("CPU_PERF_DATA_DIR", str(tmp_path))
    try:
        with pytest.raises(Left) as left:
            cli.main(["serve", "--no-library", "--no-auto-update"])
    finally:
        signal.signal(signal.SIGINT, signal.default_int_handler)
    assert left.value.code == 0 and seen["transport"] == "stdio"
    # Ctrl-C: our handler, not the default one that waits on a stdin read a terminal never ends
    assert seen["sigint"] is not signal.default_int_handler


@pytest.mark.skipif(sys.platform == "win32", reason="Ctrl-C does not interrupt a lock wait on Windows")
def test_ctrl_c_stops_a_crawl_instead_of_finishing_it(tmp_path):
    """`cpu-perf index` interrupted: the queue is dropped, not crawled to the end."""
    with Site() as site:
        site.slow_seconds = 1.0
        targets = [
            CrawlTarget(url=site.url(f"/slow/manual.pdf?n={i}"), entry_ids=[f"9.9.{i}"], sections=[9], title=f"t{i}")
            for i in range(24)
        ]
        store = Store(tmp_path / "lib.sqlite")
        crawler = Crawler(SimpleNamespace(targets=targets), store, Fetcher(allow_private=True, per_host_interval=0), None, workers=2)
        timer = threading.Timer(0.5, _thread.interrupt_main)
        timer.start()
        t = time.monotonic()
        try:
            with pytest.raises(KeyboardInterrupt):
                crawler.run()
        finally:
            timer.cancel()
        assert time.monotonic() - t < 6  # the whole queue would take about 12 s
        assert crawler.progress.done < len(targets)


def test_suggested_commands_match_how_it_was_started(monkeypatch):
    monkeypatch.setattr(cli.sys, "argv", ["/home/me/.cache/uv/archive-v0/abc/bin/cpu-perf"])
    assert cli.command() == "uvx cpu-perf" and "`uvx cpu-perf status`" in cli.terminal_hint()
    monkeypatch.setattr(cli.sys, "argv", ["/home/me/venv/bin/cpu-perf"])
    assert cli.command() == "cpu-perf" and "`cpu-perf index`" in cli.terminal_hint()
    monkeypatch.setattr(cli.sys, "argv", ["C:\\Users\\me\\AppData\\Local\\uv\\cache\\archive-v0\\x\\Scripts\\cpu-perf.exe"])
    assert cli.command() == "uvx cpu-perf"
