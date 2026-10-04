"""Dump what the MCP server shows a client, for the site's MCP pages.

Starts cpu-perf over stdio against this checkout as a user gets it by
default, source library and live fetching included, but with an empty
temporary data directory, no background indexing, no update check and no
embedding model, so listing it reads nothing from the network. It writes
what a client sees on connecting: the server's name, version and instructions,
the protocol version, and the tools, prompts, resources and resource
templates as the server itself lists them. It also puts each example
question in the server's README through the server's own `search` tool, so
the site can file each one under the section and benchmark the server
finds for it. The MCP pages render from this file and misc/mcp/README.md
only, so they cannot describe a tool, prompt or template the server does
not have.

Needs the server installed (pip install ./misc/mcp); uses the same
mcp.Client API as .github/workflows/mcp.yml.

    python misc/site/scripts/export_mcp.py --out misc/site/build
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[3]
TIMEOUT = 60
EXAMPLES_INTRO = re.compile(r"ask, for example", re.I)


def examples(readme: str) -> list[str]:
    """The bulleted questions after "ask, for example" in the server's README
    (cpu_perf_site.mcp reads the same list for the page)."""
    out, on = [], False
    for line in readme.splitlines():
        if EXAMPLES_INTRO.search(line):
            on = True
        elif on and line.startswith("- "):
            out.append(line[2:].strip())
        elif on and out and not line.strip():
            break
    return out


def dump(model) -> dict:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


async def listing(method, key: str) -> list[dict]:
    items, cursor = [], None
    while True:
        result = await method(cursor=cursor)
        items += [dump(x) for x in getattr(result, key)]
        cursor = getattr(result, "next_cursor", None) or getattr(result, "nextCursor", None)
        if not cursor:
            return items


async def route(client, question: str) -> list[dict]:
    """What the server's search tool returns for one example question."""
    query = question.replace("`", "")
    result = await client.call_tool("search", {"query": query})
    if result.is_error or not result.structured_content:
        raise SystemExit(f"search failed for {query!r}: {result.content}")
    return [{"id": r["id"], "title": r["title"]} for r in result.structured_content.get("results", [])[:5]]


async def surface(repo: Path, data_dir: str) -> dict:
    env = {**os.environ, "CPU_PERF_EMBED_MODEL": "none", "CPU_PERF_LOG_LEVEL": "ERROR"}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cpu_perf", "serve", "--repo", str(repo), "--data-dir", data_dir,
              "--no-auto-update", "--no-auto-index"],
        env=env,
    )
    with anyio.fail_after(TIMEOUT):
        async with Client(params) as client:
            info = client.server_info
            return {
                "schema": "cpu-perf-site-mcp-surface",
                "schema_version": 1,
                "server": dump(info) if info is not None else {},
                "protocol_version": client.protocol_version,
                "instructions": client.instructions or "",
                "tools": await listing(client.list_tools, "tools"),
                "prompts": await listing(client.list_prompts, "prompts"),
                "resources": await listing(client.list_resources, "resources"),
                "resource_templates": await listing(client.list_resource_templates, "resource_templates"),
                "examples": [{"question": q, "results": await route(client, q)}
                             for q in examples((repo / "misc" / "mcp" / "README.md").read_text(encoding="utf-8"))],
            }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=ROOT / "misc" / "site" / "build")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="cpu-perf-site-") as data_dir:
        data = anyio.run(surface, args.repo.resolve(), data_dir)
    for key in ("tools", "prompts", "resources", "resource_templates"):
        data[key].sort(key=lambda x: x.get("name") or x.get("uri") or x.get("uriTemplate") or "")
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "mcp-surface.json"
    path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    server = data["server"]
    print(f"{server.get('name', '?')} {server.get('version', '?')}, protocol {data['protocol_version']}: "
          f"{len(data['tools'])} tools, {len(data['prompts'])} prompts, {len(data['resources'])} resources, "
          f"{len(data['resource_templates'])} templates, {len(data['examples'])} example questions routed -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
