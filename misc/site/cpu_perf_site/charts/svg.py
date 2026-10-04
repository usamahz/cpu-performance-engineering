"""Static SVG for benchmark charts.

Marks follow the site's chart rules: hairline solid gridlines, 2px lines,
dots of radius 4 with a 2px ring in the surface colour, bars no thicker than
24px with a rounded data end and a square baseline, one y axis per panel,
reference lines in muted ink, and text in text colours only. Every mark
carries a native <title>, a data-tip for the tooltip script and a hit area
larger than the mark; every chart has a legend when it has two or more
series, and a table with every value it plots.
"""

from __future__ import annotations

import html
import math

from .spec import Chart, Point, Ref

TOP = 28  # room for the y-axis label above the plot
BOTTOM = 46  # tick labels and the x-axis label
RIGHT = 16
CHAR = 7.2  # advance of one 12px JetBrains Mono character
LINE = 14  # line height of wrapped labels
WIDE, NARROW = 760, 400  # viewBox widths; a figure shows the one that fits it (site.css)
PT_CHAR = 6.3  # advance of one 10.5px point-label character


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def num(v: float) -> str:
    """Values as the README prints them: up to four significant figures,
    thousands separated, never in exponent form."""
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    digits = max(0, 3 - int(math.floor(math.log10(a))))
    s = f"{v:.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def fmt_bytes(v: float) -> str:
    for unit, size in (("GiB", 2 ** 30), ("MiB", 2 ** 20), ("KiB", 2 ** 10)):
        if v >= size:
            return f"{num(v / size)} {unit}"
    return f"{num(v)} B"


def fmt(v, kind: str | None) -> str:
    if isinstance(v, str):
        return v
    if kind == "bytes":
        return fmt_bytes(v)
    return num(v)


def c(v: float) -> str:
    """A coordinate, rounded so the output is the same on every run."""
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def text_width(s: str) -> float:
    return len(s) * CHAR


def wrap(label: str, width: float, max_lines: int = 3) -> list[str]:
    """Greedy word wrap for tick and row labels."""
    per_line = max(4, int(width // CHAR))
    lines: list[str] = []
    for word in label.split(" "):
        if lines and len(lines[-1]) + 1 + len(word) <= per_line:
            lines[-1] += " " + word
        else:
            lines.append(word)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return lines


# ------------------------------------------------------------------ scales


class Scale:
    def __init__(self, kind: str, lo: float, hi: float, a: float, b: float):
        self.kind, self.lo, self.hi, self.a, self.b = kind, lo, hi, a, b

    def __call__(self, v: float) -> float:
        if self.kind in ("log2", "log10"):
            lo, hi, v = math.log(self.lo), math.log(self.hi), math.log(max(v, self.lo))
        else:
            lo, hi = self.lo, self.hi
        if hi == lo:
            return (self.a + self.b) / 2
        return self.a + (v - lo) / (hi - lo) * (self.b - self.a)


def nice_step(span: float, target: int = 5) -> float:
    raw = span / max(1, target)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def linear_ticks(lo: float, hi: float, zero: bool, target: int = 5) -> tuple[float, float, list[float]]:
    if zero:
        lo, hi = min(0.0, lo), max(0.0, hi)
    if hi == lo:
        hi = lo + 1
    step = nice_step(hi - lo, target)
    lo2 = math.floor(lo / step + 1e-9) * step
    hi2 = math.ceil(hi / step - 1e-9) * step
    n = int(round((hi2 - lo2) / step))
    return lo2, hi2, [round(lo2 + i * step, 10) for i in range(n + 1)]


def log_ticks(lo: float, hi: float, base: int, kind: str | None, max_ticks: int = 7) -> tuple[float, float, list[float]]:
    if base == 2:
        e0, e1 = math.floor(math.log2(lo)), math.ceil(math.log2(hi))
        if e1 == e0:
            e1 += 1
        step = 1
        while (e1 - e0) / step + 1 > max_ticks:
            step *= 2
        return 2.0 ** e0, 2.0 ** e1, [2.0 ** e for e in range(e0, e1 + 1, step)]
    # A log10 axis fits the data with a fifth of headroom each side, and its
    # gridlines sit on the decades inside (with 2 and 5 between them when the
    # axis spans two decades or less), so no decade of empty plot is drawn.
    lo2, hi2 = lo / 1.2, hi * 1.2
    e0, e1 = math.floor(math.log10(lo2)), math.ceil(math.log10(hi2))
    for mults in ((1,), (1, 2, 5), (1, 2, 3, 5)):
        ticks = sorted({round(m * 10.0 ** e, 12) for e in range(e0, e1 + 1) for m in mults
                        if lo2 <= m * 10.0 ** e <= hi2})
        if len(ticks) >= 3:
            break
    return lo2, hi2, ticks


def axis_scale(spec: dict, values: list[float], a: float, b: float, zero_default: bool) -> tuple[Scale, list[float]]:
    kind = spec.get("scale", "linear")
    lo, hi = min(values), max(values)
    if kind in ("log2", "log10"):
        lo2, hi2, ticks = log_ticks(lo, hi, 2 if kind == "log2" else 10, spec.get("format"))
        return Scale(kind, lo2, hi2, a, b), ticks
    lo2, hi2, ticks = linear_ticks(lo, hi, spec.get("zero", zero_default))
    return Scale("linear", lo2, hi2, a, b), ticks


# ------------------------------------------------------------------ pieces


class Marks:
    """Hit areas for one chart: the first is in the tab order, the rest are
    reached with the arrow keys (tooltip.js), so a chart is one tab stop."""

    def __init__(self):
        self.count = 0

    def circle(self, cx: float, cy: float, label: str) -> str:
        tab = 0 if self.count == 0 else -1
        self.count += 1
        return (f'<circle class="mark" cx="{c(cx)}" cy="{c(cy)}" r="12" tabindex="{tab}" '
                f'data-tip="{esc(label)}"><title>{esc(label)}</title></circle>')

    def rect(self, x: float, y: float, w: float, h: float, label: str) -> str:
        tab = 0 if self.count == 0 else -1
        self.count += 1
        return (f'<rect class="mark" x="{c(x)}" y="{c(y)}" width="{c(w)}" height="{c(h)}" tabindex="{tab}" '
                f'data-tip="{esc(label)}"><title>{esc(label)}</title></rect>')


def bar_path(x: float, base: float, end: float, w: float) -> str:
    """A vertical bar from the baseline to its data end, rounded 4px at the
    data end only."""
    r = min(4.0, abs(base - end), w / 2)
    if r <= 0:
        return f"M{c(x)},{c(base)}H{c(x + w)}"
    return (f"M{c(x)},{c(base)}V{c(end + r)}Q{c(x)},{c(end)} {c(x + r)},{c(end)}"
            f"H{c(x + w - r)}Q{c(x + w)},{c(end)} {c(x + w)},{c(end + r)}V{c(base)}Z")


def svg_open(w: float, height: float, title: str, desc: str, uid: str) -> str:
    cls = "chart narrow" if w == NARROW else "chart"
    return (f'<svg class="{cls}" viewBox="0 0 {c(w)} {c(height)}" role="img" aria-labelledby="{uid}-t {uid}-d" '
            f'xmlns="http://www.w3.org/2000/svg"><title id="{uid}-t">{esc(title)}</title>'
            f'<desc id="{uid}-d">{esc(desc)}</desc>')


def x_label_for(chart: Chart, v) -> str:
    x = chart.spec.get("x", {})
    if isinstance(v, str):
        return x.get("labels", {}).get(v, v)
    return fmt(v, x.get("format"))


def ref_value(chart: Chart, r: Ref) -> str:
    """A reference line's value with its unit: bytes in KiB and MiB, anything
    else with the unit of the RESULT line it came from."""
    axis = chart.spec.get("x" if r.axis == "x" else "y", {})
    if axis.get("format") == "bytes":
        return fmt_bytes(r.value)
    unit = r.unit or ("" if r.axis == "x" else chart.unit(r.facet))
    return f"{num(r.value)} {unit}".strip()


def ref_label(chart: Chart, r: Ref) -> str:
    return r.label.replace("{value}", ref_value(chart, r))


def tip(chart: Chart, p: Point) -> str:
    unit = chart.unit(p.facet)
    value = f"{num(p.y)} {unit}".strip()
    if p.low is not None and p.high is not None:
        value += f" (from {num(p.low)} to {num(p.high)})"
    parts = []
    if len(chart.series) > 1:
        parts.append(chart.series[p.series]["name"])
    if p.facet is not None:
        parts.append(chart.facet_labels.get(p.facet, p.facet))
    if p.label:
        parts.append(p.label)
    if chart.type == "roofline":
        parts.append(f"{num(p.x)} {chart.spec.get('x', {}).get('unit', '')}".strip())
    else:
        parts.append(x_label_for(chart, p.x))
    return " · ".join(parts) + ": " + value


def y_axis(out: list, ys: Scale, ticks: list[float], yfmt, left: float, right: float) -> None:
    for t in ticks:
        y = ys(t)
        out.append(f'<line class="grid" x1="{c(left)}" x2="{c(right)}" y1="{c(y)}" y2="{c(y)}"/>')
        out.append(f'<text x="{c(left - 8)}" y="{c(y + 4)}" text-anchor="end">{esc(fmt(t, yfmt))}</text>')


def axis_title(out: list, text: str, x: float, y: float, anchor: str = "start") -> None:
    if text:
        out.append(f'<text class="axis-title" x="{c(x)}" y="{c(y)}" text-anchor="{anchor}">{esc(text)}</text>')


# ------------------------------------------------------------------ forms


def render_line(chart: Chart, facet, uid: str, marks: Marks, w: float) -> str:
    sx, sy = chart.spec.get("x", {}), chart.spec.get("y", {})
    pts = [p for p in chart.points if p.facet == facet]
    refs = [r for r in chart.refs if r.facet == facet]
    category = sx.get("scale") == "category"
    ph = chart.spec.get("height", 240)
    top, bottom = TOP, TOP + ph
    height = bottom + BOTTOM
    yvals = [p.y for p in pts] + [v for p in pts for v in (p.low, p.high) if v is not None]
    yvals += [r.value for r in refs if r.axis == "y"]
    ys, yticks = axis_scale(sy, yvals, bottom, top, zero_default=False)
    left = max(text_width(fmt(t, sy.get("format"))) for t in yticks) + 16
    direct = chart.type == "line" and len(chart.series) >= 2 and all(s["short"] for s in chart.series)
    right = w - (max(text_width(s["short"]) for s in chart.series) + 18 if direct else RIGHT)
    x0, x1 = left + 10, right - 10
    if category:
        order = [str(o) for o in sx.get("order", [])] or sorted({str(p.x) for p in pts})
        step = (x1 - x0) / max(1, len(order))
        xpos = {o: x0 + step * (i + 0.5) for i, o in enumerate(order)}
        xticks: list = order
    else:
        xvals = [p.x for p in pts] + [r.value for r in refs if r.axis == "x"]
        xs, xticks = axis_scale(sx, xvals, x0, x1, zero_default=False)
        if sx.get("ticks") == "data":
            xticks = sorted({p.x for p in pts})

    def X(v):
        return xpos[str(v)] if category else xs(v)

    out = [svg_open(w, height, chart.title, describe(chart, facet), uid)]
    y_axis(out, ys, yticks, sy.get("format"), left, right)
    out.append(f'<line class="axis" x1="{c(left)}" x2="{c(right)}" y1="{c(bottom)}" y2="{c(bottom)}"/>')
    for t in xticks:
        out.append(f'<text x="{c(X(t))}" y="{c(bottom + 18)}" text-anchor="middle">{esc(x_label_for(chart, t))}</text>')
    axis_title(out, sx.get("label", ""), (left + right) / 2, height - 6, "middle")
    axis_title(out, sy.get("label", ""), 4, 14)
    for r in refs:
        label = ref_label(chart, r)
        if r.axis == "x" and not category:
            x = xs(r.value)
            out.append(f'<line class="ref" x1="{c(x)}" x2="{c(x)}" y1="{c(top - 4)}" y2="{c(bottom)}"/>')
            end = x + 4 + text_width(label) > right
            out.append(f'<text class="ref-label" x="{c(x - 4 if end else x + 4)}" y="{c(top - 6)}" '
                       f'text-anchor="{"end" if end else "start"}">{esc(label)}</text>')
        elif r.axis == "y":
            y = ys(r.value)
            out.append(f'<line class="ref" x1="{c(left)}" x2="{c(right)}" y1="{c(y)}" y2="{c(y)}"/>')
            out.append(f'<text class="ref-label" x="{c(right - 2)}" y="{c(y - 5)}" text-anchor="end">{esc(label)}</text>')
    hits, ends = [], []
    for si, s in enumerate(chart.series):
        sp = [p for p in pts if p.series == si]
        if not sp:
            continue
        if category:
            index = {o: i for i, o in enumerate(xticks)}
            sp.sort(key=lambda p: index[str(p.x)])
        else:
            sp.sort(key=lambda p: p.x)
        coords = [(X(p.x), ys(p.y), p) for p in sp]
        band = [(x, ys(p.low), ys(p.high)) for x, _, p in coords if p.low is not None and p.high is not None]
        if len(band) > 1:
            upper = " ".join(f"{c(x)},{c(h)}" for x, _, h in band)
            lower = " ".join(f"{c(x)},{c(lo)}" for x, lo, _ in reversed(band))
            out.append(f'<polygon class="band {s["cls"]}" points="{upper} {lower}"/>')
        if chart.type == "line" and len(coords) > 1:
            d = "M" + "L".join(f"{c(x)},{c(y)}" for x, y, _ in coords)
            out.append(f'<path class="line {s["cls"]}" d="{d}"/>')
        for x, y, p in coords:
            out.append(f'<circle class="dot {s["cls"]}" cx="{c(x)}" cy="{c(y)}" r="4"/>')
            hits.append(marks.circle(x, y, tip(chart, p)))
        ends.append([coords[-1][1], s["short"]])
    if direct:
        ends.sort()
        for i in range(1, len(ends)):
            ends[i][0] = max(ends[i][0], ends[i - 1][0] + LINE)
        overflow = ends[-1][0] - bottom if ends else 0
        if overflow > 0:
            for e in ends:
                e[0] -= overflow
        for y, label in ends:
            out.append(f'<text class="direct" x="{c(right + 8)}" y="{c(y + 4)}">{esc(label)}</text>')
    out += hits
    out.append("</svg>")
    return "".join(out)


def render_bar(chart: Chart, facet, uid: str, marks: Marks, w: float) -> str:
    sx, sy = chart.spec.get("x", {}), chart.spec.get("y", {})
    pts = [p for p in chart.points if p.facet == facet]
    refs = [r for r in chart.refs if r.facet == facet and r.axis == "y"]
    order = [str(o) for o in sx.get("order", [])] or sorted({str(p.x) for p in pts})
    order = [o for o in order if any(str(p.x) == o for p in pts)]
    ph = chart.spec.get("height", 220)
    yvals = [p.y for p in pts] + [r.value for r in refs]
    top, bottom = TOP, TOP + ph
    ys, yticks = axis_scale(sy, yvals, bottom, top, zero_default=True)
    left = max(text_width(fmt(t, sy.get("format"))) for t in yticks) + 16
    right = w - RIGHT
    band = (right - left) / max(1, len(order))
    labels = [wrap(x_label_for(chart, o), band - 6) for o in order]
    rows = max(len(lab) for lab in labels)
    height = bottom + (BOTTOM if sx.get("label") else 28) + LINE * (rows - 1)
    n = len(chart.series)
    bw = max(4.0, min(24.0, (band * 0.72 - 2 * (n - 1)) / n))
    out = [svg_open(w, height, chart.title, describe(chart, facet), uid)]
    y_axis(out, ys, yticks, sy.get("format"), left, right)
    base = ys(max(ys.lo, 0.0)) if ys.kind == "linear" else bottom
    out.append(f'<line class="axis" x1="{c(left)}" x2="{c(right)}" y1="{c(base)}" y2="{c(base)}"/>')
    axis_title(out, sy.get("label", ""), 4, 14)
    if sx.get("label"):
        axis_title(out, sx["label"], (left + right) / 2, height - 6, "middle")
    for r in refs:
        y = ys(r.value)
        out.append(f'<line class="ref" x1="{c(left)}" x2="{c(right)}" y1="{c(y)}" y2="{c(y)}"/>')
        out.append(f'<text class="ref-label" x="{c(right - 2)}" y="{c(y - 5)}" text-anchor="end">{esc(ref_label(chart, r))}</text>')
    hits = []
    group_w = n * bw + (n - 1) * 2
    for i, o in enumerate(order):
        cx = left + band * (i + 0.5)
        for k, line in enumerate(labels[i]):
            out.append(f'<text x="{c(cx)}" y="{c(bottom + 18 + LINE * k)}" text-anchor="middle">{esc(line)}</text>')
        for si, s in enumerate(chart.series):
            p = next((q for q in pts if str(q.x) == o and q.series == si), None)
            if p is None:
                continue
            x = cx - group_w / 2 + si * (bw + 2)
            end = ys(p.y)
            out.append(f'<path class="bar {s["cls"]}" d="{bar_path(x, base, end, bw)}"/>')
            hits.append(marks.rect(x - 1, top, bw + 2, base - top, tip(chart, p)))
    out += hits
    out.append("</svg>")
    return "".join(out)


def render_dot(chart: Chart, facet, uid: str, marks: Marks, w: float) -> str:
    """Categories as rows, values along x: a dot per series, with its range."""
    sx, sy = chart.spec.get("x", {}), chart.spec.get("y", {})
    pts = [p for p in chart.points if p.facet == facet]
    refs = [r for r in chart.refs if r.facet == facet and r.axis in ("x", "y")]
    order = [str(o) for o in sx.get("order", [])] or sorted({str(p.x) for p in pts})
    order = [o for o in order if any(str(p.x) == o for p in pts)]
    label_w = min(w * 0.42, max(text_width(x_label_for(chart, o)) for o in order) + 4)
    labels = [wrap(x_label_for(chart, o), label_w) for o in order]
    left = label_w + 20
    right = w - RIGHT
    n = len(chart.series)
    row = max(30.0, 20.0 * n + 10, LINE * max(len(lab) for lab in labels) + 12)
    top = TOP + 6 if refs else 14
    bottom = top + row * len(order)
    height = bottom + (BOTTOM if sy.get("label") else 28)
    vals = [p.y for p in pts] + [v for p in pts for v in (p.low, p.high) if v is not None] + [r.value for r in refs]
    xs, xticks = axis_scale(sy, vals, left + 8, right - 8, zero_default=True)
    out = [svg_open(w, height, chart.title, describe(chart, facet), uid)]
    for t in xticks:
        x = xs(t)
        out.append(f'<line class="grid" x1="{c(x)}" x2="{c(x)}" y1="{c(top)}" y2="{c(bottom)}"/>')
        out.append(f'<text x="{c(x)}" y="{c(bottom + 18)}" text-anchor="middle">{esc(fmt(t, sy.get("format")))}</text>')
    axis_title(out, sy.get("label", ""), (left + right) / 2, height - 6, "middle")
    for r in refs:
        x = xs(r.value)
        label = ref_label(chart, r)
        out.append(f'<line class="ref" x1="{c(x)}" x2="{c(x)}" y1="{c(top - 6)}" y2="{c(bottom)}"/>')
        end = x + 4 + text_width(label) > right
        out.append(f'<text class="ref-label" x="{c(x - 4 if end else x + 4)}" y="{c(TOP - 8)}" '
                   f'text-anchor="{"end" if end else "start"}">{esc(label)}</text>')
    hits = []
    for i, o in enumerate(order):
        y0 = top + row * i
        lines = labels[i]
        first = y0 + row / 2 - LINE * (len(lines) - 1) / 2 + 4
        for k, line in enumerate(lines):
            out.append(f'<text x="{c(left - 12)}" y="{c(first + LINE * k)}" text-anchor="end">{esc(line)}</text>')
        if i:
            out.append(f'<line class="grid" x1="{c(left)}" x2="{c(right)}" y1="{c(y0)}" y2="{c(y0)}"/>')
        for si, s in enumerate(chart.series):
            p = next((q for q in pts if str(q.x) == o and q.series == si), None)
            if p is None:
                continue
            cy = y0 + row / 2 + (si - (n - 1) / 2) * 20
            if p.low is not None and p.high is not None:
                out.append(f'<line class="range {s["cls"]}" x1="{c(xs(p.low))}" x2="{c(xs(p.high))}" '
                           f'y1="{c(cy)}" y2="{c(cy)}"/>')
                for v in (p.low, p.high):
                    out.append(f'<line class="range {s["cls"]}" x1="{c(xs(v))}" x2="{c(xs(v))}" '
                               f'y1="{c(cy - 4)}" y2="{c(cy + 4)}"/>')
            cx = xs(p.y)
            out.append(f'<circle class="dot {s["cls"]}" cx="{c(cx)}" cy="{c(cy)}" r="4.5"/>')
            hits.append(marks.circle(cx, cy, tip(chart, p)))
    out.append(f'<line class="axis" x1="{c(left)}" x2="{c(right)}" y1="{c(bottom)}" y2="{c(bottom)}"/>')
    out += hits
    out.append("</svg>")
    return "".join(out)


def render_roofline(chart: Chart, facet, uid: str, marks: Marks, w: float) -> str:
    sx, sy = chart.spec.get("x", {}), chart.spec.get("y", {})
    pts = [p for p in chart.points if p.facet == facet]
    refs = [r for r in chart.refs if r.facet == facet]
    peaks = [r for r in refs if r.axis == "y"]
    diags = [r for r in refs if r.axis == "diagonal"]
    ph = chart.spec.get("height", 260)
    top, bottom = TOP, TOP + ph
    height = bottom + BOTTOM
    xvals = [p.x for p in pts]
    lo_x, hi_x = min(xvals) / 2, max(xvals) * 2
    peak = max((r.value for r in peaks), default=None)
    ymax = max([p.y for p in pts] + [r.value for r in peaks]) * 1.25
    ymin = min(p.y for p in pts) / 4
    ys, yticks = axis_scale({"scale": "log10"}, [ymin, ymax], bottom, top, zero_default=False)
    left = max(text_width(fmt(t, sy.get("format"))) for t in yticks) + 16
    right = w - RIGHT
    xs, xticks = axis_scale({"scale": "log10"}, [lo_x, hi_x], left + 8, right - 8, zero_default=False)
    out = [svg_open(w, height, chart.title, describe(chart, facet), uid)]
    y_axis(out, ys, yticks, sy.get("format"), left, right)
    for t in xticks:
        out.append(f'<text x="{c(xs(t))}" y="{c(bottom + 18)}" text-anchor="middle">{esc(fmt(t, sx.get("format")))}</text>')
    out.append(f'<line class="axis" x1="{c(left)}" x2="{c(right)}" y1="{c(bottom)}" y2="{c(bottom)}"/>')
    axis_title(out, sx.get("label", ""), (left + right) / 2, height - 6, "middle")
    axis_title(out, sy.get("label", ""), 4, 14)
    ridges = []
    for r in diags:
        x_end = min(xs.hi, peak / r.value) if peak else xs.hi
        x_start = max(xs.lo, ys.lo / r.value)
        ridges.append(x_end)
        if x_end <= x_start:
            continue
        out.append(f'<line class="roof d{r.dash}" x1="{c(xs(x_start))}" y1="{c(ys(r.value * x_start))}" '
                   f'x2="{c(xs(x_end))}" y2="{c(ys(r.value * x_end))}"/>')
    for r in peaks:
        y = ys(r.value)
        x_from = xs(min(ridges)) if ridges else left
        out.append(f'<line class="roof" x1="{c(x_from)}" x2="{c(right)}" y1="{c(y)}" y2="{c(y)}"/>')
        out.append(f'<text class="ref-label" x="{c(right - 2)}" y="{c(y - 6)}" text-anchor="end">{esc(ref_label(chart, r))}</text>')
    hits = []
    # The first series is the measurement the roofs predict, so it is drawn
    # last, on top of any later series at the same intensity.
    for si, s in reversed(list(enumerate(chart.series))):
        for p in sorted((p for p in pts if p.series == si), key=lambda p: (p.x, p.y)):
            cx, cy = xs(p.x), ys(p.y)
            out.append(f'<circle class="dot {s["cls"]}" cx="{c(cx)}" cy="{c(cy)}" r="4.5"/>')
            hits.append(marks.circle(cx, cy, tip(chart, p)))
    # One name per point label (a kernel), beside its first series' point.
    named: dict[str, Point] = {}
    for p in sorted(pts, key=lambda p: p.series):
        if p.label and p.label not in named:
            named[p.label] = p
    for x, y, anchor, text in place_labels([(xs(p.x), ys(p.y), t) for t, p in named.items()], right, top, bottom):
        out.append(f'<text class="pt-label" x="{c(x)}" y="{c(y)}" text-anchor="{anchor}">{esc(text)}</text>')
    out += hits
    out.append("</svg>")
    return "".join(out)


def place_labels(items: list[tuple[float, float, str]], right: float, top: float, bottom: float) -> list:
    """Point labels to the right of their points, or to the left where one
    would cross the plot's edge, moved down until no two overlap."""
    placed: list[tuple[float, float, float]] = []
    out = []
    for x, y, text in sorted(items, key=lambda t: t[1]):
        width = len(text) * PT_CHAR
        anchor, lx = ("start", x + 8) if x + 8 + width <= right else ("end", x - 8)
        x0, x1 = (lx, lx + width) if anchor == "start" else (lx - width, lx)
        ly = min(max(y + 3.5, top + 10), bottom - 4)
        for _ in range(len(items)):
            clash = [q for q in placed if x0 < q[1] and x1 > q[0] and abs(q[2] - ly) < 11]
            if not clash:
                break
            ly = max(q[2] for q in clash) + 11
        placed.append((x0, x1, ly))
        out.append((lx, ly, anchor, text))
    return out


RENDER = {"line": render_line, "scatter": render_line, "bar": render_bar, "dot": render_dot, "roofline": render_roofline}
KIND_NAMES = {"line": "Line chart", "scatter": "Scatter chart", "bar": "Bar chart", "dot": "Dot chart",
              "roofline": "Roofline chart"}


def describe(chart: Chart, facet=None) -> str:
    n = sum(1 for p in chart.points if p.facet == facet)
    series = "; ".join(s["name"] for s in chart.series)
    panel = f", panel {chart.facet_labels.get(facet, facet)}" if facet is not None else ""
    return f"{KIND_NAMES[chart.type]} of {chart.metric}{panel}. Series: {series}. {n} values, all in the table below the chart."


def render_table(chart: Chart) -> str:
    sx = chart.spec.get("x", {})
    has_range = any(p.low is not None for p in chart.points)
    has_label = any(p.label for p in chart.points)
    faceted = chart.facets != [None]
    head = (["Panel"] if faceted else []) + (["Series"] if len(chart.series) > 1 else [])
    head += (["Point"] if has_label else []) + [sx.get("label") or "x", "Value", "Unit"]
    if has_range:
        head += ["Low", "High"]
    head.append("RESULT key")
    rows = []
    for p in chart.points:
        cells = [chart.facet_labels.get(p.facet, p.facet)] if faceted else []
        if len(chart.series) > 1:
            cells.append(chart.series[p.series]["name"])
        if has_label:
            cells.append(p.label)
        cells += [num(p.x) if chart.type == "roofline" else x_label_for(chart, p.x), num(p.y), chart.unit(p.facet)]
        if has_range:
            cells += [num(p.low) if p.low is not None else "", num(p.high) if p.high is not None else ""]
        rows.append("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in cells) + f"<td><code>{esc(p.key)}</code></td></tr>")
    return ('<div class="table-wrap" tabindex="0"><table class="data"><thead><tr>'
            + "".join(f'<th scope="col">{esc(h)}</th>' for h in head)
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def render_ref_table(chart: Chart) -> str:
    if not chart.refs:
        return ""
    faceted = chart.facets != [None]
    head = (["Panel"] if faceted else []) + ["Reference line", "Value", "Source"]
    rows = []
    for r in chart.refs:
        cells = ([chart.facet_labels.get(r.facet, r.facet)] if faceted else []) + [
            ref_label(chart, r).replace(ref_value(chart, r), "").strip(" ,:") or ref_label(chart, r),
            ref_value(chart, r), r.source]
        rows.append("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in cells) + "</tr>")
    return ('<div class="table-wrap" tabindex="0"><table class="data refs"><thead><tr>'
            + "".join(f'<th scope="col">{esc(h)}</th>' for h in head)
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def render(chart: Chart) -> None:
    """Two-up facets are drawn once, narrow. Anything else is drawn wide and
    narrow, and the figure shows whichever fits its own width (a container
    query in site.css), so text stays near 12px from a phone to a desktop."""
    two_up = len(chart.facets) > 1 and chart.spec.get("facet_columns", 2) == 2
    variants = [("n", NARROW)] if two_up else [("w", WIDE), ("n", NARROW)]
    parts, counts = [], {}
    for tag, w in variants:
        marks = Marks()
        panels = []
        for i, f in enumerate(chart.facets):
            uid = f"c-{chart.benchmark}-{chart.id}-{i}{tag}"
            svg = RENDER[chart.type](chart, f, uid, marks, w)
            if f is not None:
                panels.append(f'<div class="facet"><p class="facet-title">{esc(chart.facet_labels.get(f, f))}</p>'
                              f'<div class="chart-scroll">{svg}</div></div>')
            else:
                panels.append(f'<div class="chart-scroll">{svg}</div>')
        counts[tag] = marks.count
        inner = (f'<div class="facets{" n2" if two_up else ""}">' + "".join(panels) + "</div>"
                 if len(panels) > 1 else panels[0])
        if len(variants) > 1:
            inner = f'<div class="v-{"wide" if tag == "w" else "narrow"}">{inner}</div>'
        parts.append(inner)
    chart.marks = counts[variants[0][0]]
    chart.svg = "".join(parts)
    shape = {"line": "line", "scatter": "dot", "bar": "bar", "dot": "dot", "roofline": "dot"}[chart.type]
    chart.legend = []
    if len(chart.series) >= 2:
        chart.legend += [{"cls": f"k {s['cls']} {shape}", "label": s["name"]} for s in chart.series]
    if chart.type == "roofline":
        seen = set()
        for r in chart.refs:
            if r.axis == "diagonal" and r.dash not in seen:
                seen.add(r.dash)
                chart.legend.append({"cls": f"k roof d{r.dash}", "label": r.label.replace("{value}", "").strip(" ,")})
    chart.table = render_table(chart)
    chart.ref_table = render_ref_table(chart)
