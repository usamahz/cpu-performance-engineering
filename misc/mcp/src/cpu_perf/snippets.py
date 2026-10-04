"""Trim a passage to the part that answers the question, so a brief answer
spends its tokens on evidence rather than on the text around it."""

from __future__ import annotations

import re

from . import text as tx

ROW_SEP = "\n\n"


def query_terms(query: str) -> list[str]:
    """Lower-case words and identifiers to look for in raw passage text."""
    words = re.findall(r"[a-z0-9][a-z0-9_.+#/-]*[a-z0-9+#]|[a-z0-9]", query.casefold())
    out: list[str] = []
    for w in words + tx.tokens(query):
        if len(w) < 3 or w in tx.STOPWORDS:
            continue
        if w not in out:
            out.append(w)
    return out


def _hits(text: str, terms: list[str]) -> list[tuple[int, str]]:
    low = text.casefold()
    found = []
    for t in terms:
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(t), low):
            found.append((m.start(), t))
    return sorted(found)


def _is_rows(text: str) -> bool:
    return text.count("; ") > 6 and ": " in text


def window(text: str, terms: list[str], width: int = 700) -> tuple[str, bool]:
    """(the best stretch of about `width` characters, whether it was cut)."""
    text = text.strip()
    if len(text) <= width + 80:
        return text, False
    if ROW_SEP in text and _is_rows(text):
        rows = [r for r in text.split(ROW_SEP) if r.strip()]
        scored = sorted(range(len(rows)), key=lambda i: -len({t for _, t in _hits(rows[i], terms)}))
        keep, size = [], 0
        for i in scored:
            if not _hits(rows[i], terms) and keep:
                break
            if size + len(rows[i]) > width and keep:
                break
            keep.append(i)
            size += len(rows[i])
        picked = ROW_SEP.join(rows[i] if len(rows[i]) <= width else rows[i][:width] + "..." for i in sorted(keep))
        return picked, True
    hits = _hits(text, terms)
    if not hits:
        start = 0
    else:
        # the window start that covers the most distinct terms
        best, best_n = hits[0][0], 0
        for i, (pos, _) in enumerate(hits):
            seen = {t for p, t in hits[i:] if p < pos + width}
            if len(seen) > best_n:
                best, best_n = pos, len(seen)
        start = max(0, best - width // 5)
    # snap to sentence or line boundaries
    if start > 0:
        back = max(text.rfind(". ", max(0, start - 160), start), text.rfind("\n", max(0, start - 160), start))
        start = back + 1 if back >= 0 else start
    end = min(len(text), start + width)
    if end < len(text):
        fwd = [p for p in (text.find(". ", end - 120, end + 160), text.find("\n", end - 120, end + 160)) if p >= 0]
        end = min(fwd) + 1 if fwd else end
    piece = text[start:end].strip()
    return ("..." if start > 0 else "") + piece + ("..." if end < len(text) else ""), True
