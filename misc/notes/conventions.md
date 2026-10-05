# Conventions

The house rules for this list. Anything the checkers cannot enforce is
written down here.

## What the list is

A single README that is a reading path first and a reference second. The
README is the whole product: no generated index and no per-topic pages are
committed, and nothing is written anywhere first and copied in. The
website built from `misc/site/` is a rendering of the README and the files
beside it at one commit: it adds no entry, claim or number, it is never
edited by hand, and its build fails when a page drifts from the README.
Everything else in the repository exists to keep the README honest, namely
the format linter, the link checker, the benchmarks and the contribution
rules.

## Ordering

The list follows one instruction through the machine, then widens:

1. **1. Start here**, ten numbered items, read top to bottom, each
   assuming only the ones before it;
2. numbered sections that go **down** (the core, the memory hierarchy,
   measurement, models) and then **out** (one thread, the compiler, many
   threads, NUMA, the kernel boundary, tail latency, CPU inference, the
   parts themselves, the benchmark suites);
3. a dated **16. Watchlist** for things whose evidence is still moving;
4. **What earns a place**, which states the admission rule.

Sections are H2, subsections H3, and every H3 is a cluster of three to six
entries. No H4s, no tier headings, no checkpoints; the linter rejects the
last two. Order inside a subsection is dependency order, never importance
and never date.

## Entry format

One entry is exactly one line:

    - [Title](URL) - Why it earns its place.

- A hyphen with a space either side separates the link from the reason.
- The reason says **why the entry earns its place**, not what it is. "The
  normative x86 reference" describes; "the only public per-instruction
  latency table that is measured rather than quoted" is a reason.
- Under 120 characters, one sentence or fragment, capital to full stop.
- No author names, no numbers, no praise adjectives, no second person.
- Titles are the source's own, trimmed to the searchable part. Section
  names are sentence case.
- Numbered lists only in Start here, where the order is the point;
  bullets everywhere else.
- A section preamble is at most one sentence and appears only where the
  reader needs a warning before the links, such as the hardware section
  saying vendor generation-on-generation percentages are not measurements.

## What stays out

- Aggregators, listicles, SEO summaries and AI-generated explainers.
- Summaries, tutorials and surveys: secondary by definition.
- Practitioner blogs as such, and communities. A post enters only when it
  is the original report of a mechanism or a measurement by the person who
  did the work.
- Leaderboards without a hardened evaluator.
- Marketing pages and vendor posts that are not the canonical home of a
  mechanism's definition.
- Third-party mirrors where an official copy exists, and paywalled copies
  where the author hosts one.
- Author bylines inside reasons: they cost width and invite name-dropping.
- The same URL twice inside one subsection; the linter rejects it. A URL
  may appear in two different sections when each reason names a different
  mechanism.

## Evidence

A CPU number is meaningless without the parts of the machine that vary run
to run, so seven fields are required before any number may be stated:

1. CPU model and microarchitecture
2. core count used
3. frequency, and whether turbo and SMT were on
4. compiler and flags
5. workload
6. baseline
7. method: how measured, how many runs, which statistic

Any number missing any field is dropped, not softened and not caveated. If
the entry rests on that number it moves to the watchlist or is cut. This
applies to numbers in reasons and to numbers in `misc/benchmarks/`.

## Watchlist against core

The watchlist sits outside the numbered core, carries a checked-on date,
and every line states the condition that would promote it. An item enters
the core only when three things exist at once: a specification or an
original paper, a shipped implementation, and a public measurement that
states all seven fields. A claim that fails the seven-field test lands
here rather than in the core even when the mechanism itself is real.

## Tooling

- `misc/scripts/check_format.py` runs on every push: entry grammar, reason
  length, Start here numbering, watchlist promotion conditions, internal
  anchors, Contents completeness, relative link targets, no duplicate URL
  within a subsection, no empty subsection, no em dashes or placeholders.
- `misc/scripts/check_links.py` runs on every push and again weekly, with
  no third-party dependency. It separates dead (gone) from unreachable
  (the network here) and from blocked (401, 403, 429), because vendor
  document libraries and publishers refuse automated clients while serving
  the page to a browser. A dead link fails the build and opens an issue.
- `misc/scripts/build_changelog.py` regenerates the record of what was
  included, what was rejected and why.
- Issue templates for adding an entry, a dead or moved link, and an
  evidence concern. The pull request template asks the four admission
  questions and the seven fields.
- `misc/mcp/` is a read-only MCP server. It parses the README with the same
  grammar as `check_format.py`, plus the drafts, the notes and the benchmarks,
  when it starts, and its tests fail when the two drift apart. Its index
  lives in memory and in a library each user builds from the linked URLs on
  their own machine; nothing generated is committed, and the README stays the
  whole product.
- `misc/site/` builds the website with the MCP server's parser, from the
  README, the benchmarks, the drafts and the server's own tool list, and
  publishes it on Vercel on every merge to `main`. Its check fails
  when a page loses an entry, an anchor or a chart value, or when its
  counts disagree with an independent walk of the README; nothing it
  generates is committed.
