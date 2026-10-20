"""Plotting helpers for training and evaluation artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from src.labels import CLASS_NAMES


def denormalize(
    image: torch.Tensor,
    mean: Sequence[float],
    std: Sequence[float],
) -> np.ndarray:
    """Convert a normalized CHW tensor into an HWC numpy image in [0, 1]."""
    mean_tensor = torch.tensor(mean, dtype=image.dtype).view(3, 1, 1)
    std_tensor = torch.tensor(std, dtype=image.dtype).view(3, 1, 1)
    image = (image * std_tensor + mean_tensor).clamp(0, 1)
    return image.permute(1, 2, 0).numpy()


def plot_confusion_matrix(
    matrix: list[list[int]] | np.ndarray,
    out_path: str | Path,
    normalize: bool = True,
) -> None:
    """Save a confusion matrix with one row/column per class."""
    cm = np.asarray(matrix, dtype=float)
    if normalize:
        row_sums = cm.sum(axis=1, keepdims=True)
        cm = np.divide(cm, row_sums, out=np.zeros_like(cm), where=row_sums != 0)

    fig, ax = plt.subplots(figsize=(18, 16))
    image = ax.imshow(cm, cmap="Blues", vmin=0, vmax=1 if normalize else None)
    ax.set_title("Confusion matrix (row-normalized)" if normalize else "Confusion matrix")
    ax.set_xlabel("Predicted class")
    ax.set_ylabel("True class")
    ticks = np.arange(len(CLASS_NAMES))
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)
    ax.set_xticklabels([str(i) for i in ticks], rotation=90, fontsize=7)
    ax.set_yticklabels([str(i) for i in ticks], fontsize=7)
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_training_curves(history_path: str | Path, out_path: str | Path) -> None:
    """Save loss, accuracy and macro-F1 curves from a history CSV."""
    history = pd.read_csv(history_path)
    if history.empty:
        return

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    axes[0].plot(history["epoch"], history["train_loss"], label="train")
    axes[0].plot(history["epoch"], history["val_loss"], label="validation")
    axes[0].set_title("Loss")
    axes[0].set_xlabel("Epoch")
    axes[0].legend()

    axes[1].plot(history["epoch"], history["train_accuracy"], label="train")
    axes[1].plot(history["epoch"], history["val_accuracy"], label="validation")
    axes[1].set_title("Accuracy")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylim(0, 1.02)
    axes[1].legend()

    axes[2].plot(history["epoch"], history["val_macro_f1"], color="tab:green")
    best_row = history.loc[history["val_macro_f1"].idxmax()]
    axes[2].scatter(
        best_row["epoch"],
        best_row["val_macro_f1"],
        color="black",
        zorder=3,
        label=f"best ({best_row['val_macro_f1']:.4f})",
    )
    axes[2].set_title("Validation macro-F1")
    axes[2].set_xlabel("Epoch")
    axes[2].set_ylim(0, 1.02)
    axes[2].legend()

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_class_distribution(
    counts: Sequence[int],
    out_path: str | Path,
) -> None:
    """Save a bar chart with the number of samples per class."""
    fig, ax = plt.subplots(figsize=(14, 5))
    positions = np.arange(len(counts))
    ax.bar(positions, counts, color="tab:blue")
    ax.set_title("Training set class distribution")
    ax.set_xlabel("Class id")
    ax.set_ylabel("Images")
    ax.set_xticks(positions)
    ax.set_xticklabels([str(i) for i in positions], rotation=90, fontsize=7)
    ax.axhline(np.median(counts), color="tab:red", linestyle="--", label="median")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_samples(
    dataset: Dataset,
    out_path: str | Path,
    mean: Sequence[float],
    std: Sequence[float],
    num_samples: int = 16,
    seed: int = 42,
) -> None:
    """Save a grid of random training images with their labels."""
    rng = np.random.default_rng(seed)
    indices = rng.choice(len(dataset), size=min(num_samples, len(dataset)), replace=False)
    grid_size = int(np.ceil(np.sqrt(len(indices))))

    fig, axes = plt.subplots(grid_size, grid_size, figsize=(12, 12))
    axes = np.atleast_2d(axes)
    for ax in axes.flat:
        ax.axis("off")

    for ax, index in zip(axes.flat, indices, strict=False):
        image, label = dataset[int(index)]
        ax.imshow(denormalize(image, mean, std))
        ax.set_title(CLASS_NAMES[label], fontsize=8)
        ax.axis("off")

    fig.suptitle("Sample training images", fontsize=14)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_errors(
    images: Sequence[torch.Tensor],
    true_labels: Sequence[int],
    pred_labels: Sequence[int],
    confidences: Sequence[float],
    out_path: str | Path,
    mean: Sequence[float],
    std: Sequence[float],
) -> None:
    """Save a grid of misclassified images with true and predicted labels."""
    if not images:
        return

    num_images = min(len(images), 16)
    grid_size = int(np.ceil(np.sqrt(num_images)))
    fig, axes = plt.subplots(grid_size, grid_size, figsize=(14, 14))
    axes = np.atleast_2d(axes)
    for ax in axes.flat:
        ax.axis("off")

    for ax, image, true_label, pred_label, confidence in zip(
        axes.flat,
        images[:num_images],
        true_labels[:num_images],
        pred_labels[:num_images],
        confidences[:num_images],
        strict=False,
    ):
        ax.imshow(denormalize(image, mean, std))
        ax.set_title(
            f"T: {CLASS_NAMES[int(true_label)]}\nP: {CLASS_NAMES[int(pred_label)]} "
            f"({float(confidence):.2f})",
            fontsize=7,
        )
        ax.axis("off")

    fig.suptitle("Misclassified test images", fontsize=14)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
