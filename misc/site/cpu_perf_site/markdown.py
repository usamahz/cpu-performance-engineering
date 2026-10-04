"""Markdown from the repository, rendered with markdown-it-py.

Raw HTML never passes through (html=False), HTML comments such as the
benchmark READMEs' results markers are dropped, links are rewritten by
paths.Links, headings carry GitHub's ids, and tables scroll in a wrapper.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt

from .paths import Links, is_external, slugify

COMMENT = re.compile(r"<!--.*?-->", re.S)
MD_LINK = re.compile(r"(\]\()([^)\s]+)(\))")


class Markdown:
    def __init__(self, links: Links):
        self.links = links
        md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
        md.enable("table")
        md.add_render_rule("table_open", lambda *a, **k: '<div class="table-wrap" tabindex="0"><table>\n')
        md.add_render_rule("table_close", lambda *a, **k: "</table></div>\n")
        self.md = md

    def _links(self, tokens, source: str, external_new_tab: bool) -> None:
        for tok in tokens:
            if tok.type == "inline" and tok.children:
                self._links(tok.children, source, external_new_tab)
            elif tok.type == "link_open":
                href = self.links.rewrite(tok.attrGet("href") or "", source)
                tok.attrSet("href", href)
                if is_external(href):
                    tok.attrSet("rel", "noopener")
                    if external_new_tab:
                        tok.attrSet("target", "_blank")

    def render(self, text: str, source: str, demote: int = 0, ids: bool = True, id_prefix: str = "",
               external_new_tab: bool = False) -> str:
        """A whole document or fragment. `demote` shifts heading levels down so a
        README's H2 can sit under a page's own H2."""
        tokens = self.md.parse(COMMENT.sub("", text), {})
        seen: dict[str, int] = {}
        for i, tok in enumerate(tokens):
            if tok.type in ("heading_open", "heading_close"):
                tok.tag = f"h{min(6, int(tok.tag[1]) + demote)}"
                if tok.type == "heading_open" and ids:
                    slug = slugify(tokens[i + 1].content)
                    n = seen.get(slug, 0)
                    seen[slug] = n + 1
                    tok.attrSet("id", id_prefix + (slug if n == 0 else f"{slug}-{n}"))
        self._links(tokens, source, external_new_tab)
        self._align(tokens)
        # code and tables scroll sideways, so they take keyboard focus
        return self.md.renderer.render(tokens, self.md.options, {}).replace("<pre>", '<pre tabindex="0">')

    @staticmethod
    def _align(tokens) -> None:
        """Column alignment as a class: the site's CSP allows no inline style,
        and markdown-it writes `|---:|` as style="text-align:right"."""
        for tok in tokens:
            if tok.type in ("th_open", "td_open"):
                style = tok.attrGet("style") or ""
                if style.startswith("text-align:"):
                    tok.attrs.pop("style", None)
                    tok.attrSet("class", "ta-" + style.split(":", 1)[1])

    def inline(self, text: str, source: str, external_new_tab: bool = False) -> str:
        """One line of markdown (a reason, a preamble) without a wrapping <p>."""
        tokens = self.md.parseInline(text, {})
        self._links(tokens, source, external_new_tab)
        return self.md.renderer.render(tokens, self.md.options, {})

    def absolutise(self, text: str, source: str, base_url: str) -> str:
        """Raw markdown with every relative link made absolute, for the .md twins
        agents read: site pages on this site, other files on GitHub."""

        def fix(m: re.Match) -> str:
            href = self.links.rewrite(m.group(2), source)
            if href.startswith("/"):
                href = base_url + href
            return m.group(1) + href + m.group(3)

        return MD_LINK.sub(fix, text)
