"""cpuperf.com: a static rendering of the CPU Performance Engineering list.

The site never parses the README itself. scripts/export_corpus.py runs the
MCP server's parser (cpu_perf.corpus) and writes build/export.json; this
package turns that file, plus the site's own configuration and templates,
into dist/. The output is a pure function of those inputs.
"""

from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SITE_ROOT.parent.parent
