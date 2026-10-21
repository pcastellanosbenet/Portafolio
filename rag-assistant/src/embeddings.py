"""Embedding backends: local transformer models and a deterministic test backend."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Protocol

import numpy as np

from src.text import tokenize


class Embedder(Protocol):
    dimension: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class HashingEmbedder:
    """Deterministic signed feature hashing.

    This backend is intentionally simple. It is used in tests and as a fallback
    when no model is available; it is not a semantic embedding model.
    """

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def _embed(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        return np.vstack([self._embed(text) for text in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed(text)


class TransformerEmbedder:
    """Mean-pooled transformer embeddings, CPU-friendly by default."""

    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        max_length: int = 512,
        batch_size: int = 16,
        dimension: int | None = None,
    ) -> None:
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as error:  # pragma: no cover - exercised only without deps
            raise RuntimeError(
                "Para usar embeddings reales instala torch y transformers."
            ) from error

        self._torch = torch
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self.batch_size = batch_size
        self._prefix_documents = "passage: " if "e5" in model_name.lower() else ""
        self._prefix_query = "query: " if "e5" in model_name.lower() else ""
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        self.model.eval()
        self.model.to(device)
        detected = int(self.model.config.hidden_size)
        self.dimension = dimension or detected
        if dimension and dimension != detected:
            raise ValueError(
                f"El modelo {model_name} produce {detected} dimensiones, "
                f"pero la configuración declara {dimension}."
            )
        # Use physical cores rather than all logical CPUs on small laptops.
        torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))

    def _encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        vectors: list[np.ndarray] = []
        with self._torch.no_grad():
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start : start + self.batch_size]
                encoded = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                outputs = self.model(**encoded)
                hidden = outputs.last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).float()
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
                pooled = self._torch.nn.functional.normalize(pooled, p=2, dim=1)
                vectors.append(pooled.cpu().numpy().astype(np.float32))
        return np.vstack(vectors)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode([self._prefix_documents + text for text in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([self._prefix_query + text])[0]


def get_embedder(settings: Any) -> Embedder:
    backend = settings.embedding_backend.lower().strip()
    if backend == "hashing":
        return HashingEmbedder(dimension=settings.embedding_dimension)
    if backend != "transformers":
        raise ValueError(f"Backend de embeddings desconocido: {settings.embedding_backend}")
    return TransformerEmbedder(
        settings.embedding_model,
        max_length=settings.embedding_max_length,
        batch_size=settings.embedding_batch_size,
        dimension=settings.embedding_dimension,
    )


def embed_in_batches(
    embedder: Embedder,
    texts: list[str],
    batch_size: int = 64,
) -> np.ndarray:
    """Embed a large list in manageable batches, preserving order."""
    vectors: list[np.ndarray] = []
    for start in range(0, len(texts), batch_size):
        vectors.append(embedder.embed_documents(texts[start : start + batch_size]))
    if not vectors:
        return np.empty((0, embedder.dimension), dtype=np.float32)
    return np.vstack(vectors)
