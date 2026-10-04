"""The MCP server as the site shows it: its own README, split into sections,
and the tool, resource and prompt lists the build dumped from the running
server (build/mcp-surface.json). Nothing here describes the server in the
site's own words; every MCP page quotes one of those two sources."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .markdown import Markdown
from .paths import slugify

SOURCE = "misc/mcp/README.md"
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
EXAMPLES_INTRO = re.compile(r"ask, for example", re.I)
TOOL_ROW = re.compile(r"^\|\s*((?:`[a-z_]+`(?:,\s*)?)+)\s*\|\s*(.+?)\s*\|\s*$")

# Which MCP page carries each heading of the server's README. A heading not
# listed (development, releasing) stays on GitHub; check.py fails the build
# if the README gains a heading no page or link accounts for.
ANCHOR_PAGES = {
    "connect-it": "/mcp/quickstart/",
    "claude": "/mcp/quickstart/",
    "chatgpt": "/mcp/quickstart/",
    "codex": "/mcp/quickstart/",
    "cursor-and-vs-code": "/mcp/quickstart/",
    "what-every-client-sees": "/mcp/quickstart/",
    "the-first-run-building-the-library": "/mcp/quickstart/",
    "configuration": "/mcp/quickstart/",
    "tools": "/mcp/tools/",
    "speed": "/mcp/tools/",
    "use-it-for-your-own-work": "/mcp/workflows/",
    "how-it-stays-honest": "/mcp/security/",
    "keeping-the-list-current": "/mcp/security/",
    "safety-of-fetching": "/mcp/security/",
    "copyright-and-politeness": "/mcp/security/",
    "serving-over-http": "/mcp/security/",
}
GITHUB_ONLY = {"development", "releasing", "licence"}
CLIENT_TABS = ("claude", "chatgpt", "codex", "cursor-and-vs-code")
# A client the README sets up through another client's host: the ChatGPT
# desktop app runs local servers through Codex.
CLIENT_SETUP_VIA = {"chatgpt": "codex"}
CODE = re.compile(r"^(?:```|~~~| {4}\S)", re.M)


@dataclass
class DocSection:
    level: int
    title: str
    anchor: str
    body: str
    children: list = field(default_factory=list)


def split_sections(text: str) -> tuple[str, list[DocSection]]:
    """(text before the first H2, [H2 sections with their H3 children])."""
    intro: list[str] = []
    top: list[DocSection] = []
    current: DocSection | None = None
    buf: list[str] = []
    fence = False

    def flush():
        if current is not None:
            current.body = "\n".join(buf).strip("\n")

    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
        m = None if fence else HEADING.match(line)
        if m and len(m.group(1)) in (2, 3):
            flush()
            buf = []
            level, title = len(m.group(1)), m.group(2)
            sec = DocSection(level, title, slugify(title), "")
            if level == 2 or not top:
                top.append(sec)
            else:
                top[-1].children.append(sec)
            current = sec
            continue
        if m and len(m.group(1)) == 1:
            continue  # the README's own title
        (buf if current is not None else intro).append(line)
    flush()
    return "\n".join(intro).strip(), top


class McpView:
    def __init__(self, readme: str, surface: dict | None, md: Markdown):
        self.readme = readme
        self.surface = surface or None
        self.md = md
        self.intro_md, self.sections = split_sections(readme)
        self.examples = self._examples()

    # ---- README -------------------------------------------------------------

    def find(self, anchor: str) -> DocSection | None:
        for s in self.sections:
            if s.anchor == anchor:
                return s
            for c in s.children:
                if c.anchor == anchor:
                    return c
        return None

    def render(self, text: str, demote: int = 0) -> str:
        return self.md.render(text, SOURCE, demote=demote)

    def section_html(self, anchor: str, demote: int = 0, children: bool = True) -> str:
        s = self.find(anchor)
        if s is None:
            return ""
        parts = [s.body]
        if children:
            for c in s.children:
                parts.append(f"{'#' * c.level} {c.title}\n\n{c.body}")
        return self.render("\n\n".join(parts), demote=demote)

    @property
    def intro_html(self) -> str:
        return self.render(self.intro_md)

    def _examples(self) -> list[str]:
        out, on = [], False
        for line in self.readme.splitlines():
            if EXAMPLES_INTRO.search(line):
                on = True
                continue
            if on:
                if line.startswith("- "):
                    out.append(line[2:].strip())
                elif out and not line.strip():
                    break
        return out

    def example_html(self, text: str) -> str:
        return self.md.inline(text, SOURCE)

    def body_html(self, anchor: str, demote: int = 1) -> str:
        """One section's own text, without its heading or its H3 children."""
        s = self.find(anchor)
        return self.render(s.body, demote=demote) if s else ""

    def child(self, parent: str, anchor: str) -> DocSection | None:
        s = self.find(parent)
        return next((c for c in s.children if c.anchor == anchor), None) if s else None

    def children(self, parent: str, exclude: tuple = ()) -> list[DocSection]:
        s = self.find(parent)
        return [c for c in s.children if c.anchor not in exclude] if s else []

    @property
    def intro_blocks(self) -> list[str]:
        from .data import split_blocks

        return split_blocks(self.intro_md)

    @property
    def lede_html(self) -> str:
        blocks = self.intro_blocks
        return self.md.inline(" ".join(blocks[0].split()), SOURCE) if blocks else ""

    @property
    def knows_html(self) -> str:
        """The intro after its first paragraph: what the server knows."""
        return self.render("\n\n".join(self.intro_blocks[1:]))

    def tools_section(self) -> dict:
        """The README's Tools section: its table as {tool: html}, and the
        paragraphs after it sorted by the page that shows them."""
        from .data import split_blocks

        s = self.find("tools")
        out = {"summary": {}, "resources_html": "", "prompts_html": "", "notes_html": []}
        if s is None:
            return out
        for block in split_blocks(s.body):
            if block.lstrip().startswith("|"):
                for line in block.splitlines():
                    m = TOOL_ROW.match(line.strip())
                    if m:
                        html = self.md.inline(m.group(2), SOURCE)
                        for name in re.findall(r"`([a-z_]+)`", m.group(1)):
                            out["summary"][name] = html
            elif block.startswith("**Resources:**"):
                out["resources_html"] = self.render(block)
            elif block.startswith("**Prompts:**"):
                out["prompts_html"] = self.render(block)
            else:
                out["notes_html"].append(self.render(block))
        return out

    # ---- surface ------------------------------------------------------------

    @property
    def tools(self) -> list[dict]:
        return list((self.surface or {}).get("tools", []))

    @property
    def prompts(self) -> list[dict]:
        return list((self.surface or {}).get("prompts", []))

    @property
    def resources(self) -> list[dict]:
        return list((self.surface or {}).get("resources", []))

    @property
    def templates(self) -> list[dict]:
        return list((self.surface or {}).get("resource_templates", []))

    @property
    def server(self) -> dict:
        return (self.surface or {}).get("server", {})

    def prompt(self, name: str) -> dict | None:
        return next((p for p in self.prompts if p.get("name") == name), None)

    def template(self, prefix: str) -> dict | None:
        return next((t for t in self.templates if t.get("uriTemplate", "").startswith(prefix)), None)

    @property
    def client_tabs(self) -> tuple:
        return CLIENT_TABS

    def setup_via(self, anchor: str) -> DocSection | None:
        """The section of the client another client is set up through, when
        the README sends it there ("configured as below") and its own section
        has no command or config. Once each client is a tab, "below" is a
        tab the reader is not looking at, so the panel shows that setup too."""
        own, via = self.find(anchor), CLIENT_SETUP_VIA.get(anchor)
        if own is None or via is None or CODE.search(own.body):
            return None
        return self.find(via)

    @property
    def instructions(self) -> str:
        return (self.surface or {}).get("instructions", "")

    @property
    def protocol(self) -> str:
        return (self.surface or {}).get("protocol_version", "")

    @property
    def named_resources(self) -> list[dict]:
        return [r for r in self.resources if not r.get("uri", "").startswith("cpuperf://file/")]

    @property
    def file_resources(self) -> list[dict]:
        return [r for r in self.resources if r.get("uri", "").startswith("cpuperf://file/")]

    @property
    def routed_examples(self) -> list[dict]:
        """The README's example questions with what the server's search tool
        returned for each at build time, keyed by question text."""
        return list((self.surface or {}).get("examples", []))

    def tool_access(self, tool: dict) -> str:
        a = tool.get("annotations") or {}
        return "network" if a.get("openWorldHint") else "read"

    def params(self, tool: dict) -> list[dict]:
        schema = tool.get("inputSchema") or {}
        required = set(schema.get("required", []))
        out = []
        for name, prop in (schema.get("properties") or {}).items():
            types = [prop.get("type")] if prop.get("type") else [x.get("type") for x in prop.get("anyOf", []) if x.get("type") != "null"]
            out.append({
                "name": name,
                "type": " | ".join(t for t in types if t) + (" (" + ", ".join(map(str, prop["enum"])) + ")" if prop.get("enum") else ""),
                "required": name in required,
                "default": prop.get("default"),
                "description": prop.get("description", ""),
            })
        out.sort(key=lambda x: (not x["required"], x["name"]))
        return out
