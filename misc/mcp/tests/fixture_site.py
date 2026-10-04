"""A local web site that mirrors the shapes the crawler meets on the real list:
PDFs, a vendor landing page that offers a PDF, articles, redirects, blocked
and dead links, a bot wall, robots.txt, gzip and a spreadsheet."""

from __future__ import annotations

import gzip
import io
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one Helvetica text block per page."""
    objects: list[bytes] = []

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    n_pages = len(pages)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, text in enumerate(pages):
        content_id = 4 + 2 * i
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        lines = [ln for ln in text.split("\n")]
        ops = " T* ".join(f"({esc(ln)}) Tj" for ln in lines)
        stream = f"BT /F1 11 Tf 14 TL 72 720 Td {ops} ET".encode()
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for num, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{num} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_xlsx(rows: list[list[str]]) -> bytes:
    shared: list[str] = []
    cells_xml = []
    for r, row in enumerate(rows, 1):
        cs = []
        for c, val in enumerate(row):
            if val == "":
                continue  # like real files: empty cells are simply absent
            if val.startswith("="):
                cs.append(f'<c r="{chr(65 + c)}{r}"><f>{val[1:]}</f><v>0</v></c>')
            else:
                shared.append(val)
                cs.append(f'<c r="{chr(65 + c)}{r}" t="s"><v>{len(shared) - 1}</v></c>')
        cells_xml.append(f'<row r="{r}">{"".join(cs)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{rns}"><sheets><sheet name="Metrics" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}">' + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>{"".join(cells_xml)}</sheetData></worksheet>')
    return buf.getvalue()


PAPER_PAGES = [
    "False sharing happens when two cores write different variables\nthat sit on the same cache line.",
    "The line moves between the cores on every write, so throughput\ncollapses as threads are added. Padding each counter to its own\nline restores scaling.",
    "Measure with perf c2c to find the contended line and its offsets.",
]
MANUAL_PAGES = [
    "Store forwarding lets a load read data from an older store\nthat has not yet reached the cache.",
    "A size mismatch between the store and the load blocks forwarding\nand costs a stall of many cycles.",
]
ARTICLE = (
    "<html><head><title>Roofline in practice</title></head><body><nav>site menu</nav><main><article>"
    "<h1>Roofline in practice</h1><p>Operational intensity is flops per byte of DRAM traffic. "
    + "A kernel below the ridge point is bound by memory bandwidth, not by the floating point units. " * 12
    + "</p><h2>Measuring the roofs</h2><p>Measure peak bandwidth with a STREAM-like triad and peak flops with an "
    "unrolled FMA loop.</p></article></main><footer>copyright</footer></body></html>"
)
LANDING = (
    "<html><head><title>Optimization Manual</title></head><body><main><p>Download the manual.</p>"
    '<a href="/docs/manual.pdf">Download PDF</a> <a href="/about">About us</a></main></body></html>'
)
WALL = "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"


class Site:
    def __init__(self):
        self.hits: dict[str, int] = {}
        self.slow_seconds = 1.5
        self.paper = make_pdf(PAPER_PAGES)
        self.manual = make_pdf(MANUAL_PAGES)
        self.sheet = make_xlsx([["Metric", "Formula"], ["Frontend_Bound", "=IDQ_UOPS_NOT_DELIVERED/SLOTS"]])
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                site.hits[self.path] = site.hits.get(self.path, 0) + 1
                if self.path.startswith("/slow/"):
                    time.sleep(site.slow_seconds)
                route = site.routes().get(self.path.split("?")[0])
                if route is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                status, ctype, body, extra = route
                if self.headers.get("If-None-Match") == '"v1"' and extra.get("ETag") == '"v1"':
                    self.send_response(304)
                    self.end_headers()
                    return
                self.send_response(status)
                if ctype:
                    self.send_header("Content-Type", ctype)
                for k, v in extra.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def routes(self) -> dict:
        gz = gzip.compress(ARTICLE.encode())
        return {
            "/robots.txt": (200, "text/plain", b"User-agent: *\nDisallow: /private/\n", {}),
            "/papers/false-sharing.pdf": (200, "application/pdf", self.paper, {"ETag": '"v1"'}),
            "/docs/manual.pdf": (200, "application/pdf", self.manual, {}),
            "/content-details/manual.html": (200, "text/html; charset=utf-8", LANDING.encode(), {}),
            "/article.html": (200, "text/html; charset=utf-8", ARTICLE.encode(), {}),
            "/gz.html": (200, "text/html; charset=utf-8", gz, {"Content-Encoding": "gzip"}),
            "/moved": (301, None, b"", {"Location": "/article.html"}),
            "/forbidden": (403, "text/html", b"no", {}),
            "/wall.html": (200, "text/html", WALL.encode(), {}),
            "/private/secret.html": (200, "text/html", b"<p>robots says no</p>", {}),
            "/sheet.xlsx": (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", self.sheet, {}),
            "/notes.txt": (200, "text/plain; charset=utf-8", b"# Notes\n\nPlain text notes about TLB reach and huge pages.\n", {}),
            "/slow/manual.pdf": (200, "application/pdf", self.manual, {}),
        }

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def url(self, path: str) -> str:
        return self.base + path
