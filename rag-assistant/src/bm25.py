"""A small, dependency-free BM25 Okapi implementation."""

from __future__ import annotations

import math
from collections import Counter


class BM25Index:
    """BM25 index over an in-memory list of tokenised documents."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_freqs: list[Counter[str]] = []
        self.doc_lengths: list[int] = []
        self.idf: dict[str, float] = {}
        self.avg_length = 0.0

    def fit(self, documents: list[list[str]]) -> None:
        self.doc_freqs = [Counter(tokens) for tokens in documents]
        self.doc_lengths = [len(tokens) for tokens in documents]
        self.avg_length = (
            sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 0.0
        )
        document_frequency: Counter[str] = Counter()
        for freqs in self.doc_freqs:
            document_frequency.update(freqs.keys())
        total = len(documents)
        self.idf = {
            term: math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        if not self.doc_freqs or self.avg_length == 0:
            return []
        scores = [0.0] * len(self.doc_freqs)
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for index, freqs in enumerate(self.doc_freqs):
                frequency = freqs.get(term, 0)
                if not frequency:
                    continue
                length = self.doc_lengths[index]
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * length / self.avg_length
                )
                scores[index] += idf * frequency * (self.k1 + 1) / denominator
        return scores

    def top_n(self, query_tokens: list[str], n: int) -> list[tuple[int, float]]:
        scores = self.get_scores(query_tokens)
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        return [(index, score) for index, score in ranked[:n] if score > 0]
