"""Command line: serve (stdio or HTTP), build the library, show status, self-test."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import statistics
import sys
import threading
import time

from . import __version__


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("0", "false", "no", "off", "")


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", default=os.environ.get("CPU_PERF_REPO"), help="serve a checkout of the repository instead of the bundled copy")
    p.add_argument("--data-dir", default=os.environ.get("CPU_PERF_DATA_DIR"), help="where the source library lives")
    p.add_argument("--embed-model", default=os.environ.get("CPU_PERF_EMBED_MODEL"), help="model2vec model id, 'hashing', or 'none' for keyword search only")
    p.add_argument("--no-library", action="store_true", default=not _env_bool("CPU_PERF_LIBRARY", True), help="repository knowledge only: no source library")
    p.add_argument(
        "--respect-robots", action="store_true", default=_env_bool("CPU_PERF_RESPECT_ROBOTS", False),
        help="skip what robots.txt disallows (by default the listed links are read, as a reader opening them would)",
    )
    p.add_argument("--ignore-robots", action="store_true", help=argparse.SUPPRESS)  # the default now; still accepted
    p.add_argument("--no-auto-update", action="store_true", default=not _env_bool("CPU_PERF_AUTO_UPDATE", True), help="serve the installed copy of the list; no daily check for a newer one")
    p.add_argument("--log-level", default=os.environ.get("CPU_PERF_LOG_LEVEL", "WARNING"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cpu-perf", description="MCP server for the CPU Performance Engineering list.")
    parser.add_argument("--version", action="version", version=f"cpu-perf {__version__}")
    parser.add_argument("--selftest", action="store_true", help="load the corpus, check it, time it, and exit")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the MCP server (default)")
    _common(serve)
    serve.add_argument("--transport", choices=("stdio", "http"), default=os.environ.get("CPU_PERF_TRANSPORT", "stdio"))
    serve.add_argument("--host", default=os.environ.get("CPU_PERF_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("CPU_PERF_PORT") or os.environ.get("PORT") or 8000))
    serve.add_argument("--path", default=os.environ.get("CPU_PERF_PATH", "/mcp"))
    serve.add_argument("--no-auto-index", action="store_true", default=not _env_bool("CPU_PERF_AUTO_INDEX", True), help="do not build the library in the background")
    serve.add_argument("--no-live-fetch", action="store_true", default=not _env_bool("CPU_PERF_LIVE_FETCH", True), help="read_source serves only what is already indexed")
    serve.add_argument("--structured-output", action="store_true", default=_env_bool("CPU_PERF_STRUCTURED_OUTPUT", False), help="also return structured content and output schemas (for programmatic clients; chat clients read the markdown)")
    serve.add_argument("--allowed-host", action="append", default=[h for h in os.environ.get("CPU_PERF_ALLOWED_HOSTS", "").split(",") if h], help="Host header values to accept over HTTP (DNS-rebinding protection)")

    index = sub.add_parser("index", help="build or refresh the source library now")
    _common(index)
    index.add_argument("--refresh", action="store_true", help="re-check every source, not only missing or stale ones")
    index.add_argument("--only", action="append", default=[], help="a URL or entry id to (re)fetch; repeatable")
    index.add_argument("--max-pages", type=int, default=2500, help="pages indexed per PDF")
    index.add_argument("--workers", type=int, default=6)
    index.add_argument("--no-embeddings", action="store_true", help="keyword index only")

    status = sub.add_parser("status", help="show the library's coverage")
    _common(status)
    status.add_argument("--detail", action="store_true")
    status.add_argument("--json", action="store_true")
    return parser


def _setup_logging(level: str) -> None:
    logging.basicConfig(stream=sys.stderr, level=getattr(logging, str(level).upper(), logging.WARNING), format="cpu-perf %(levelname)s %(message)s")


def _data_dir(args):
    from pathlib import Path

    from .library.store import default_data_dir

    return Path(args.data_dir).expanduser() if args.data_dir else default_data_dir()


def _brain(args, *, auto_index: bool, live_fetch: bool, library: bool = True, workers: int = 6, max_pages: int = 2500):
    from .brain import Brain
    from .corpus import load
    from .library.service import LibraryService
    from .locate import locate
    from .search import SearchIndex

    # with the daily update on, a newer list it downloaded wins over the installed copy
    reader = locate(args.repo, data_dir=None if args.no_auto_update else _data_dir(args))
    reader.preload()
    corpus = load(reader)
    index = SearchIndex(corpus)
    lib = None
    if library and not args.no_library:
        lib = LibraryService(
            corpus,
            index.expand,
            data_dir=args.data_dir,
            embed_model=args.embed_model,
            auto_index=auto_index,
            live_fetch=live_fetch,
            respect_robots=args.respect_robots and not args.ignore_robots,
            workers=workers,
            max_pages=max_pages,
        )
    return Brain(corpus, index, lib)


def validate_corpus(reader, current):
    """A downloaded list must parse and must not have collapsed against the one served."""
    from .corpus import load

    reader.preload()
    corpus = load(reader)
    new, old = corpus.stats(), current.stats()
    for key in ("sections", "linked_entries", "benchmarks"):
        if new[key] < 0.8 * old[key]:
            raise ValueError(f"{key} fell from {old[key]} to {new[key]}")
    return corpus


def start_daily_update(holder, args, updater=None):
    """Check once a day for a newer list and swap it in; returns the updater or None."""
    from .brain import Brain
    from .corpus_update import CorpusUpdater
    from .search import SearchIndex

    brain = holder.current
    if args.no_auto_update or brain.c.reader.source not in ("bundled", "downloaded"):
        return None
    updater = updater or CorpusUpdater(_data_dir(args))
    brain.updater = updater
    log = logging.getLogger("cpu_perf.update")

    def tick():
        cur = holder.current
        built = {}

        def check(reader):
            built["corpus"] = validate_corpus(reader, cur.c)

        newer = updater.run(cur.c.reader, validate=check)
        if newer is None:
            return
        corpus = built.get("corpus") or validate_corpus(newer, cur.c)
        holder.swap(Brain(corpus, SearchIndex(corpus), cur.lib))
        log.warning("now serving the list at commit %s", (newer.commit or "")[:12])

    if brain.lib is not None:
        brain.lib.on_tick = tick
    else:
        def loop():
            while True:
                try:
                    tick()
                except Exception:
                    log.exception("list update failed")
                time.sleep(float(os.environ.get("CPU_PERF_MAINTENANCE_SECONDS", "300")))

        threading.Thread(target=loop, name="list-update", daemon=True).start()
    return updater


def command() -> str:
    """How the person started this program, for the commands we suggest: uvx
    runs it from uv's cache, where there is no `cpu-perf` on the PATH."""
    path = os.path.abspath(sys.argv[0] or "").replace("\\", "/")
    return "uvx cpu-perf" if "/uv/" in path else "cpu-perf"


def terminal_hint() -> str:
    c = command()
    return f"""cpu-perf is an MCP server: your AI client starts it and talks to it over stdin.
Add it to a client instead of running it here:

    claude mcp add --scope user cpu-perf -- uvx cpu-perf
    codex mcp add cpu-perf -- uvx cpu-perf

From a terminal: `{c} status` shows the source library, `{c} index`
builds it now, `{c} --help` lists the rest. Waiting for a client on
stdin; Ctrl-C quits."""


def _leave(holder, code: int) -> None:
    """Exit now. Downloads still in flight would otherwise hold the process
    open for minutes after its client has gone; every library write is
    already committed, the operating system releases the crawl lock, and the
    crawl resumes where it stopped on the next start."""
    lib = holder.current.lib
    if lib is not None:
        lib.stop()
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(code)


def cmd_serve(args) -> int:
    from .brain import BrainHolder
    from .server import create_server

    brain = _brain(args, auto_index=not args.no_auto_index, live_fetch=not args.no_live_fetch)
    holder = BrainHolder(brain)
    srv = create_server(holder, live_fetch=not args.no_live_fetch, structured=args.structured_output)
    start_daily_update(holder, args)
    if brain.lib is not None:
        brain.lib.start()
    if args.transport == "stdio":
        if sys.stdin.isatty():
            print(terminal_hint(), file=sys.stderr)
        # Ctrl-C: the stdio transport waits on a stdin read that a terminal never ends
        signal.signal(signal.SIGINT, lambda *_: _leave(holder, 130))
        srv.run("stdio")
        _leave(holder, 0)  # the client closed stdin
    from mcp.server.transport_security import TransportSecuritySettings

    security = None
    if args.allowed_host:
        hosts = list(args.allowed_host)
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts + [f"{h}:*" for h in hosts if ":" not in h],
            allowed_origins=[f"https://{h}" for h in hosts] + [f"http://{h}" for h in hosts],
        )
    elif args.host not in ("127.0.0.1", "localhost", "::1"):
        logging.getLogger("cpu_perf").warning("serving on %s without --allowed-host: DNS-rebinding protection is off", args.host)
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    signal.signal(signal.SIGINT, lambda *_: _leave(holder, 130))  # the web server would re-raise it, then wait on downloads
    srv.run(
        "streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
        json_response=True,
        stateless_http=True,
        transport_security=security,
    )
    _leave(holder, 0)


def cmd_index(args) -> int:
    brain = _brain(args, auto_index=False, live_fetch=False, workers=args.workers, max_pages=args.max_pages)
    lib = brain.lib
    if lib is None:
        print("the library is disabled (--no-library)", file=sys.stderr)
        return 2
    if args.no_embeddings:
        lib.embed_model = "none"
    print(f"library: {lib.data_dir}", file=sys.stderr)
    print("loading the embedding model...", file=sys.stderr)
    lib.load_embedder()
    print(f"embedder: {lib.embedder_state}", file=sys.stderr)
    if not lib.lock.acquire():
        print("another process is building the library; try again later", file=sys.stderr)
        return 1
    stop = threading.Event()

    def report():
        while not stop.wait(3):
            p = lib.crawler.progress
            cur = ", ".join(u.split("/")[2] for u in p.current[:3])
            print(f"  {p.done}/{p.total} sources  {dict(p.counts)}  now: {cur}", file=sys.stderr)

    t = threading.Thread(target=report, daemon=True)
    t.start()
    try:
        if lib.store.stale_normalisation():
            print(f"re-normalised {lib.renormalise()} passages for the current tokenizer", file=sys.stderr)
        summary = lib.crawler.run(only=args.only or None, refresh=args.refresh)
    except KeyboardInterrupt:
        stop.set()
        p = lib.crawler.progress
        print(f"\nstopped at {p.done}/{p.total} sources; run `{command()} index` again to continue", file=sys.stderr)
        os._exit(130)  # downloads in flight would hold the process open; what is done is committed
    finally:
        stop.set()
        lib.lock.release()
    print(f"done: {summary['done']}/{summary['total']} {summary['counts']}", file=sys.stderr)
    print(lib.coverage_line())
    return 0


def cmd_status(args) -> int:
    from . import render

    brain = _brain(args, auto_index=False, live_fetch=False)
    out = brain.library_status(args.detail)
    if args.json:
        print(json.dumps(out.model_dump(mode="json"), indent=1))
    else:
        print(render.status(out, cli=command()))
    return 0


def cmd_selftest(args) -> int:
    from .corpus import load
    from .locate import locate
    from .search import SearchIndex

    t0 = time.perf_counter()
    corpus = load(locate(getattr(args, "repo", None) or os.environ.get("CPU_PERF_REPO")))
    t1 = time.perf_counter()
    index = SearchIndex(corpus)
    t2 = time.perf_counter()
    stats = corpus.stats()
    problems = list(corpus.warnings)
    if corpus.badge_entries is not None and corpus.badge_entries != stats["linked_entries"]:
        problems.append("entry count differs from the README badge")
    if corpus.badge_benchmarks is not None and corpus.badge_benchmarks != stats["benchmarks"]:
        problems.append("benchmark count differs from the README badge")
    queries = ["false sharing", "branch misprediction penalty", "numa first touch", "roofline", "tail latency p99",
               "auto-vectorisation aliasing", "int8 quantization", "store forwarding", "huge pages tlb", "top-down"]
    times = []
    for _ in range(20):
        for q in queries:
            s = time.perf_counter()
            index.search(q, limit=10)
            times.append((time.perf_counter() - s) * 1000)
    times.sort()
    print(f"cpu-perf {__version__}")
    print(f"source: {corpus.reader.source} ({corpus.reader.describe()})")
    for k, v in stats.items():
        print(f"{k}: {v}")
    print(f"load_ms: {(t1 - t0) * 1000:.1f}")
    print(f"index_ms: {(t2 - t1) * 1000:.1f}")
    print(f"query_ms p50: {statistics.median(times):.3f} p99: {times[int(len(times) * 0.99) - 1]:.3f}")
    for p in problems:
        print(f"PROBLEM: {p}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    commands = {"serve", "index", "status"}
    if "--selftest" in argv:
        args = parser.parse_args(["--selftest"])
        rest = [a for a in argv if a != "--selftest"]
        args.repo = None
        if "--repo" in rest:
            args.repo = rest[rest.index("--repo") + 1]
        return cmd_selftest(args)
    if not argv or argv[0] not in commands and not argv[0] in ("-h", "--help", "--version"):
        argv = ["serve", *argv]
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "log_level", "WARNING"))
    if args.command == "index":
        return cmd_index(args)
    if args.command == "status":
        return cmd_status(args)
    return cmd_serve(args)


if __name__ == "__main__":
    sys.exit(main())
