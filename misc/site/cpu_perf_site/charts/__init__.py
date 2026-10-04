"""Benchmark charts: charts.toml specs over RESULT lines, drawn as static SVG.

Every benchmark needs at least one chart, and every chart names a benchmark
that exists, so adding a benchmark without its chart, or renaming one,
stops the build instead of publishing a page with a hole in it.
"""

from __future__ import annotations

from .spec import ChartError, build_chart
from .svg import render

__all__ = ["ChartError", "attach"]


def attach(site) -> None:
    by_bench: dict[str, list[dict]] = {}
    for spec in site.config.charts:
        slug = spec.get("benchmark")
        if slug not in site.bench_by_slug:
            raise ChartError(f"charts.toml: chart {spec.get('id')!r} names benchmark {slug!r}, "
                             "which is not a directory under misc/benchmarks/")
        by_bench.setdefault(slug, []).append(spec)
    missing = [b.slug for b in site.benchmarks if b.slug not in by_bench]
    if missing:
        raise ChartError("charts.toml has no chart for " + ", ".join(missing)
                         + "; every benchmark needs one (CONTRIBUTING.md, \"Adding a benchmark\")")
    for b in site.benchmarks:
        if not b.passport_filled:
            raise ChartError(f"{b.slug}: the README states none of the seven fields, and a chart is only "
                             "drawn beside its measurement passport")
        ids = [s.get("id") for s in by_bench[b.slug]]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ChartError(f"charts.toml: {b.slug} has more than one chart with id {dupes}")
        b.charts = []
        for spec in by_bench[b.slug]:
            chart = build_chart(spec, b.slug, b.results, b.raw_header)
            render(chart)
            b.charts.append(chart)
