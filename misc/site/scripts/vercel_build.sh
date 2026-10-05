#!/bin/sh
# The website's build on Vercel (vercel.json at the repository root runs it).
# Installs the site and the MCP server into a virtualenv, exports the corpus
# and the server's surface, builds misc/site/dist and checks it against the
# README; a failing check fails the deployment.
set -eu
cd "$(dirname "$0")/../../.."

py=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    py=$candidate
    break
  fi
done
[ -n "$py" ] || { echo "error: the site needs Python 3.11 or later" >&2; exit 1; }

# The address the pages carry in canonical links, the sitemap and the feeds:
# SITE_URL when set, else the production domain, else this preview's own URL.
if [ -n "${SITE_URL:-}" ]; then
  base=$SITE_URL
elif [ "${VERCEL_ENV:-}" = production ] && [ -n "${VERCEL_PROJECT_PRODUCTION_URL:-}" ]; then
  base=https://$VERCEL_PROJECT_PRODUCTION_URL
elif [ -n "${VERCEL_URL:-}" ]; then
  base=https://$VERCEL_URL
else
  base=http://localhost:8000
fi
echo "building with $("$py" --version) for $base"

"$py" -m venv .venv-site
venv=.venv-site/bin/python
"$venv" -m pip install --quiet --upgrade pip
"$venv" -m pip install --quiet -e misc/site ./misc/mcp
"$venv" misc/site/scripts/export_corpus.py
"$venv" misc/site/scripts/export_mcp.py
"$venv" -m cpu_perf_site build --base-url "$base"
"$venv" -m cpu_perf_site check --base-url "$base"
