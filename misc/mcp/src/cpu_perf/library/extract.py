"""Text out of PDFs, HTML, plain text, markdown and xlsx, with page numbers
or heading paths kept for citations."""

from __future__ import annotations

import io
import json
import re
import threading
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.etree import ElementTree as ET


@dataclass
class Segment:
    text: str
    page: int | None = None  # 1-based PDF page
    heading: str | None = None


@dataclass
class Extracted:
    kind: str  # pdf | html | text | xlsx | json
    title: str | None
    segments: list[Segment] = field(default_factory=list)
    pages: int | None = None
    partial: bool = False
    description: str | None = None
    note: str = ""

    @property
    def chars(self) -> int:
        return sum(len(s.text) for s in self.segments)


# ----- PDF -----------------------------------------------------------------------

# PDFium is not thread-safe: every call into it, from any thread, goes through this lock.
PDFIUM_LOCK = threading.Lock()


def extract_pdf(data: bytes, max_pages: int = 2500, start_page: int = 1, end_page: int | None = None) -> Extracted:
    with PDFIUM_LOCK:
        return _extract_pdf(data, max_pages, start_page, end_page)


def _extract_pdf(data: bytes, max_pages: int, start_page: int, end_page: int | None) -> Extracted:
    import pypdfium2 as pdfium  # imported lazily: only PDFs need it

    pdf = pdfium.PdfDocument(data)
    try:
        total = len(pdf)
        title = None
        try:
            meta = pdf.get_metadata_dict()
            title = (meta.get("Title") or "").strip() or None
        except Exception:
            title = None
        if title and PLACEHOLDER_TITLE.match(title):
            title = None
        first = max(1, start_page)
        last = min(total, end_page or total, first + max_pages - 1)
        segments: list[Segment] = []
        for number in range(first, last + 1):
            page = pdf[number - 1]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range()
                finally:
                    textpage.close()
            finally:
                page.close()
            text = clean_text(text).replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
            if text.strip():
                segments.append(Segment(text=text, page=number))
        partial = last < total
        note = ""
        if not segments:
            note = "no text layer (scanned PDF?)"
        elif partial:
            note = f"indexed pages {first}-{last} of {total}; read the rest with read_source(page=...)"
        return Extracted(kind="pdf", title=title, segments=segments, pages=total, partial=partial, note=note)
    finally:
        pdf.close()


# ----- HTML ----------------------------------------------------------------------

SKIP = {"script", "style", "noscript", "svg", "template", "nav", "footer", "form", "iframe", "button", "select", "aside"}
BLOCK = {"p", "div", "section", "li", "tr", "br", "table", "ul", "ol", "dl", "dt", "dd", "blockquote", "figure", "figcaption", "header", "hr"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
VOID = {"br", "hr", "img", "meta", "link", "input", "source", "wbr", "col", "area", "base", "embed", "param", "track"}


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self._in_title = False
        self._skip = 0
        self._main = 0
        self._pre = 0
        self._heading: int | None = None
        self._heading_buf: list[str] = []
        self.blocks_all: list[tuple[str, str]] = []  # (kind, text) kind: h1..h6 | p
        self.blocks_main: list[tuple[str, str]] = []
        self._buf: list[str] = []
        self._stack: list[str] = []

    # helpers
    def _emit(self, kind: str, text: str) -> None:
        text = text.strip() if self._pre == 0 else text.rstrip()
        if not text:
            return
        self.blocks_all.append((kind, text))
        if self._main:
            self.blocks_main.append((kind, text))

    def _flush(self) -> None:
        if self._buf:
            raw = "".join(self._buf)
            self._buf = []
            if self._pre:
                self._emit("p", raw)
            else:
                self._emit("p", re.sub(r"[ \t\r\f\v]+", " ", raw).replace(" \n", "\n"))

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            a = dict(attrs)
            key = (a.get("name") or a.get("property") or "").lower()
            if key and a.get("content"):
                self.meta[key] = a["content"]
            return
        if tag in VOID:
            if tag == "br":
                self._buf.append("\n")
            return
        self._stack.append(tag)
        if tag == "title":
            self._in_title = True
            return
        if tag in SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in ("main", "article"):
            self._flush()
            self._main += 1
        elif tag == "pre":
            self._flush()
            self._pre += 1
        elif tag in HEADINGS:
            self._flush()
            self._heading = HEADINGS[tag]
            self._heading_buf = []
        elif tag in BLOCK:
            self._flush()
            if tag == "li":
                self._buf.append("- ")
        elif tag in ("td", "th"):
            self._buf.append(" | ")

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        # tolerate unclosed tags: pop back to the matching opener
        if tag in self._stack:
            while self._stack:
                top = self._stack.pop()
                self._close(top)
                if top == tag:
                    break

    def _close(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if tag in SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in HEADINGS and self._heading is not None:
            text = " ".join("".join(self._heading_buf).split())
            if text:
                self._emit(f"h{self._heading}", text)
            self._heading = None
            self._heading_buf = []
        elif tag in ("main", "article"):
            self._flush()
            self._main = max(0, self._main - 1)
        elif tag == "pre":
            self._flush()
            self._pre = max(0, self._pre - 1)
        elif tag in BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        if self._heading is not None:
            self._heading_buf.append(data)
        else:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def _charset(content_type: str, data: bytes) -> str:
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if m:
        return m.group(1)
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", data[:4096], re.I)
    if m:
        return m.group(1).decode("ascii", "ignore")
    return "utf-8"


def decode(data: bytes, content_type: str = "") -> str:
    enc = _charset(content_type, data)
    try:
        return data.decode(enc, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def extract_html(data: bytes, content_type: str = "", html: str | None = None) -> Extracted:
    html = html if html is not None else decode(data, content_type)
    parser = _TextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    main_chars = sum(len(t) for _, t in parser.blocks_main)
    blocks = parser.blocks_main if main_chars >= 400 else parser.blocks_all
    segments: list[Segment] = []
    path: list[tuple[int, str]] = []
    buf: list[str] = []

    def flush():
        text = "\n\n".join(buf).strip()
        if text:
            heading = " > ".join(h for _, h in path) or None
            segments.append(Segment(text=text, heading=heading))

    for kind, text in blocks:
        if kind.startswith("h"):
            flush()
            buf = []
            level = int(kind[1])
            path = [p for p in path if p[0] < level] + [(level, text)]
            buf.append("#" * level + " " + text)
        else:
            buf.append(text)
    flush()
    title = " ".join(parser.title.split()) or parser.meta.get("og:title")
    description = parser.meta.get("og:description") or parser.meta.get("description")
    return Extracted(kind="html", title=title or None, segments=segments, description=description)


# ----- plain text, markdown, reStructuredText, AsciiDoc ---------------------------

MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
ADOC_HEADING = re.compile(r"^(={1,6})\s+(.+?)\s*$")


def extract_text(text: str, title: str | None = None) -> Extracted:
    segments: list[Segment] = []
    path: list[tuple[int, str]] = []
    buf: list[str] = []
    in_code = False

    def flush():
        body = "\n".join(buf).strip()
        if body:
            segments.append(Segment(text=body, heading=" > ".join(h for _, h in path) or None))

    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith(("```", "~~~")):
            in_code = not in_code
        m = None if in_code else (MD_HEADING.match(line) or ADOC_HEADING.match(line))
        if not m and not in_code and i + 1 < len(lines) and line.strip() and re.match(r"^(=+|-+)\s*$", lines[i + 1]) and len(lines[i + 1].strip()) >= 3:
            level = 1 if lines[i + 1].strip().startswith("=") else 2
            flush()
            buf = [line]
            path = [p for p in path if p[0] < level] + [(level, line.strip())]
            continue
        if m:
            flush()
            buf = [line]
            level = len(m.group(1))
            path = [p for p in path if p[0] < level] + [(level, m.group(2).strip())]
            if title is None and level == 1:
                title = m.group(2).strip()
            continue
        if re.match(r"^(=+|-+)\s*$", line) and buf and len(buf) == 1:
            continue  # setext underline already consumed
        buf.append(line)
    flush()
    return Extracted(kind="text", title=title, segments=segments)


# ----- xlsx (stdlib) ----------------------------------------------------------------

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

# PDFium returns U+FFFE for a hyphen that breaks a word at a line end: "perfor￾mance".
# Left in, every quote carries it and the full-text index holds "perfor" and "mance".
LINE_END_HYPHEN = re.compile("￾(?:\r?\n)?")
# What a PDF's Title field holds when nobody set it; the list's own title is used instead.
PLACEHOLDER_TITLE = re.compile(
    r"^(untitled(\s+document)?|document\d*|microsoft (word|powerpoint) - .*|slide \d+|\S+\.(docx?|pptx?|tex|dvi|pdf))$", re.I
)


def clean_text(text: str) -> str:
    return LINE_END_HYPHEN.sub("", text)


# Bumped per kind when extraction improves; sources extracted by an older
# version are fetched again (unconditionally) by the next maintenance pass.
EXTRACT_VERSIONS = {"xlsx": 2, "pdf": 2}  # pdf 2: line-end hyphens joined, placeholder titles dropped


def extract_outdated(kind: str | None, version: int | None) -> bool:
    want = EXTRACT_VERSIONS.get(kind or "")
    return bool(want) and (version or 1) < want


def extract_xlsx(data: bytes, max_rows: int = 20000) -> Extracted:
    zf = zipfile.ZipFile(io.BytesIO(data))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    sheets: list[tuple[str, str]] = []
    try:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}
        for s in wb.findall("m:sheets/m:sheet", NS):
            target = targets.get(s.get(REL_NS), "")
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            sheets.append((s.get("name") or target, target))
    except (KeyError, ET.ParseError):
        sheets = [(n, n) for n in zf.namelist() if n.startswith("xl/worksheets/sheet")]
    segments: list[Segment] = []
    rows_total = 0
    for name, path in sheets:
        if path not in zf.namelist():
            continue
        root = ET.fromstring(zf.read(path))
        rows: list[list[str]] = []
        for row in root.iter(f"{{{NS['m']}}}row"):
            cells: list[str] = []
            for c in row.findall("m:c", NS):
                # empty cells are usually absent: place each one by its column letters
                col = _column_index(c.get("r") or "")
                if col is not None and col >= len(cells) and col < 4096:
                    cells.extend([""] * (col - len(cells)))
                t = c.get("t")
                v = c.find("m:v", NS)
                f = c.find("m:f", NS)
                val = ""
                if t == "s" and v is not None and v.text is not None:
                    idx = int(v.text)
                    val = shared[idx] if idx < len(shared) else ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                elif v is not None and v.text is not None:
                    val = v.text
                if f is not None and f.text:
                    val = f"{val} [={f.text}]" if val else f"={f.text}"
                cells.append(val.strip())
            while cells and not cells[-1]:
                cells.pop()
            if cells:
                rows.append(cells)
            rows_total += 1
            if rows_total >= max_rows:
                break
        paragraphs = _labelled_rows(rows)
        if paragraphs:
            # one row per paragraph, so passages hold whole rows and a search
            # lands on the row that matches
            segments.append(Segment(text="\n\n".join(paragraphs), heading=f"Sheet: {name}"))
        if rows_total >= max_rows:
            break
    return Extracted(kind="xlsx", title=None, segments=segments, partial=rows_total >= max_rows)


def _column_index(ref: str) -> int | None:
    """'AB12' -> 27 (0-based column)."""
    letters = ""
    for ch in ref:
        if ch.isalpha():
            letters += ch.upper()
        else:
            break
    if not letters:
        return None
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _header_row(rows: list[list[str]]) -> int | None:
    """The row of column names: among the first few, the widest row of short
    labels."""
    best, best_n = None, 2
    for i, r in enumerate(rows[:6]):
        cells = [c for c in r if c]
        if len(cells) <= best_n or any(len(c) > 40 for c in cells):
            continue
        if sum(1 for c in cells if any(ch.isalpha() for ch in c)) < 0.8 * len(cells):
            continue
        best, best_n = i, len(cells)
    return best


def _labelled_rows(rows: list[list[str]]) -> list[str]:
    """'Column: value; Column: value' per row when the sheet has a header,
    so a passage says what each value is (Metric, Threshold, Formula)."""
    h = _header_row(rows)
    if h is None:
        return [" | ".join(c for c in r if c) for r in rows]
    header = rows[h]
    out = [" | ".join(c for c in r if c) for r in rows[:h]]
    out.append("Columns: " + "; ".join(c for c in header if c))
    for r in rows[h + 1 :]:
        if sum(1 for c in r if c) < 2:
            out.append(" | ".join(c for c in r if c))
            continue
        cells = [f"{header[j] if j < len(header) and header[j] else f'column {j + 1}'}: {v}" for j, v in enumerate(r) if v]
        out.extend(_split_row(cells))
    return out


ROW_PIECE = 1200


def _split_row(cells: list[str]) -> list[str]:
    """A long row becomes several paragraphs at cell boundaries, each
    continuation led by the row's first two cells, so every passage still
    says which metric its threshold or formula belongs to."""
    whole = "; ".join(cells)
    if len(whole) <= ROW_PIECE:
        return [whole]
    lead = "; ".join(cells[:2]) + " (continued)"
    pieces, buf = [], ""
    for cell in cells:
        cell = cell if len(cell) <= ROW_PIECE else cell[:ROW_PIECE] + "..."
        if buf and len(buf) + len(cell) + 2 > ROW_PIECE:
            pieces.append(buf)
            buf = f"{lead}; {cell}"
        else:
            buf = f"{buf}; {cell}" if buf else cell
    if buf:
        pieces.append(buf)
    return pieces


# ----- GitHub pull request JSON -------------------------------------------------------


def extract_github_pr(data: bytes) -> Extracted:
    obj = json.loads(data.decode("utf-8", "replace"))
    title = obj.get("title") or None
    body = obj.get("body") or ""
    head = f"# {title}\n\n" if title else ""
    return extract_text(head + body, title=title)


# ----- sniffing ----------------------------------------------------------------------------


def sniff(data: bytes, content_type: str, url: str) -> str:
    ct = (content_type or "").lower()
    if data[:5] == b"%PDF-" or "application/pdf" in ct:
        return "pdf"
    if data[:2] == b"PK" and (url.lower().endswith(".xlsx") or "spreadsheet" in ct):
        return "xlsx"
    if "json" in ct:
        return "json"
    if "html" in ct or data.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
        return "html"
    if ct.startswith("text/") or not ct:
        return "text"
    if data[:2] == b"\x1f\x8b" or url.lower().endswith((".gz", ".ps")):
        return "unsupported"
    return "text" if _looks_textual(data) else "unsupported"


def _looks_textual(data: bytes) -> bool:
    sample = data[:4096]
    if not sample:
        return False
    return sum(1 for b in sample if b < 9 or 13 < b < 32) / len(sample) < 0.02
