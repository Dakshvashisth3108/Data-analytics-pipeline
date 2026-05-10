"""sentence-transformers wrapper.

The model is loaded lazily on first ``embed()`` call, so importing the
module is cheap (no torch download, no GPU init) and tests can swap in
a fake embedder by injecting a precomputed vector list.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from utils import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

LOG = get_logger("hcm.embeddings.embedder")


class Embedder:
    """Encodes lists of strings into normalized dense vectors.

    Default model: ``sentence-transformers/all-MiniLM-L6-v2`` -- 384
    dims, ~80 MB, fast on CPU, plenty for short business prose.
    """

    def __init__(self,
                 model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
                 device: str | None = None) -> None:
        self.model_name = model_name
        self.device = device
        self._model: SentenceTransformer | None = None

    def _ensure_loaded(self) -> "SentenceTransformer":
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            LOG.info("loading_model name=%s device=%s",
                     self.model_name, self.device or "auto")
            self._model = SentenceTransformer(
                self.model_name, device=self.device,
            )
            dim = self._model.get_sentence_embedding_dimension()
            LOG.info("model_loaded dim=%d", dim)
        return self._model

    def dim(self) -> int:
        return self._ensure_loaded().get_sentence_embedding_dimension()

    def embed(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Embed a list of strings. Returns a list of float lists (Chroma-ready)."""
        if not texts:
            return []
        model = self._ensure_loaded()
        try:
            vectors = model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,   # cosine similarity = dot product
            )
        except Exception:
            LOG.exception("embedding_failed batch_size=%d count=%d",
                          batch_size, len(texts))
            raise
        return vectors.tolist()
