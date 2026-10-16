"""Local, privacy-preserving sentence embeddings backed by ONNX/FastEmbed."""
from __future__ import annotations

import threading
import math
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout


DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class FastEmbedAdapter:
    model_id = DEFAULT_MODEL
    dimensions = 384

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="libra-embed")

    def _embed_sync(self, text: str) -> list[float]:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=self.model_id)
            return [float(value) for value in next(iter(self._model.embed([text])))]

    def _embed_many_sync(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=self.model_id)
            return [[float(value) for value in vector] for vector in self._model.embed(texts)]

    def warmup(self, *, timeout_seconds: float = 120) -> None:
        """Load the model and run first inference outside the short query budget."""
        self.embed('准备就绪', timeout_seconds=timeout_seconds)

    def embed(self, text: str, *, timeout_seconds: float) -> list[float]:
        future = self._executor.submit(self._embed_sync, str(text)[:8000])
        try:
            return future.result(timeout=max(0.1, timeout_seconds))
        except FutureTimeout as error:
            future.cancel()
            raise TimeoutError("local embedding timed out") from error

    def embed_many(self, texts: list[str], *, timeout_seconds: float) -> list[list[float]]:
        cleaned = [str(text)[:8000] for text in texts]
        future = self._executor.submit(self._embed_many_sync, cleaned)
        try:
            return future.result(timeout=max(0.1, timeout_seconds))
        except FutureTimeout as error:
            future.cancel()
            raise TimeoutError("local embedding batch timed out") from error


def normalized(vector) -> list[float]:
    values = [float(value) for value in vector]
    magnitude = math.sqrt(sum(value * value for value in values))
    if not magnitude:
        return []
    return [value / magnitude for value in values]


_adapter: FastEmbedAdapter | None = None


def get_local_embedding_adapter() -> FastEmbedAdapter:
    global _adapter
    if _adapter is None:
        _adapter = FastEmbedAdapter()
    return _adapter
