"""Optional cross-encoder reranking for the top retrieval candidates."""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float] | None: ...


class NoopReranker:
    def score(self, query: str, passages: list[str]) -> list[float] | None:
        return None


class CrossEncoderReranker:
    """A small transformer cross-encoder, evaluated on CPU."""

    def __init__(
        self,
        model_name: str,
        *,
        batch_size: int = 8,
        max_length: int = 512,
        device: str = "cpu",
    ) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.eval()
        self.model.to(device)
        self.batch_size = batch_size
        self.max_length = max_length
        self.device = device
        torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))

    def score(self, query: str, passages: list[str]) -> list[float] | None:
        if not passages:
            return []
        scores: list[float] = []
        with self._torch.no_grad():
            for start in range(0, len(passages), self.batch_size):
                batch = passages[start : start + self.batch_size]
                encoded = self.tokenizer(
                    [(query, passage) for passage in batch],
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                logits = self.model(**encoded).logits
                if logits.shape[-1] == 1:
                    batch_scores = self._torch.sigmoid(logits.squeeze(-1))
                else:
                    batch_scores = self._torch.softmax(logits, dim=-1)[:, -1]
                scores.extend(float(value) for value in batch_scores.cpu())
        return scores


def get_reranker(settings: Any) -> Reranker:
    if not settings.use_reranker:
        return NoopReranker()
    try:
        return CrossEncoderReranker(
            settings.reranker_model,
            batch_size=settings.reranker_batch_size,
        )
    except Exception as error:  # pragma: no cover - depends on local model cache
        logger.warning("No se pudo cargar el reranker (%s). Se usará RRF.", error)
        return NoopReranker()
