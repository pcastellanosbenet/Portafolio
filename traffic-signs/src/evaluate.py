"""Evaluate a trained traffic-sign classifier and save artifacts."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Subset
from tqdm import tqdm

from src.config import get_device, set_seed
from src.data import (
    GTSRBDataset,
    build_transforms,
    dataset_summary,
    normalization,
    stratified_split,
)
from src.labels import CLASS_NAMES
from src.metrics import compute_metrics, top_confusions
from src.model import build_model
from src.viz import plot_confusion_matrix, plot_errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, help="Path to a .pt checkpoint.")
    parser.add_argument("--split", default="test", choices=("test", "val"))
    parser.add_argument("--output", default=None, help="Output directory for artifacts.")
    parser.add_argument("--device", default=None, help="cpu, cuda or mps.")
    parser.add_argument("--batch-size", type=int, default=None)
    return parser.parse_args()


@torch.no_grad()
def predict(
    model: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> tuple[list[int], list[int], list[float], list[str], list[torch.Tensor]]:
    model.eval()
    targets: list[int] = []
    predictions: list[int] = []
    confidences: list[float] = []
    paths: list[str] = []
    error_images: list[torch.Tensor] = []

    for images, labels, batch_paths in tqdm(loader, desc="evaluate", leave=False):
        images = images.to(device)
        logits = model(images)
        probabilities = torch.softmax(logits, dim=1)
        confidence, prediction = probabilities.max(dim=1)

        targets.extend(labels.tolist())
        predictions.extend(prediction.cpu().tolist())
        confidences.extend(confidence.cpu().tolist())
        paths.extend(list(batch_paths))

        mask = prediction.cpu() != labels
        error_images.extend(images[mask].cpu())

    return targets, predictions, confidences, paths, error_images


def main() -> None:
    args = parse_args()
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    config = checkpoint["config"]
    set_seed(int(config["seed"]))
    torch.set_num_threads(int(config.get("threads", 4)))
    device = get_device(args.device)

    data_config = config["data"]
    image_size = int(data_config["image_size"])
    pretrained = bool(config["model"].get("pretrained", False))
    transform = build_transforms(image_size, train=False, pretrained=pretrained)

    if args.split == "test":
        dataset = GTSRBDataset(
            data_config["root"],
            split="test",
            transform=transform,
            return_path=True,
        )
    else:
        full_train = GTSRBDataset(
            data_config["root"],
            split="train",
            transform=transform,
            return_path=True,
        )
        _, val_idx = stratified_split(
            full_train.labels,
            val_fraction=float(data_config["val_fraction"]),
            seed=int(config["seed"]),
        )
        dataset = Subset(full_train, val_idx.tolist())

    loader = DataLoader(
        dataset,
        batch_size=args.batch_size or int(data_config["batch_size"]),
        shuffle=False,
        num_workers=int(data_config["num_workers"]),
        pin_memory=False,
        persistent_workers=int(data_config["num_workers"]) > 0,
    )

    eval_config = copy.deepcopy(config)
    eval_config["model"]["pretrained"] = False
    model = build_model(eval_config)
    model.load_state_dict(checkpoint["model_state"])
    model.to(device)

    targets, predictions, confidences, paths, error_images = predict(model, loader, device)
    metrics = compute_metrics(targets, predictions)
    mean, std = normalization(pretrained)

    output_dir = Path(
        args.output
        or Path(config["output"]["results_dir"]) / config["output"]["run_name"] / args.split
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "checkpoint": str(args.checkpoint),
        "split": args.split,
        "model": config["model"]["name"],
        "run_name": config["output"]["run_name"],
        "config": config,
        "dataset": dataset_summary(targets),
        "metrics": metrics,
    }
    with (output_dir / "metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    pd.DataFrame(metrics["per_class"]).to_csv(
        output_dir / "classification_report.csv", index=False
    )
    confusions = top_confusions(metrics["confusion_matrix"])
    pd.DataFrame(confusions).to_csv(output_dir / "top_confusions.csv", index=False)

    misclassified = pd.DataFrame(
        {
            "path": paths,
            "true_id": targets,
            "true_name": [CLASS_NAMES[index] for index in targets],
            "pred_id": predictions,
            "pred_name": [CLASS_NAMES[index] for index in predictions],
            "confidence": confidences,
        }
    )
    misclassified[misclassified["true_id"] != misclassified["pred_id"]].to_csv(
        output_dir / "misclassified.csv", index=False
    )

    plot_confusion_matrix(
        metrics["confusion_matrix"],
        output_dir / "confusion_matrix.png",
    )
    misclassified_indices = np.flatnonzero(np.asarray(targets) != np.asarray(predictions))
    plot_errors(
        error_images,
        [targets[index] for index in misclassified_indices],
        [predictions[index] for index in misclassified_indices],
        [confidences[index] for index in misclassified_indices],
        output_dir / "errors.png",
        mean,
        std,
    )

    print(f"Split: {args.split} ({metrics['num_samples']:,} images)")
    print(f"Accuracy: {metrics['accuracy']:.4f}")
    print(f"Macro-F1: {metrics['macro_f1']:.4f}")
    print(f"Weighted-F1: {metrics['weighted_f1']:.4f}")
    print(f"Artifacts: {output_dir}")


if __name__ == "__main__":
    main()
