"""Retrieval quality on everyday questions. The floors only ever go up."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cpu_perf.library.retrieve import Retriever
from cpu_perf.library.store import Store

from eval_queries import eval_library, eval_list

LIST_FLOOR = 1.0
LIBRARY_FLOOR = 0.92
# Share of spreadsheet rows among prose answers. Off-topic prose is now filtered out, so
# what remains of the share is rows that name the topic (Intel's False_Sharing metric).
TABLE_SHARE_CEILING = 0.25


def test_list_layer_answers_everyday_questions(index):
    res = eval_list(index)
    misses = [(r["q"], r["got"]) for r in res["rows"] if not r["ok"]]
    assert res["recall"] >= LIST_FLOOR, misses


@pytest.mark.skipif(not os.environ.get("CPU_PERF_EVAL_DB"), reason="set CPU_PERF_EVAL_DB to a crawled library.sqlite")
def test_library_answers_everyday_questions(index):
    store = Store(Path(os.environ["CPU_PERF_EVAL_DB"]), readonly=True)
    res = eval_library(Retriever(store, lambda: None, index.expand))
    misses = [(r["q"], [u.rsplit("/", 1)[-1] for u in r["got"]]) for r in res["rows"] if not r["ok"]]
    assert res["recall"] >= LIBRARY_FLOOR, misses
    assert round(res["table_share"], 2) <= TABLE_SHARE_CEILING
