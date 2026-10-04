"""charts.toml specs, matched against a benchmark's RESULT lines.

A spec names series by regexes with named groups over RESULT keys. Groups
become the x value, the category, the facet, or parts of other keys (a
range's low and high ends, a roofline point's x). Every value plotted is a
RESULT value; nothing is computed or typed in by hand. Anything that does
not line up stops the build with a message naming the benchmark and chart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TYPES = ("line", "scatter", "bar", "dot", "roofline")
CATEGORICAL = ("bar", "dot")
MAX_SERIES = 4  # the validated palette has four slots


class ChartError(Exception):
    pass


@dataclass
class Point:
    series: int
    x: float | str
    y: float
    facet: str | None
    key: str
    unit: str
    low: float | None = None
    high: float | None = None
    label: str = ""


@dataclass
class Ref:
    axis: str  # x | y | diagonal
    value: float
    label: str  # may hold {value}, filled with the axis format when drawn
    facet: str | None = None
    source: str = ""  # the RESULT key or raw.txt header line it came from
    dash: int = 0
    unit: str = ""


@dataclass
class Chart:
    id: str
    benchmark: str
    type: str
    title: str
    metric: str
    spec: dict
    series: list[dict]
    points: list[Point]
    refs: list[Ref]
    facets: list[str | None]
    facet_labels: dict = field(default_factory=dict)
    facet_units: dict = field(default_factory=dict)
    svg: str = ""
    table: str = ""
    ref_table: str = ""
    legend: list = field(default_factory=list)
    marks: int = 0

    @property
    def log(self) -> bool:
        return self.type == "roofline" or any(
            self.spec.get(a, {}).get("scale") in ("log2", "log10") for a in ("x", "y"))

    def unit(self, facet: str | None) -> str:
        if facet in self.facet_units:
            return self.facet_units[facet]
        unit = self.spec.get("y", {}).get("unit")
        if unit:
            return unit
        units = {p.unit for p in self.points if p.facet == facet}
        return units.pop() if len(units) == 1 else ""


def fill(template: str, groups: dict) -> str:
    try:
        return template.format(**groups)
    except KeyError as exc:
        raise ChartError(f"template {template!r} names group {exc} that the match did not capture") from exc


class Results:
    """A benchmark's RESULT rows, looked up by key with segment checks."""

    def __init__(self, slug: str, rows: list[dict], header: dict):
        self.slug = slug
        self.rows = rows
        self.header = header
        self.by_key: dict[str, list[dict]] = {}
        for r in rows:
            self.by_key.setdefault(r["key"], []).append(r)

    def one(self, key: str, segment: int | None = None, where: str = "") -> dict:
        rows = self.by_key.get(key, [])
        if segment is not None:
            rows = [r for r in rows if r["segment"] == segment]
        if not rows:
            raise ChartError(f"{self.slug}{where}: no RESULT line with key {key!r}")
        if len(rows) > 1:
            segs = sorted({r["segment"] for r in rows})
            raise ChartError(f"{self.slug}{where}: key {key!r} appears in segments {segs}; give it a segment")
        return rows[0]

    def number(self, key: str, segment: int | None = None, where: str = "") -> float:
        row = self.one(key, segment, where)
        if row["number"] is None:
            raise ChartError(f"{self.slug}{where}: RESULT {key!r} is {row['value']!r}, not a number")
        return row["number"]

    def substitute(self, text: str, groups: dict, where: str = "") -> str:
        """'{t}' takes a captured group; '{=t[t]_cond_true}' takes the value of
        that RESULT key (square brackets standing for braces inside it), so a
        label can quote the run without retyping it. '{value}' is left for the
        renderer, which formats a reference line's value for its axis."""

        def value(m: re.Match) -> str:
            key = fill(m.group(1).replace("[", "{").replace("]", "}"), groups)
            return self.one(key, where=where)["value"]

        text = re.sub(r"\{=([^{}]+)\}", value, text)
        if "{" not in text:
            return text
        return fill(text, {**groups, "value": "{value}"})


def _x_value(raw: str, categorical: bool) -> float | str:
    if categorical:
        return raw
    try:
        return float(raw)
    except ValueError as exc:
        raise ChartError(f"x value {raw!r} is not a number; give the axis scale = \"category\"") from exc


def build_chart(spec: dict, slug: str, rows: list[dict], header: dict) -> Chart:
    where = f" chart {spec.get('id', '?')!r}"
    for required in ("id", "title", "type", "series"):
        if required not in spec:
            raise ChartError(f"{slug}{where}: the spec has no {required!r}")
    ctype = spec["type"]
    if ctype not in TYPES:
        raise ChartError(f"{slug}{where}: type {ctype!r} is not one of {', '.join(TYPES)}")
    if len(spec["series"]) > MAX_SERIES:
        raise ChartError(f"{slug}{where}: {len(spec['series'])} series; the validated palette has {MAX_SERIES} slots")
    res = Results(slug, rows, header)
    x = spec.get("x", {})
    y = spec.get("y", {})
    facet = spec.get("facet")
    categorical = ctype in CATEGORICAL or x.get("scale") == "category"
    facet_units = {str(k): v for k, v in (facet or {}).get("units", {}).items()}
    if facet_units and y.get("unit"):
        raise ChartError(f"{slug}{where}: give either y.unit or facet.units, not both")
    if ctype == "roofline" and not facet_units and not y.get("unit"):
        raise ChartError(f"{slug}{where}: a roofline needs y.unit")

    points: list[Point] = []
    for si, s in enumerate(spec["series"]):
        rx = re.compile(s["match"])
        seg = s.get("segment")
        matched = 0
        for r in rows:
            if seg is not None and r["segment"] != seg:
                continue
            m = rx.match(r["key"])
            if not m:
                continue
            if r["number"] is None:
                raise ChartError(f"{slug}{where}: {r['key']} = {r['value']!r} is not a number")
            if seg is None and len(res.by_key[r["key"]]) > 1:
                raise ChartError(f"{slug}{where}: key {r['key']!r} repeats across segments; give the series a segment")
            g = m.groupdict()
            lookup_seg = seg
            if s.get("x_key"):
                xv: float | str = res.number(fill(s["x_key"], g), lookup_seg, where)
            else:
                raw = g.get(x.get("from", "")) if x.get("from") else None
                if raw is None:
                    raise ChartError(f"{slug}{where}: series {s['name']!r} captures no group {x.get('from')!r} for x")
                xv = _x_value(raw, categorical)
            if facet:
                fv = g.get(facet["from"])
                if fv is None and not s.get("every_facet"):
                    raise ChartError(f"{slug}{where}: series {s['name']!r} captures no facet group {facet['from']!r}; "
                                     "set every_facet = true to draw it in every panel")
            else:
                fv = None
            lo = res.number(fill(s["low"], g), lookup_seg, where) if s.get("low") else None
            hi = res.number(fill(s["high"], g), lookup_seg, where) if s.get("high") else None
            label = fill(s["point_label"], g) if s.get("point_label") else ""
            points.append(Point(si, xv, r["number"], fv, r["key"], r["unit"], lo, hi, label))
            matched += 1
        if matched == 0:
            raise ChartError(f"{slug}{where}: series {s['name']!r} matches no RESULT line ({s['match']})")
        if matched < spec.get("min_points", 1):
            raise ChartError(f"{slug}{where}: series {s['name']!r} matched {matched} lines, fewer than min_points")

    # ---- facets
    facets: list[str | None]
    facet_labels: dict = {}
    if facet:
        present = {p.facet for p in points if p.facet is not None}
        order = [str(f) for f in facet.get("order", sorted(present))]
        missing = present - set(order)
        if missing:
            raise ChartError(f"{slug}{where}: facet values {sorted(missing)} are not in facet.order")
        facets = [f for f in order if f in present]
        expanded = []
        for p in points:
            if p.facet is None:  # an every_facet series
                expanded += [Point(p.series, p.x, p.y, f, p.key, p.unit, p.low, p.high, p.label) for f in facets]
            else:
                expanded.append(p)
        points = expanded
        for f in facets:
            groups = {facet["from"]: f}
            label = facet.get("labels", {}).get(f, facet.get("label", "{" + facet["from"] + "}"))
            facet_labels[f] = res.substitute(label, groups, where)
        for f in facets:
            if facet_units and f not in facet_units:
                raise ChartError(f"{slug}{where}: facet {f!r} has no entry in facet.units")
    else:
        facets = [None]

    # ---- units, categories, duplicates, log axes
    for p in points:
        want = facet_units.get(p.facet) if facet_units else y.get("unit")
        if want and p.unit != want:
            raise ChartError(f"{slug}{where}: {p.key} is in {p.unit!r}, the axis is in {want!r}")
    if not facet_units and not y.get("unit"):
        for f in facets:
            units = {p.unit for p in points if p.facet == f}
            if len(units) > 1:
                raise ChartError(f"{slug}{where}: one axis would mix the units {sorted(units)}; set y.unit or facet.units")
    if categorical and x.get("order"):
        order = [str(o) for o in x["order"]]
        stray = sorted({str(p.x) for p in points} - set(order))
        if stray:
            raise ChartError(f"{slug}{where}: x values {stray} are not in x.order, so they would not be drawn")
    seen: dict[tuple, str] = {}
    for p in points:
        k = (p.series, p.facet, p.x, p.label)
        if k in seen:
            raise ChartError(f"{slug}{where}: {p.key} and {seen[k]} land on the same mark")
        seen[k] = p.key
    for axis_name, axis in (("x", x), ("y", y)):
        if axis.get("scale") in ("log2", "log10") or ctype == "roofline":
            for p in points:
                v = p.x if axis_name == "x" else p.y
                if isinstance(v, (int, float)) and v <= 0:
                    raise ChartError(f"{slug}{where}: {p.key} = {v} cannot sit on a log axis")

    # ---- reference lines
    refs: list[Ref] = []
    for ri, ref in enumerate(spec.get("refs", [])):
        for f in facets:
            groups = {facet["from"]: f} if facet and f is not None else {}
            if "key" in ref:
                key = fill(ref["key"], groups)
                value = res.number(key, ref.get("segment"), where)
                unit = res.one(key, ref.get("segment"), where)["unit"]
                source = f"RESULT {key}"
            else:
                text = res.header.get(ref["header"])
                if text is None:
                    raise ChartError(f"{slug}{where}: raw.txt header has no line {ref['header']!r}")
                m = re.search(ref["pattern"], text)
                if not m:
                    raise ChartError(f"{slug}{where}: {ref['pattern']!r} finds nothing in header line {text!r}")
                value = float(m.group(1)) * float(ref.get("scale", 1))
                unit = ref.get("unit", "")
                source = f"raw.txt header, {ref['header']}"
            label = res.substitute(ref.get("label", ""), groups, where)
            axis = ref.get("axis", "y")
            if axis not in ("x", "y", "diagonal"):
                raise ChartError(f"{slug}{where}: reference axis {axis!r} is not x, y or diagonal")
            refs.append(Ref(axis, value, label, f, source, int(ref.get("dash", ri)), unit))
            if not facet:
                break

    series = []
    for i, s in enumerate(spec["series"]):
        series.append({
            "name": res.substitute(s["name"], {}, where),
            "short": res.substitute(s["short"], {}, where) if s.get("short") else "",
            "cls": f"s{i}",
        })
    return Chart(
        id=spec["id"], benchmark=slug, type=ctype,
        title=res.substitute(spec["title"], {}, where),
        metric=res.substitute(spec.get("metric", y.get("label", "")), {}, where),
        spec=spec, series=series, points=points, refs=refs, facets=facets,
        facet_labels=facet_labels, facet_units=facet_units,
    )
