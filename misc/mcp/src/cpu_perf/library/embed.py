"""Sentence embeddings for semantic search. model2vec static embeddings run on
the CPU at thousands of passages per second; a deterministic hashing embedder
stands in for tests and as a last resort. If neither is wanted, the library
runs on keyword search alone."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading

from ..text import tokens

log = logging.getLogger("cpu_perf.embed")

DEFAULT_MODEL = "minishlab/potion-base-8M"


class Embedder:
    name: str = "none"
    dim: int = 0

    def encode(self, texts: list[str]):  # -> numpy.ndarray (n, dim), rows unit length
        raise NotImplementedError


class HashingEmbedder(Embedder):
    """Feature hashing over folded tokens: deterministic, no download.
    Captures shared vocabulary, not meaning; used in tests."""

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.name = f"hashing-{dim}"

    def encode(self, texts: list[str]):
        import numpy as np

        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in tokens(t):
                h = hashlib.blake2b(tok.encode(), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                sign = 1.0 if h[4] & 1 else -1.0
                out[i, idx] += sign
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


class Model2VecEmbedder(Embedder):
    def __init__(self, model_id: str = DEFAULT_MODEL):
        self.model_id = model_id
        self.name = f"model2vec:{model_id}"
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is None:
                from model2vec import StaticModel

                self._model = StaticModel.from_pretrained(self.model_id, force_download=False)
                self.dim = int(self._model.dim) if hasattr(self._model, "dim") else int(self._model.encode(["x"]).shape[1])

    def encode(self, texts: list[str]):
        import numpy as np

        self.load()
        vecs = np.asarray(self._model.encode(texts, use_multiprocessing=False), dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms


_cache: dict[str, Embedder | None] = {}


def get_embedder(name: str | None = None) -> Embedder | None:
    """The configured embedder, or None for keyword-only search.

    `name`/CPU_PERF_EMBED_MODEL: a model2vec model id (default
    minishlab/potion-base-8M), "hashing" for the test embedder, or "none"."""
    name = name or os.environ.get("CPU_PERF_EMBED_MODEL") or DEFAULT_MODEL
    if name in _cache:
        return _cache[name]
    emb: Embedder | None
    if name.lower() in ("none", "off", "0", "false"):
        emb = None
    elif name.lower().startswith("hashing"):
        emb = HashingEmbedder()
    else:
        try:
            m = Model2VecEmbedder(name)
            m.load()
            emb = m
        except Exception as exc:  # no network, no model, no package: keyword-only
            if sys.is_finalizing():
                return None  # the client closed the server while the model was loading
            log.warning("semantic search unavailable (%s: %s); using keyword search only", type(exc).__name__, exc)
            emb = None
    _cache[name] = emb
    return emb
