"""Split extracted text into passages of about 1,400 characters with a small
overlap. Passages never cross a PDF page, so every one cites a single page."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..text import sentences
from .extract import Extracted

TARGET = 1400
OVERLAP = 150
MIN_CHARS = 40


@dataclass
class Chunk:
    ord: int
    page: int | None
    heading: str | None
    text: str


def _paragraphs(text: str, pdf: bool) -> list[str]:
    text = text.replace("\r\n", "\n")
    if pdf:
        # PDF text has hard line breaks; rejoin hyphenated and wrapped lines.
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
        blocks = re.split(r"\n\s*\n", text)
        out = []
        for b in blocks:
            lines = [ln.strip() for ln in b.split("\n") if ln.strip()]
            if lines:
                out.append(" ".join(lines))
        return out
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _split_long(par: str) -> list[str]:
    if len(par) <= TARGET:
        return [par]
    pieces: list[str] = []
    buf = ""
    for s in sentences(par) or [par]:
        while len(s) > TARGET:  # a run-on "sentence" (tables, code)
            pieces.append((buf + " " + s[:TARGET]).strip() if buf else s[:TARGET])
            buf = ""
            s = s[TARGET:]
        if len(buf) + len(s) + 1 > TARGET and buf:
            pieces.append(buf.strip())
            buf = ""
        buf = f"{buf} {s}" if buf else s
    if buf.strip():
        pieces.append(buf.strip())
    return pieces


def _tail(text: str) -> str:
    """The last ~OVERLAP characters, starting at a word boundary."""
    if len(text) <= OVERLAP:
        return ""
    tail = text[-OVERLAP:]
    cut = tail.find(" ")
    return tail[cut + 1 :] if cut >= 0 else tail


def chunk(doc: Extracted) -> list[Chunk]:
    chunks: list[Chunk] = []
    pdf = doc.kind == "pdf"
    for seg in doc.segments:
        pieces: list[str] = []
        for par in _paragraphs(seg.text, pdf):
            pieces.extend(_split_long(par))
        buf = ""
        for piece in pieces:
            if buf and len(buf) + len(piece) + 2 > TARGET:
                chunks.append(Chunk(len(chunks), seg.page, seg.heading, buf.strip()))
                overlap = _tail(buf)
                buf = f"{overlap} {piece}" if overlap else piece
            else:
                buf = f"{buf}\n\n{piece}" if buf else piece
        if len(buf.strip()) >= MIN_CHARS or (buf.strip() and not chunks):
            chunks.append(Chunk(len(chunks), seg.page, seg.heading, buf.strip()))
    return chunks
