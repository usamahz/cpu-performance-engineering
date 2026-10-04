# Contributing

Every entry here has to survive one question: **would someone working
through the list top to bottom be worse off without it?** Volume is not the
goal. A pull request that adds a good source to an already-complete
subsection will be asked which existing entry it beats.

## The rules

These are the curation rules, verbatim, as set by the maintainer. They are
not negotiable and they apply to every line of the README.

> - Primary sources only: original papers, vendor optimization manuals and ISA
>   references, creator repos, kernel and compiler documentation. No blogspam, no
>   listicles, no SEO aggregators, no AI-generated posts.
> - Every entry gets one line saying why it earns a place, not what it is.
> - Every performance claim carries: CPU model and microarchitecture, core count,
>   frequency and turbo/SMT state, compiler and flags, workload, baseline, and
>   measurement method. Missing any of those means watchlist or cut. Stricter than the
>   reference, because CPU numbers are easy to get wrong by accident.
> - Every URL resolves to the live canonical source. No dead links, no third-party PDF
>   mirrors where an official one exists.
> - /benchmarks/ — for at least one claim per major section, commit a reproducible
>   microbenchmark I can run myself: source, build script, the machine it ran on, raw
>   numbers, and the analysis. This directory is the part of the repo nobody can fork
>   their way into and it is the whole point.

## Step 1: does the source qualify?

Work down this list. The first line that matches is your answer.

| The source is | Verdict |
|---|---|
| The paper that first described the mechanism | Qualifies. Link the publisher, arXiv, or the author's own page |
| A specification, ISA reference or vendor optimisation manual defining it | Qualifies. Link the vendor's or project's own library |
| The codebase the mechanism is implemented in | Qualifies. Its own home, never a mirror or a repackaging |
| Someone reporting work they did themselves, with code and numbers | Qualifies if the numbers carry all seven fields below |
| Anything restating a mechanism established elsewhere | Rejected. Find what it restates and link that |
| A summary, explainer, tutorial, survey or slide deck | Rejected |
| Marketing copy, a press release, or a vendor blog that is not the definition | Rejected |
| Wikipedia, a Q&A site, an aggregator, an unofficial upload of a talk | Rejected |

When two sources cover the same ground, the one closer to the origin wins.

## Step 2: write the line

One entry occupies exactly one line:

    - [Title](URL) - Why it earns its place.

What goes after the hyphen is the hard part. Write what the source uniquely
establishes, measures, defines or is the home of. "The official x86
optimisation manual" tells a reader nothing they could not guess from the
title; "where Intel states the prefetcher rules a loop must satisfy" tells
them why they would open it.

Constraints the linter enforces: under 120 characters, capital to full
stop, no author names, no numbers, no second person, no em dashes. British
spelling in prose, except `quantization`; titles keep their own spelling.
Start here is numbered, everything else takes bullets, and a watchlist line
must name what would promote it.

## Step 3: if the line carries a number

It needs all seven of these, in the source, stated plainly:

1. CPU model and microarchitecture
2. core count used
3. frequency, and whether turbo (or DVFS) and SMT were on
4. compiler and flags
5. workload
6. baseline
7. measurement method: how timed, how many runs, which statistic

One missing field and the number comes out. If the entry still earns its
place without it, keep the entry and drop the number. If it does not, the
entry belongs on the watchlist with the missing fields named, or nowhere.

This is deliberately stricter than most lists. A CPU figure quoted without
its frequency, its core count or its compiler flags cannot be reproduced
and is therefore not evidence of anything.

## Step 4: open the pull request

Say, briefly:

- which mechanism the source establishes, defines, measures or proves;
- why it is the canonical home for that mechanism, and not a copy of one;
- where it sits in the dependency order, and what it assumes the reader has
  already read;
- which entry it displaces, if its subsection is already full at six;
- whether you have any stake in it, such as having written it or working
  for whoever publishes it.

Run both checkers before you push:

    python3 misc/scripts/check_format.py
    python3 misc/scripts/check_links.py

Both must pass. The link checker labels 401, 403 and 429 as blocked rather
than dead, because Intel, Arm, ACM and several publishers refuse automated
clients while serving the page perfectly well to a browser. If yours comes
back blocked, open it in a browser and say so in the pull request.

## Adding a benchmark

A benchmark directory holds `bench.c`, `build.sh`, `run.sh`, and a README
carrying the claim, the method, the seven fields, the results table and the
analysis, with `results/raw.txt` and `results/summary.md` committed from
the machine the README names. `QUICK=1 ./run.sh` has to finish inside ten
seconds so CI can smoke-test it. `misc/benchmarks/README.md` has the
details. The website charts every benchmark from its `results/raw.txt`
through a short entry in `misc/site/charts.toml` that names the `RESULT`
keys to plot, and its build stops until a new benchmark has one; a
reviewer adds it if the pull request does not.

## How review goes

Arguments are about the source, never about whoever proposed it. Expect to
be asked for the origin of a claim. Expect a good source to be turned down
because a subsection is full, and say so plainly if you think the entry it
would displace is weaker.

The website is rebuilt from the repository on every merge to `main`, so a
change to the list is a change to the README and never to the site.
