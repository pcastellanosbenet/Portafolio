"""Evaluation metrics for multi-class classification."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

from src.labels import CLASS_NAMES, NUM_CLASSES


def compute_metrics(
    y_true: list[int] | np.ndarray,
    y_pred: list[int] | np.ndarray,
    num_classes: int = NUM_CLASSES,
) -> dict[str, Any]:
    """Compute accuracy, macro/weighted F1 and per-class metrics."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    labels = list(range(num_classes))

    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=labels,
        zero_division=0,
    )
    matrix = confusion_matrix(y_true, y_pred, labels=labels)

    per_class = []
    for class_id in labels:
        per_class.append(
            {
                "class_id": class_id,
                "name": CLASS_NAMES[class_id] if class_id < len(CLASS_NAMES) else str(class_id),
                "precision": float(precision[class_id]),
                "recall": float(recall[class_id]),
                "f1": float(f1[class_id]),
                "support": int(support[class_id]),
            }
        )

    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(
            f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)
        ),
        "weighted_f1": float(
            f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0)
        ),
        "num_samples": int(len(y_true)),
        "per_class": per_class,
        "confusion_matrix": matrix.tolist(),
    }


def top_confusions(
    matrix: list[list[int]] | np.ndarray,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Return the most frequent off-diagonal confusions."""
    matrix = np.asarray(matrix)
    pairs: list[dict[str, Any]] = []
    for true_id in range(matrix.shape[0]):
        for pred_id in range(matrix.shape[1]):
            if true_id == pred_id:
                continue
            count = int(matrix[true_id, pred_id])
            if count == 0:
                continue
            pairs.append(
                {
                    "true_id": true_id,
                    "true_name": CLASS_NAMES[true_id],
                    "pred_id": pred_id,
                    "pred_name": CLASS_NAMES[pred_id],
                    "count": count,
                }
            )
    pairs.sort(key=lambda item: item["count"], reverse=True)
    return pairs[:limit]
