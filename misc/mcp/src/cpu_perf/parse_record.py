"""Parse the section drafts in misc/notes/sections/: the Rejected, Claims,
Link notes and Benchmark proposal blocks that record every editorial decision.

Drafts are joined to README sections by their file number NN, never by their
own H2, which is numbered one lower (file 09 says "## 8. Concurrency")."""

from __future__ import annotations

import re

from . import grammar as g
from .schema import Claim, Draft, LinkNote, Rejected

OWNER = re.compile(r"<!--\s*owner:\s*(.+?)\s*-->")
STRICT = re.compile(r"^- \[(?P<title>[^\]]+)\]\((?P<url>https?://[^\s)]+)\) - (?P<reason>\S.*)$")
BACKTICK = re.compile(r"`([^`]+)`")
QUOTE = re.compile(r"[\"“]([^\"”]+)[\"”]")
SECTION_REF = re.compile(r"\b(?:listed|left|carried|kept)\s+(?:in|to|under)\s+sections?\s+(\d{1,2})", re.I)
LEFT_TO = re.compile(r"^left to (?:sections? (\d{1,2})|start here)", re.I)
RULES_PREFIX = re.compile(r"^(?:rules?\s+\d(?:\s*(?:,|and|&)\s*(?:rule\s*)?\d)*)", re.I)
FIELD_DIGITS = re.compile(r"\b([1-7])\b")
FIELD_WORDS = (
    (re.compile(r"\b(cpu|model|microarchitecture|part)\b", re.I), 1),
    (re.compile(r"\b(cores?|core count|threads?)\b", re.I), 2),
    (re.compile(r"\b(freq\w*|turbo|smt|dvfs|clock)\b", re.I), 3),
    (re.compile(r"\b(compiler|flags?)\b", re.I), 4),
    (re.compile(r"\bworkload\b", re.I), 5),
    (re.compile(r"\bbaseline\b", re.I), 6),
    (re.compile(r"\b(method|runs?|statistic|repetitions?)\b", re.I), 7),
)

BLOCKS = ("Rejected", "Claims", "Link notes", "Benchmark proposal")


def _split_head(body: str) -> tuple[str, str] | None:
    """Split "head - reason" on the first " - " outside brackets, parentheses
    and backticks."""
    depth_paren = depth_brack = 0
    in_tick = False
    i = 0
    while i < len(body) - 2:
        c = body[i]
        if c == "`":
            in_tick = not in_tick
        elif not in_tick:
            if c == "(":
                depth_paren += 1
            elif c == ")":
                depth_paren = max(0, depth_paren - 1)
            elif c == "[":
                depth_brack += 1
            elif c == "]":
                depth_brack = max(0, depth_brack - 1)
            elif body.startswith(" - ", i) and depth_paren == 0 and depth_brack == 0:
                return body[:i], body[i + 3 :]
        i += 1
    return None


def categorize(reason: str) -> tuple[str, list[int], int | None]:
    low = reason.strip().lower()
    rules: list[int] = []
    left_to: int | None = None
    pm = RULES_PREFIX.match(reason.strip())
    if pm:
        rules = sorted({int(d) for d in re.findall(r"\d", pm.group(0))})
        # "Rule 1: ...; rule 3: ..." mentions further rules after the first clause
        for extra in re.findall(r"\brule (\d)\b", low):
            if int(extra) not in rules:
                rules.append(int(extra))
        return "rule", rules, None
    lm = LEFT_TO.match(low)
    if lm:
        left_to = int(lm.group(1)) if lm.group(1) else 1
        return "left_to", rules, left_to
    if low.startswith(("no rule failed", "fails no source rule", "not a list-rule failure", "not a rule failure")):
        return "no_rule_failed", rules, None
    if low.startswith("trimmed for length"):
        return "trimmed", rules, None
    if low.startswith("size"):
        return "size", rules, None
    if low.startswith("left out"):
        return "cap", rules, None
    if low.startswith(("scope", "out of scope")):
        return "scope", rules, None
    if low.startswith("duplicate"):
        return "duplicate", rules, None
    if low.startswith("leaderboard"):
        return "leaderboard", rules, None
    return "other", rules, None


def _parse_rejected(body: str, section: int, line: int, source: str, ordinal: int) -> Rejected:
    raw = body
    sm = STRICT.match(body)
    if sm:
        title, urls, reason = sm.group("title"), [sm.group("url")], sm.group("reason")
        unlinked = note = None
    else:
        split = _split_head(body[2:])
        if split is None:
            head, reason = body[2:], ""
        else:
            head, reason = split
        links = g.INLINE_LINK.findall(head)
        urls = [u for _, u in links]
        ticks = BACKTICK.findall(head)
        unlinked = ticks[0] if ticks else None
        for u in g.find_urls(head):
            if u not in urls:
                urls.append(u)
        nm = re.search(r"\(([^()]*not linked[^()]*)\)", head)
        note = nm.group(1) if nm else None
        if links:
            title = links[0][0]
        else:
            title = re.sub(r"\s*\([^()]*\)\s*$", "", head).strip() or head.strip()
            title = re.sub(r"https?://\S+", "", title).strip(" ,") or head.strip()
    category, rules, left_to = categorize(reason)
    listed_in = sorted({int(x) for x in SECTION_REF.findall(reason)})
    return Rejected(
        id=f"r{section}.{ordinal}",
        section=section,
        line=line,
        source=source,
        title=title.strip(),
        urls=urls,
        reason=reason.strip(),
        category=category,
        rules=rules,
        unlinked_ref=unlinked,
        note=note,
        left_to=left_to,
        listed_in=listed_in,
        raw=raw,
    )


def normalise_verdict(text: str | None) -> str | None:
    if not text:
        return None
    low = text.strip().lower()
    if low.startswith("core"):
        return "core"
    if low.startswith("watchlist"):
        return "watchlist"
    if low.startswith("cut"):
        return "cut"
    if "not quoted" in low or "nothing to quote" in low or low.startswith("not carried"):
        return "not_quoted"
    return "other"


def _parse_claim(body: str, section: int, line: int, source: str, ordinal: int) -> Claim:
    text = body[2:].strip()
    qm = QUOTE.search(text)
    quote = qm.group(1) if qm else None
    urls = g.find_urls(text)
    fields_text = missing_text = verdict_text = None
    fm = re.search(r"fields present:\s*(.+?)(?=(?:\.\s*)?Missing:|(?:\.\s*)?Verdict:|$)", text, re.I | re.S)
    if fm:
        fields_text = fm.group(1).strip().rstrip(".")
    mm = re.search(r"Missing:\s*(.+?)(?=(?:\.\s*)?Verdict:|$)", text, re.S)
    if mm:
        missing_text = mm.group(1).strip().rstrip(".")
    vm = re.search(r"Verdict:\s*(.+)$", text, re.S)
    if vm:
        verdict_text = vm.group(1).strip()
    missing: set[int] = set()
    if missing_text:
        missing.update(int(d) for d in FIELD_DIGITS.findall(missing_text))
        if not missing:
            for rx, num in FIELD_WORDS:
                if rx.search(missing_text):
                    missing.add(num)
    return Claim(
        id=f"c{section}.{ordinal}",
        section=section,
        line=line,
        source=source,
        text=text,
        quote=quote,
        urls=urls,
        fields_text=fields_text,
        missing_text=missing_text,
        missing_fields=sorted(missing),
        verdict=normalise_verdict(verdict_text),
        verdict_text=verdict_text,
    )


def _parse_link_note(body: str, section: int, line: int, source: str, ordinal: int) -> LinkNote:
    text = body[2:].strip()
    head = text.split(": ", 1)[0]
    urls = g.find_urls(head) or g.find_urls(text)
    return LinkNote(id=f"l{section}.{ordinal}", section=section, line=line, source=source, urls=urls, text=text)


def parse_draft(
    path: str, text: str, section: int
) -> tuple[Draft, list[Rejected], list[Claim], list[LinkNote]]:
    lines = text.splitlines()
    om = OWNER.search(text)
    owner = om.group(1) if om else None
    heading = ""
    block: str | None = None
    items: dict[str, list[tuple[int, str]]] = {b: [] for b in BLOCKS[:3]}
    proposal: list[str] = []
    for n, line in enumerate(lines, 1):
        if line.startswith("## "):
            name = line[3:].strip()
            if not heading:
                heading = name
            block = name if name in BLOCKS else None
            continue
        if block is None:
            continue
        if block == "Benchmark proposal":
            proposal.append(line)
            continue
        if line.startswith("- "):
            items[block].append((n, line))
        elif line.strip() and line.startswith((" ", "\t")) and items[block]:
            ln, prev = items[block][-1]
            items[block][-1] = (ln, prev + " " + line.strip())
    rejected = [_parse_rejected(b, section, n, path, i) for i, (n, b) in enumerate(items["Rejected"], 1)]
    claims = [_parse_claim(b, section, n, path, i) for i, (n, b) in enumerate(items["Claims"], 1)]
    notes = [_parse_link_note(b, section, n, path, i) for i, (n, b) in enumerate(items["Link notes"], 1)]
    draft = Draft(number=section, path=path, owner=owner, heading=heading, proposal="\n".join(proposal).strip())
    return draft, rejected, claims, notes


def parse_rules(owner_brief: str) -> dict[int, str]:
    """The seven numbered rules in owner-brief.md (Rule 1..7 in Rejected reasons)."""
    rules: dict[int, str] = {}
    current: int | None = None
    buf: list[str] = []
    in_rules = False
    for line in owner_brief.splitlines():
        if line.startswith("## "):
            if in_rules and current is not None:
                rules[current] = " ".join(buf).strip()
            in_rules = "rules" in line.lower()
            current, buf = None, []
            continue
        if not in_rules:
            continue
        m = re.match(r"^(\d)\. (.+)$", line)
        if m:
            if current is not None:
                rules[current] = " ".join(buf).strip()
            current, buf = int(m.group(1)), [m.group(2).strip()]
        elif current is not None and line.strip():
            buf.append(line.strip())
    if in_rules and current is not None:
        rules[current] = " ".join(buf).strip()
    return rules
