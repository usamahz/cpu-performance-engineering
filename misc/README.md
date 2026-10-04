# misc

Everything the list is built from and checked with. The list itself is
the [README](../README.md) at the repository root; this directory keeps
the supporting material out of the root listing.

| Directory | What it holds |
|---|---|
| [benchmarks/](benchmarks/README.md) | The fourteen microbenchmarks, one per numbered section, each with source, build line, run script, machine description and raw numbers. Every "Reproduce it" line in the README points here. |
| [notes/](notes/status.md) | The working record: the briefs the section owners wrote from, the sixteen section drafts with their Rejected and Claims blocks, the generated changelog, and the build status. |
| [scripts/](scripts/) | `check_format.py` (entry format and anchors), `check_links.py` (every URL is live) and `build_changelog.py`. The first two run in CI on every push. |
| [mcp/](mcp/README.md) | The MCP server, `cpu-perf`, that serves the README, the drafts' Rejected, Claims and Link notes, the notes and the benchmarks to an AI client, and builds a searchable index of the linked sources on the user's own machine. It reads these files when it starts and never writes to the repository. |
| [site/](site/README.md) | The website: every page generated at one commit from the README, the benchmarks, the drafts and the MCP server's own lists, checked against the README, and published to GitHub Pages on every merge. Nothing it builds is committed. |
| `banner-pinnacle-ridge.avif` | The banner at the top of the README; renderer and provenance in [notes/banner/](notes/banner/README.md). |

Run the checkers from the repository root:

    python3 misc/scripts/check_format.py
    python3 misc/scripts/check_links.py
