from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from cpu_perf import corpus as corpus_mod
from cpu_perf.locate import locate
from cpu_perf.resolve import Resolver
from cpu_perf.search import SearchIndex


@pytest.fixture(scope="session")
def corpus():
    # Automatic location: the checkout when run from the repository, the
    # bundled copy when run against an installed wheel.
    return corpus_mod.load(locate())


@pytest.fixture(scope="session")
def index(corpus):
    return SearchIndex(corpus)


@pytest.fixture(scope="session")
def resolver(corpus, index):
    return Resolver(corpus, index)


@pytest.fixture(scope="session")
def check_format(corpus):
    """misc/scripts/check_format.py, loaded from wherever the corpus lives."""
    root = corpus.reader.root
    if not isinstance(root, Path):
        root = Path(str(root))
    path = root / "misc" / "scripts" / "check_format.py"
    if not path.is_file():
        pytest.skip("check_format.py not available in this corpus")
    spec = importlib.util.spec_from_file_location("check_format", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, root
