"""Tests for classification metrics."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import accuracy_score, f1_score

from src.metrics import compute_metrics, top_confusions


def test_compute_metrics_matches_sklearn() -> None:
    y_true = [0, 1, 2, 2, 1, 0, 2]
    y_pred = [0, 2, 2, 1, 1, 0, 2]
    metrics = compute_metrics(y_true, y_pred, num_classes=3)

    assert metrics["accuracy"] == accuracy_score(y_true, y_pred)
    assert metrics["macro_f1"] == f1_score(
        y_true, y_pred, labels=[0, 1, 2], average="macro", zero_division=0
    )
    assert metrics["num_samples"] == len(y_true)
    assert len(metrics["per_class"]) == 3
    assert np.asarray(metrics["confusion_matrix"]).shape == (3, 3)
    assert metrics["per_class"][2]["support"] == 3


def test_top_confusions_ignores_diagonal() -> None:
    matrix = np.array([[2, 1, 0], [0, 3, 4], [0, 0, 5]])
    pairs = top_confusions(matrix, limit=5)
    assert pairs[0] == {
        "true_id": 1,
        "true_name": "Speed limit 30",
        "pred_id": 2,
        "pred_name": "Speed limit 50",
        "count": 4,
    }
    assert all(pair["true_id"] != pair["pred_id"] for pair in pairs)
    assert len(pairs) == 2


def test_top_confusions_respects_limit() -> None:
    matrix = np.ones((3, 3), dtype=int)
    np.fill_diagonal(matrix, 0)
    assert len(top_confusions(matrix, limit=3)) == 3
