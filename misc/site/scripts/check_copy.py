"""Lint every string the site writes itself against misc/notes/voice.md.

The site's own words live in copy.toml, plus the titles and labels in
charts.toml; everything else on the site is quoted from the repository and
linted there by misc/scripts/check_format.py. The rules are the README's:
no second person, no exclamation marks, no adjectives of praise, no em
dashes or spaced en dashes, British spelling (quantization excepted), and
no placeholder text.

    python misc/site/scripts/check_copy.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]

RULES = [
    (re.compile(r"\b(you|your|yours|yourself|yourselves|we|our|ours|ourselves)\b", re.I), "addresses the reader"),
    (re.compile(r"!"), "exclamation mark"),
    (re.compile(r"\b(comprehensive|essential|excellent|seminal|must-read|great|powerful|deep|amazing|awesome|"
                r"incredible|ultimate|world-class|cutting-edge|best-in-class|state-of-the-art|blazing|seamless|"
                r"effortless|revolutionary|game-changing)\b", re.I), "adjective of praise"),
    (re.compile("—"), "em dash"),
    (re.compile(" – "), "en dash as a separator"),
    (re.compile(r"\b(TODO|TBD|FIXME|lorem ipsum|coming soon|placeholder)\b", re.I), "placeholder text"),
    (re.compile(r"\b(optimiz\w*|analyz\w*|behavior\w*|colou?r(?<!colour)|center\w*|favor\w*|neighbor\w*|"
                r"organiz\w*|summariz\w*|recogniz\w*|prioritiz\w*|minimiz\w*|maximiz\w*|vectoriz\w*|"
                r"paralleliz\w*|normaliz\w*|serializ\w*|initializ\w*|visualiz\w*|utiliz\w*|customiz\w*|"
                r"categoriz\w*|characteriz\w*|standardiz\w*|synchroniz\w*|catalog\b|modeling|labeled)\b", re.I),
     "American spelling"),
]
# Strings that name things the site does not get to respell: code, identifiers,
# the README's own section and field names quoted as data keys.
ALLOW = re.compile(r"QOS_CLASS_\w+|taskpolicy|-fno-\S+|\bSINK\(\)")


def strings(node, path: str = ""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from strings(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from strings(v, f"{path}[{i}]")


CHART_TEXT = re.compile(r"(^|\.)(title|metric|label|labels\.[^.]+|name|short)$")


def lint() -> list[str]:
    problems = []
    copy = tomllib.loads((SITE / "copy.toml").read_text(encoding="utf-8"))
    charts = tomllib.loads((SITE / "charts.toml").read_text(encoding="utf-8"))
    sources = [("copy.toml", path, text) for path, text in strings(copy)]
    for i, spec in enumerate(charts.get("chart", [])):
        for path, text in strings(spec, f"chart[{i}]:{spec.get('benchmark', '?')}"):
            if CHART_TEXT.search(path.split(":", 1)[-1]):
                sources.append(("charts.toml", path, text))
    for file, path, text in sources:
        plain = ALLOW.sub("", re.sub(r"\{=?[^}]*\}", "", text))
        for rx, why in RULES:
            m = rx.search(plain)
            if m:
                problems.append(f"{file} {path}: {why} ({m.group(0)!r}) in {text!r}")
    return problems


def main() -> int:
    problems = lint()
    for p in problems:
        print(p)
    print(f"check_copy: {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
