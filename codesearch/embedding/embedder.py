from __future__ import annotations

import threading


class Embedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class SentenceTransformersEmbedder(Embedder):
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # type: ignore
        from pathlib import Path

        escaped_name = model_name.replace("/", "_")
        cache_dir = Path(".model_cache") / escaped_name

        if cache_dir.exists():
            self._model = SentenceTransformer(str(cache_dir))
        else:
            self._model = SentenceTransformer(model_name)
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._model.save(str(cache_dir))

        self._lock = threading.Lock()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # SentenceTransformer is not reliably thread-safe across concurrent encode calls.
        with self._lock:
            vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vecs]

