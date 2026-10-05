# site

The website for the list, generated from this repository at one commit
and published to GitHub Pages. The README stays the product: every page is
built from the README, CONTRIBUTING.md, `misc/benchmarks/`, the section
drafts in `misc/notes/sections/` and `misc/mcp/README.md`, adds no entry,
claim or number of its own, and is never edited by hand. Nothing generated
is committed.

## Build it

From the repository root, with Python 3.11 or later:

    pip install -e misc/site ./misc/mcp
    python misc/site/scripts/export_corpus.py      # build/export.json
    python misc/site/scripts/export_mcp.py         # build/mcp-surface.json
    python -m cpu_perf_site build                  # dist/
    python -m cpu_perf_site check                  # the checks below
    python -m cpu_perf_site serve                  # http://localhost:8000, rebuilt on change

`export_corpus.py` is the only code that parses the repository, through
`cpu_perf.corpus` from `misc/mcp/src`, the same parser the MCP server uses;
it needs only the standard library. `export_mcp.py` starts the server over
stdio and records what it lists (tools, prompts, resources, templates), so
the MCP pages cannot describe something the server does not have. Pass
`--base-url https://cpuperf.com` to `build` for absolute URLs in the
sitemap, the feeds and the Markdown twins.

## What it publishes

| Path | From |
|---|---|
| `/`, `/learn/`, `/learn/<section>/`, `/learn/all/`, `/watchlist/` | README.md |
| `/benchmarks/`, `/benchmarks/<slug>/` | `misc/benchmarks/`, with charts drawn from `results/raw.txt` |
| `/evidence/`, `/evidence/record/`, `/evidence/record/link-notes/` | README.md, CONTRIBUTING.md, the section drafts |
| `/mcp/` and five pages under it | `misc/mcp/README.md` and the server's own lists |
| `/search/` | `search.json`, built from the same data |
| `<page>.md`, `llms.txt`, `llms-full.txt` | Markdown twins of every page, for agents |
| `corpus.json`, `schema/corpus-v1.json` | the parsed list, benchmarks and record as JSON |
| `anchors.json` | every README heading anchor and the page that carries it |

A link to `README.md#some-heading` keeps working: the page that carries the
heading uses the same id, and `/#some-heading` redirects there.

## Checks

`python -m cpu_perf_site check` reads `dist/` as a browser would and fails
on any of these, naming the page:

- a section page that shows a different set of entries from the README, or
  lacks a link to one of them;
- a README heading whose anchor is not where `anchors.json` says;
- a count that disagrees with an independent markdown-it walk of the README;
- a Markdown twin that is not the README's own lines, or a data file or
  sitemap entry that points at nothing;
- an internal link or fragment that does not resolve;
- a benchmark whose passport lacks a field, whose chart draws a different
  number of marks from its data table, or whose README results differ from
  `results/summary.md`;
- a record page missing an item, or an MCP page naming a prompt the server
  does not list;
- a page without the Content-Security-Policy, with an inline style, loading
  anything from another origin, or over its size budget (`site.toml`).

`tests/test_site.py` seeds each of those defects into a copy of a real build
and asserts the check catches it. `tests/e2e/test_smoke.py` opens every
page type in Chrome at 1280 and 390 pixels, light and dark, runs axe-core,
and exercises the filters, progress, tabs, copy buttons, search and chart
tooltips, with and without JavaScript. `scripts/check_copy.py` lints the
site's own words (`copy.toml`, `charts.toml`) against
`misc/notes/voice.md`, and `scripts/check_github_anchors.py` compares the
heading anchors with the ones GitHub's renderer produces.

## Adding a benchmark

Every benchmark needs at least one chart in `charts.toml`, or the build
stops. A chart names RESULT keys by regex and never contains a number: the
values, the reference lines and the labels that quote a value all come from
`results/raw.txt`, so a new run redraws it with no edit. The comment at the
top of `charts.toml` lists the keys; the build reports a series that
matches nothing, a unit that disagrees with its axis, a key repeated across
`---` segments, and a value that cannot sit on a log axis.

## Layout

- `site.toml`: navigation, the reading-path groups, reserved slugs, budgets.
- `copy.toml`: every string the site writes itself.
- `charts.toml`: one or more chart specs per benchmark.
- `cpu_perf_site/`: the generator (`data.py` view models, `pages.py`,
  `charts/` for the SVG charts, `agents.py` for the twins and data files,
  `seo.py`, `check.py`).
- `templates/`, `static/`: Jinja templates, one stylesheet, seven small
  scripts and self-hosted fonts (Instrument Sans and JetBrains Mono, both
  under the SIL Open Font License, with their licence texts beside them).
  GitHub's mark in the header, hero and footer is `mark-github-16` from
  Primer Octicons (MIT), inline in `templates/_icons.html`.
