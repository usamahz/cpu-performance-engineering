"""Parse README.md into sections, subsections, entries and their attachments."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import grammar as g
from .schema import Companion, Entry, Reproduce, Section, Subsection

NON_RESOURCE = {"contents", "what earns a place", "license"}
TABLE_ROW = re.compile(r"^\|\s*(\d)\s*\|\s*(.+?)\s*\|$")
BADGE_ENTRIES = re.compile(r"badge/entries-(\d+)-")
BADGE_BENCH = re.compile(r"badge/benchmarks-(\d+)%20runnable")


@dataclass
class ReadmeParse:
    sections: dict[int, Section] = field(default_factory=dict)
    subsections: dict[str, Subsection] = field(default_factory=dict)
    entries: dict[str, Entry] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)  # entry ids in README order
    seven_fields: list[str] = field(default_factory=list)
    admission: str = ""
    intro: str = ""
    badge_entries: int | None = None
    badge_benchmarks: int | None = None
    headings: list[tuple[int, int, str, str]] = field(default_factory=list)  # (line, level, title, anchor)


def host_of(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _section_kind(title: str) -> str:
    low = title.lower()
    if "start here" in low:
        return "start_here"
    if "watchlist" in low or low == "frontier":
        return "watchlist"
    return "core"


def parse_readme(text: str) -> ReadmeParse:
    out = ReadmeParse()
    lines = text.splitlines()

    m = BADGE_ENTRIES.search(text)
    out.badge_entries = int(m.group(1)) if m else None
    m = BADGE_BENCH.search(text)
    out.badge_benchmarks = int(m.group(1)) if m else None

    anchors_seen: dict[str, int] = {}
    in_code = False
    section: Section | None = None
    sub: Subsection | None = None
    non_resource: str | None = None
    pos_in_sub = 0
    sub_pos = 0
    awaiting_preamble = False
    preamble_lines: list[str] = []
    intro_lines: list[str] = []
    admission_lines: list[str] = []
    seen_first_h2 = False

    def anchor_for(title: str) -> str:
        base = g.github_anchor(title)
        count = anchors_seen.get(base, 0)
        anchors_seen[base] = count + 1
        return base if count == 0 else f"{base}-{count}"

    def close_preamble() -> None:
        nonlocal awaiting_preamble, preamble_lines
        if section is not None and preamble_lines:
            section.preamble = " ".join(s.strip() for s in preamble_lines).strip()
        awaiting_preamble = False
        preamble_lines = []

    for n, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue

        hm = g.HEADING.match(line)
        if hm:
            close_preamble()
            level = len(hm.group(1))
            title = hm.group(2)
            anchor = anchor_for(title)
            out.headings.append((n, level, title, anchor))
            if level == 2:
                seen_first_h2 = True
                nm = g.NUMBERED_H2.match(title)
                if nm and title.lower() not in NON_RESOURCE:
                    number = int(nm.group(1))
                    section = Section(
                        number=number,
                        title=nm.group(2).strip(),
                        heading=title,
                        anchor=anchor,
                        line=n,
                        kind=_section_kind(nm.group(2)),
                    )
                    out.sections[number] = section
                    non_resource = None
                    awaiting_preamble = True
                else:
                    section = None
                    non_resource = title.lower()
                sub = None
                sub_pos = 0
                pos_in_sub = 0
            elif level == 3 and section is not None:
                sub_pos += 1
                sub = Subsection(
                    id=f"{section.number}.{sub_pos}",
                    section=section.number,
                    position=sub_pos,
                    title=title,
                    anchor=anchor,
                    line=n,
                )
                out.subsections[sub.id] = sub
                section.subsection_ids.append(sub.id)
                pos_in_sub = 0
            continue

        if not seen_first_h2:
            if n > 5 and stripped:  # skip H1, banner and badges
                intro_lines.append(stripped)
            elif n > 5 and intro_lines and intro_lines[-1] != "":
                intro_lines.append("")
            continue

        if non_resource == "what earns a place":
            tm = TABLE_ROW.match(stripped)
            if tm:
                out.seven_fields.append(tm.group(2))
            elif stripped and not stripped.startswith("|"):
                admission_lines.append(stripped)
            elif not stripped and admission_lines and admission_lines[-1] != "":
                admission_lines.append("")
            continue
        if section is None:
            continue

        if awaiting_preamble:
            if not stripped:
                if preamble_lines:
                    close_preamble()
                continue
            if g.ENTRY.match(line) or stripped.startswith("- ") or g.REPRO.match(line):
                close_preamble()
            else:
                preamble_lines.append(stripped)
                if section.kind == "watchlist":
                    wd = g.WATCH_DATE.search(stripped)
                    if wd:
                        section.watch_checked = wd.group(1)
                continue

        if not stripped:
            continue

        rm = g.REPRO.match(line)
        if rm:
            rep = Reproduce(
                slug=rm.group(2),
                description=rm.group(3),
                line=n,
                section=section.number,
                subsection=sub.id if sub else None,
            )
            (sub.reproduce if sub else section.reproduce).append(rep)
            continue

        em = g.ENTRY.match(line)
        wm = None
        if not em and section.kind == "watchlist" and line.startswith("- "):
            wm = g.WATCH.match(line)
        if em or wm:
            match = em or wm
            title = match.group("title")
            url = match.group("url")
            reason = match.group("reason")
            if section.kind == "start_here" and em and em.group(1):
                entry_id = f"{section.number}.{int(em.group(1))}"
                position = int(em.group(1))
                kind = "start_here"
            else:
                pos_in_sub += 1
                position = pos_in_sub
                entry_id = f"{section.number}.{sub.position if sub else 0}.{pos_in_sub}"
                kind = "watch" if section.kind == "watchlist" else "entry"
            if title is None:  # unlinked watchlist line
                title = reason.split(", ", 1)[0].rstrip(".")
            entry = Entry(
                id=entry_id,
                kind=kind,
                section=section.number,
                subsection=sub.id if sub else None,
                position=position,
                title=title,
                url=url,
                reason=reason,
                line=n,
                host=host_of(url) if url else "",
            )
            if kind == "watch":
                cm = g.CONDITION.match(reason)
                if cm:
                    entry.condition = cm.group("cond")
                    entry.condition_kw = cm.group("kw")
            out.entries[entry_id] = entry
            out.order.append(entry_id)
            section.entry_ids.append(entry_id)
            if sub:
                sub.entry_ids.append(entry_id)
            continue

        for title, url in g.INLINE_LINK.findall(line):
            section.companions.append(
                Companion(title=title, url=url, text=stripped, line=n, section=section.number)
            )

    close_preamble()
    out.intro = "\n".join(intro_lines).strip()
    out.admission = "\n".join(admission_lines).strip()
    return out
