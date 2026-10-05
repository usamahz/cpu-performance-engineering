# cpu-perf

An [MCP](https://modelcontextprotocol.io) server that gives any AI client the
whole [CPU Performance Engineering](https://github.com/usamahz/cpu-performance-engineering)
list as something it can search and reason over, instead of a page it has to
be pasted. Connect it to Claude Code, Codex, Claude Desktop, Cursor or VS
Code and use it for your own performance work: ask questions, paste `perf stat` or compiler
output, and the client's own model writes the answer from what the server
returns, with citations back to the sources.

It knows two things.

1. **The repository.** Every entry and its reason, in reading order; the
   watchlist and what would promote each line; the editorial record behind the
   list (every candidate that was considered and left out, with the rule it
   failed; every performance number examined against the seven-field rule,
   with its verdict; the link-verification notes); the fourteen benchmarks
   with their claims, machines, results, analysis, code and raw output; and
   the house rules. This is bundled with the server and loads in a fraction
   of a second.
2. **The sources themselves.** On first run the server reads every source the
   README links, plus the main document behind each link (the PDF behind an
   arXiv abstract, the manual behind a vendor landing page, a repository's
   README, a pull request's description), extracts the text with page numbers,
   and builds a local full-text and semantic index of it. Questions are then
   answered from the papers, manuals and documentation, not from memory.

Nothing is invented on top: the server reads the README, the section drafts
and the benchmarks at start-up, the README stays the product, and no generated
index is committed anywhere.

## Connect it

Your AI client starts the server itself, with [uv](https://docs.astral.sh/uv/):
it runs `uvx cpu-perf`, which fetches the release and starts it. Add that
command to your client once, as below; run in a terminal, it only waits for
a client. (`pip install cpu-perf` works too and gives the same `cpu-perf`
command.)

The first start downloads its dependencies, which can take longer than some
clients wait for a new server. Run `uvx cpu-perf --version` once in a
terminal first, and every client after that starts it in about a second.

| Client | Setup |
|---|---|
| Claude Code | one command |
| Claude Desktop | a few lines of config |
| Codex (CLI, IDE extension, ChatGPT desktop app) | one command |
| Cursor, VS Code | a few lines of config |
| Claude.ai, Claude mobile, ChatGPT on the web | not yet |

Every client above starts the server on your own machine; there is nothing
to host. Claude.ai, the mobile apps and ChatGPT on the web connect only to
servers on the internet, not to a program on your computer, so they cannot
use it yet.

### Claude

**Claude Code**

    claude mcp add --scope user cpu-perf -- uvx cpu-perf

**Claude Desktop**: Settings, Developer, Edit Config, then add to
`claude_desktop_config.json`. Desktop does not always see your shell's
`PATH`, so give the full path that `which uvx` prints:

```json
{
  "mcpServers": {
    "cpu-perf": { "command": "/full/path/to/uvx", "args": ["cpu-perf"] }
  }
}
```

### ChatGPT

The ChatGPT desktop app runs local servers through its Codex host,
configured as below.

### Codex

    codex mcp add cpu-perf -- uvx cpu-perf

or, in `~/.codex/config.toml` (shared by the CLI, the IDE extension and the
ChatGPT desktop app):

```toml
[mcp_servers.cpu-perf]
command = "uvx"
args = ["cpu-perf"]
startup_timeout_sec = 120   # room for the first start's downloads
# Codex starts servers with a minimal environment; behind a proxy, pass it on:
# env_vars = ["HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"]
```

### Cursor and VS Code

**Cursor** (`~/.cursor/mcp.json`) and **VS Code** (`.vscode/mcp.json`,
which names the key `servers` and adds `"type": "stdio"`):

```json
{
  "mcpServers": {
    "cpu-perf": { "command": "uvx", "args": ["cpu-perf"] }
  }
}
```

### What every client sees

The answers are markdown written for a model to read. Claude Code and Codex
show the model only a tool's structured data when a tool returns any, so the
server returns none by default and every client reads the same text
(`--structured-output` adds it back for programmatic use). Every tool is
marked read-only, so no client asks for approval on each call, and slow
reads of large documents return within a minute, finishing in the
background.

Then ask, for example:

- Why does my multithreaded counter stop scaling past two threads?
- Here is my `perf stat` output; where is the time going?
- gcc says "not vectorized: complicated access pattern"; what do I change?
- What does `cycle_activity.stalls_l3_miss` count?
- What does the Intel optimisation manual say about store forwarding?
- Give me a reading path for NUMA, ending with something I can run.
- Why is cppreference not in the list?
- Is "AVX-512 gives 2x on Zen 5" a claim the list would quote?

## Use it for your own work

`ask` takes the question and, optionally, whatever the user pasted as
`context`. The server reads that output itself, with no model involved:

- **`perf stat`** in its plain, `-x` and `-j` forms, per-CPU and interval
  output included: the counters as read, and the ratios computed from them
  (instructions per cycle, frequency, branch, cache and TLB miss rates,
  misses per thousand instructions, stalled-cycle shares, faults and context
  switches per second), each with its formula, computed as perf computes its
  own columns. P-core and E-core counts on hybrid parts are never divided by
  each other.
- **Top-down** level 1 from `perf stat --topdown`, `-M TopdownL1`, the AMD
  `PipelineL1` group, or toplev, and level 2 from `-M TopdownL2`. A level is
  flagged only against a threshold a listed source states: Intel's own values
  from its TMA metrics sheet, applied only to Intel P-cores and cited with
  every flag. Everything else is reported as measured, without a verdict. A
  flagged level sends the answer to the part of the list about it: a
  memory-bound run to the memory hierarchy, a front-end-bound one to fetch
  and decode.
- **The machine:** when the PMUs and event names show Intel, AMD or Arm,
  sources about the other vendors' hardware and tools are left out.
- **How far to trust it:** multiplexed counters (and the lowest running
  share, metric groups included), events that were not counted or not
  supported, how many `-I` intervals were summed, and lines the parser could
  not read, which are listed rather than guessed.
- **perf's own errors:** a missing metric group, `perf_event_paranoid`
  refusals, unknown or unsupported events, the NMI watchdog: each restated
  with what perf itself says to do, instead of being searched for word by
  word.
- **gcc `-fopt-info` and clang `-Rpass` remarks:** why each loop was left
  scalar, counted per loop, routed to the list's auto-vectorisation sources and
  benchmark.
- **Assembly and code:** `objdump -d` with or without the opcode bytes, gdb's
  `disassemble`, `perf annotate`, and source code. The instructions and
  identifiers that matter (gathers, atomics, fences, intrinsics, `alignas`,
  `restrict`) are routed to the matching sections, and so is what a loop does:
  a float sum carried across iterations, which stays one serial chain of adds
  without `-fassociative-math` even when a remark says the loop was vectorised
  (and packed multiplies feeding a run of scalar adds, its shape in assembly),
  an early exit, or fields read from an array of structs.

The event names, remarks and identifiers then steer the search, so the
passages that come back are about the pasted output, not just the question.

Every answer says which of the list's sources it carries text from and which
it does not. Each entry is marked as quoted (with the passages and pages),
in the library but without a matching passage (with the `read_source` call that
looks inside), or not read on this machine (with the reason: blocked, refused
by a proxy, not fetched yet, a talk with only its description). The model is
told to attribute a claim to a source only through a passage it was given, and
to offer an unread source as further reading, never as a citation. A listed
paper the question is about comes with its abstract, and every passage carries
the list's title for its source rather than the document's own, which is often
a placeholder such as "Untitled Document".

Answers are brief by default: passages are trimmed to the part that matches,
the benchmark and the editorial record come only when they are relevant, and
each passage carries an id that `read_source(ref, passage=id)` expands in
full. `detail="full"` returns whole passages and everything related.
Repeated questions are answered from a cache until the library changes.

## The first run: building the library

The server answers from the repository immediately. In the background it
fetches the linked sources into a local library:

- where: `~/.local/share/cpu-perf` on Linux,
  `~/Library/Application Support/cpu-perf` on macOS,
  `%LOCALAPPDATA%\cpu-perf` on Windows, or `CPU_PERF_DATA_DIR`;
- how long: a few minutes to a quarter of an hour, depending on the network
  and the large manuals; the crawl resumes where it stopped if the client
  closes the server;
- how big: one SQLite file of passages, a keyword index and embeddings, a few
  hundred megabytes at most; the downloaded files themselves are not kept;
- what it skips: very large PDFs are indexed up to a page cap and the rest is
  read on demand; scanned PDFs, compressed PostScript and videos have no text
  to index (videos keep their title and description).

To build it in the foreground with progress, run
`cpu-perf index`; `cpu-perf status --detail` lists every source with
its state.

Several MCP clients (Claude Desktop, Claude Code and Cursor at once, say)
share one library. Every few minutes one of them, whichever holds an
operating-system lock on the data folder, does the upkeep: it fetches sources
that are new, due for a refresh or due for a retry, embeds passages that have
no vector, and brings a library built by an older release up to date in
place; a source is fetched again only when a release improves how its kind of
document is read (this one rejoins words PDFs hyphenate across lines). A
refresh that fails keeps the copy already in the library, unless the document
is gone. The lock is released by the system if that client exits or crashes,
and the work pauses while requests arrive.

Some publishers (ACM, IEEE, parts of the Intel and Arm portals) refuse
automated clients or render their documents only in a browser. Those sources
are reported as blocked or partial, with the list's own link notes on why, and
the answer points the reader to the link instead. Coverage is reported as it
is, never padded.

Semantic search uses the small static embedding model
[potion-base-8M](https://huggingface.co/minishlab/potion-base-8M), downloaded
once. Without it (offline, or `CPU_PERF_EMBED_MODEL=none`) the library
falls back to keyword search alone.

### Copyright and politeness

The library is built on the user's own machine, or the operator's own server,
from the public URLs the list links; nothing crawled is committed, published
or shipped in the package or the container image. The crawler fetches only
those documents, identifies itself, waits between requests to one host and
backs off on rate limits. It reads each listed link the way a reader opening
it would, so it does not consult `robots.txt` unless asked to with
`--respect-robots` (`CPU_PERF_RESPECT_ROBOTS=1`); sources a site then
disallows are reported as blocked.

## Tools

| Tool | What it answers |
|---|---|
| `ask` | The evidence for a question: the best passages from the linked sources (with page numbers), the list's entries and reasons, and, when relevant, the matching benchmark and the editorial record. With `context`, the pasted output's metrics and notes too. Call it first. |
| `lookup` | Ranked lookup over entries, sections, benchmarks, the record, notes and benchmark code, or over the sources' text (`scope="sources"`). |
| `search`, `fetch` | Find documents (entries, sections, benchmarks, record items, source passages) by id and read one in full: the pair ChatGPT deep research and company knowledge use. |
| `get_section` | The table of contents, or one section in dependency order with its benchmarks and, for the watchlist, the promotion conditions. |
| `get_entry` | One entry in context: why it is listed, what to read before and after, other places it is listed, its benchmark, the numbers examined in it, alternatives left out, link notes. |
| `reading_path` | What to read, in order, for a topic, ending with the benchmark that reproduces it. |
| `get_benchmark` | A benchmark's claim, machine (the seven fields), results, analysis, limits, code, build and run scripts, raw output and metrics. |
| `editorial_record` | Why something is or is not listed: rejections by rule, claims by verdict, link notes. |
| `check_evidence` | A seven-field audit of a performance claim, with how the list judged similar numbers. |
| `read_source` | The text of one linked source, from the library or fetched now; with `query`, only the matching passages; with `passage`, one passage in full. |
| `read_file` | Any repository file the server carries. |
| `library_status` | Which copy of the list is served, the daily update's state, how much of the linked material is indexed, and what is blocked and why. |

**Resources:** `cpuperf://readme`, `cpuperf://contents`, `cpuperf://rules`,
`cpuperf://watchlist`, `cpuperf://benchmarks`, and the templates
`cpuperf://section/{number}`, `cpuperf://entry/{id}`,
`cpuperf://benchmark/{slug}`, `cpuperf://file/{+path}` and
`cpuperf://source/{id}`.

**Prompts:** `ask_the_list`, `study_plan`, `diagnose` (the list's own method:
the USE method, counters that work, top-down, roofline, then the mechanism),
`audit_claim`, `reproduce_benchmark` and `review_candidate` (pre-screens a
proposed entry against CONTRIBUTING.md).

Entry ids (`4.3.5`, Start here `1.7`) follow the README and change when it
does; every output also carries the URL, which does not.

## Keeping the list current

Once a day (one request shared by every client on the machine) the server
asks GitHub for the newest commit of the list. When there is a newer one it
downloads that commit, keeps only the list's own files (the same set the
package bundles), checks that they parse into a list no smaller than the one
it is serving, and switches to it between two calls. Links the new list adds
are fetched by the next upkeep pass; links it drops leave the answers. An
entry id that now names a different source is flagged in `get_entry`.

Downloaded files are read as data. Nothing from them is imported or run, file
sizes and paths are checked before anything is written, and a copy that does
not parse is kept off with a note in `library_status` to upgrade the server.
A checkout (`--repo`, or running from the repository) is never updated: it is
the copy being edited. `CPU_PERF_AUTO_UPDATE=0` turns the check off;
`CPU_PERF_UPSTREAM=owner/repo` follows a fork instead.

## How it stays honest

- It reads the README with the same grammar as `misc/scripts/check_format.py`;
  a test fails if the two drift apart, and another fails if the parsed counts
  disagree with the README's badges or the changelog's totals.
- The README is authoritative. The section drafts contribute only their
  Rejected, Claims, Link notes and Benchmark proposal blocks, joined by file
  number.
- Benchmark numbers come from one Apple M4 Pro; outputs say so, and the
  server tells the client to quote a number only with all seven fields.
- Text from sources is fenced and labelled as untrusted data.
- Metrics from pasted output are computed exactly as the output shows them,
  and the only thresholds applied are the ones Intel publishes for top-down
  level 1, cited each time.
- A retrieval test set of everyday questions guards the ranking: every change
  must keep its recall (`python tests/eval_queries.py path/to/library.sqlite`
  prints the report).

## Safety of fetching

Only URLs that appear in the repository are read. Every request and every
redirect is checked: http and https on their default ports only, and the host
must resolve to public addresses (no loopback, private, link-local or cloud
metadata addresses); the connection is pinned to the address that was checked.
Downloads and decompression are size-capped and time-boxed. `HTTPS_PROXY` and
`NO_PROXY` are honoured.

## Speed

Everything about the repository is held in memory and every lookup is a
dictionary walk; passages are served from SQLite FTS5 and a matrix of
quantised embeddings. Run `cpu-perf --selftest` to see load, index and
query times on your own machine.

## Configuration

| Variable (flag) | Meaning |
|---|---|
| `CPU_PERF_DATA_DIR` (`--data-dir`) | Where the library lives. |
| `CPU_PERF_EMBED_MODEL` (`--embed-model`) | A model2vec model id, or `none` for keyword search only. |
| `CPU_PERF_AUTO_INDEX=0` (`--no-auto-index`) | Do not build the library in the background. |
| `CPU_PERF_LIVE_FETCH=0` (`--no-live-fetch`) | `read_source` serves only what is indexed. |
| `CPU_PERF_LIBRARY=0` (`--no-library`) | Repository knowledge only. |
| `CPU_PERF_RESPECT_ROBOTS=1` (`--respect-robots`) | Skip what `robots.txt` disallows. By default every listed link is read. |
| `CPU_PERF_REPO` (`--repo`) | Serve a checkout instead of the bundled copy. |
| `CPU_PERF_AUTO_UPDATE=0` (`--no-auto-update`) | Serve the installed copy of the list; no daily check. |
| `CPU_PERF_UPSTREAM` | The `owner/repo` the daily check follows (a fork, say). |
| `CPU_PERF_MAINTENANCE_SECONDS` | How often the upkeep pass runs (default 300). |
| `CPU_PERF_STRUCTURED_OUTPUT=1` (`--structured-output`) | Also return structured data and output schemas, for programmatic clients. |
| `CPU_PERF_LIVE_WAIT_SECONDS` | How long a call waits for a live read before answering "still fetching" (default 40). |
| `CPU_PERF_TRANSPORT`, `_HOST`, `_PORT`, `_PATH` | HTTP serving (`--transport http`). |
| `CPU_PERF_ALLOWED_HOSTS` (`--allowed-host`) | Host names accepted over HTTP. |
| `GITHUB_TOKEN` | Not needed; pull request descriptions come from the public API. |

## Serving over HTTP

Nobody using cpu-perf needs this: every client above starts it locally. It
is for running one shared instance. The same server speaks Streamable HTTP;
from the repository root:

    docker build -f misc/mcp/Dockerfile -t cpu-perf .
    docker run -p 8000:8000 -v cpu-perf-data:/data -e CPU_PERF_ALLOWED_HOSTS=your-host cpu-perf

The endpoint is `/mcp`, with `/healthz` for health checks, and goes behind
HTTPS. Without an allowed host the server refuses requests addressed to any
host but localhost, which is what protects it from DNS rebinding. There is
no authentication, so anyone with the URL can call the tools, all of which
only read. The container builds its library into the `/data` volume on first
start; the image itself carries no crawled text. A public instance serves
passages of other people's work alongside their links, much as a search
engine shows snippets.

## Development

    cd misc/mcp
    pip install -e ".[test]"
    pytest
    cpu-perf --selftest

An editable install reads the checkout, so a README edit shows up on the next
start. The tests need no network: the crawler runs against a local fixture
site and a deterministic embedder, and the daily update against a local
stand-in for GitHub. With `CPU_PERF_EVAL_DB` pointing at a crawled
`library.sqlite`, the retrieval tests also run against real sources.

## Releasing

Set the version in `pyproject.toml`, merge, then tag the merge commit on
`main` with the same version:

    git tag mcp-v0.1.1 && git push origin mcp-v0.1.1

`.github/workflows/mcp-release.yml` builds, tests and publishes to PyPI with
trusted publishing. Once, before the first release: on PyPI add a pending
publisher for project `cpu-perf`, owner `usamahz`, repository
`cpu-performance-engineering`, workflow `mcp-release.yml`, environment
`pypi`. GitHub creates the `pypi` environment on the first run.

A release candidate (`0.1.1rc1`, say) is tagged the same way; it installs
only when asked for by version, with `uvx cpu-perf@0.1.1rc1`, so testing one
never reaches people on the latest release.

The same workflow then lists the release in the
[MCP Registry](https://registry.modelcontextprotocol.io) from `server.json`,
signing in with the workflow's own GitHub identity, so a release needs no
other step. `server.json` carries the same version as `pyproject.toml`. The
registry proves the PyPI package belongs to the listing by finding this line
in the README as PyPI shows it, so it stays here:

    mcp-name: io.github.usamahz/cpu-perf

## Licence

MIT, as the repository. The wheel carries the repository's files and its
LICENSE.
