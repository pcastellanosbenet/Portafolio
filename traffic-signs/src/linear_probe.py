"""Transfer-learning baseline: multinomial logistic regression on frozen MobileNetV3 features.

The ImageNet backbone is used as a fixed feature extractor. A linear classifier
(logistic regression) is trained on top with PyTorch, which keeps the experiment
viable on CPU while measuring how useful pretrained visual features are for GTSRB.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from torchvision import models
from tqdm import tqdm

from src.config import get_device, load_config, set_seed
from src.data import GTSRBDataset, build_transforms, compute_class_weights, stratified_split
from src.labels import CLASS_NAMES, NUM_CLASSES
from src.metrics import compute_metrics, top_confusions
from src.viz import plot_confusion_matrix, plot_errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to a YAML config.")
    parser.add_argument("--output", default=None, help="Directory for artifacts.")
    parser.add_argument("--cache-dir", default="checkpoints", help="Feature cache directory.")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--device", default=None, help="cpu, cuda or mps.")
    parser.add_argument("--force-extract", action="store_true", help="Ignore cached features.")
    return parser.parse_args()


def build_backbone(device: torch.device) -> tuple[nn.Module, nn.Module]:
    """Return a frozen MobileNetV3-Small feature extractor and a pooling layer."""
    weights = models.MobileNet_V3_Small_Weights.DEFAULT
    model = models.mobilenet_v3_small(weights=weights)
    backbone = model.features.to(device).eval()
    for parameter in backbone.parameters():
        parameter.requires_grad = False
    return backbone, nn.AdaptiveAvgPool2d(1).to(device)


@torch.no_grad()
def extract_features(
    loader: DataLoader,
    backbone: nn.Module,
    pool: nn.Module,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    features: list[np.ndarray] = []
    labels: list[int] = []
    paths: list[str] = []

    for images, targets, batch_paths in tqdm(loader, desc="features", leave=False):
        output = pool(backbone(images.to(device))).flatten(1)
        features.append(output.cpu().numpy())
        labels.extend(targets.tolist())
        paths.extend(list(batch_paths))

    return np.concatenate(features), np.asarray(labels), paths


def load_features(
    cache_path: Path,
    loader: DataLoader,
    backbone: nn.Module,
    pool: nn.Module,
    device: torch.device,
    force: bool = False,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    if cache_path.is_file() and not force:
        cached = np.load(cache_path)
        return cached["features"], cached["labels"], cached["paths"].tolist()

    features, labels, paths = extract_features(loader, backbone, pool, device)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        cache_path,
        features=features,
        labels=labels,
        paths=np.asarray(paths),
    )
    return features, labels, paths


def standardize(
    x_train: np.ndarray,
    *others: np.ndarray,
) -> tuple[np.ndarray, ...]:
    """Standardize features using train statistics only."""
    mean = x_train.mean(axis=0, keepdims=True)
    std = x_train.std(axis=0, keepdims=True) + 1e-6
    return (x_train - mean) / std, *((array - mean) / std for array in others)


def train_linear_head(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    *,
    lr: float,
    weight_decay: float,
    epochs: int = 80,
    batch_size: int = 512,
    seed: int = 42,
    device: torch.device | None = None,
) -> tuple[nn.Linear, list[dict[str, float]]]:
    """Train a linear classifier and keep the best validation macro-F1 state."""
    device = device or torch.device("cpu")
    torch.manual_seed(seed)

    model = nn.Linear(x_train.shape[1], NUM_CLASSES).to(device)
    weights = compute_class_weights(y_train.tolist()).to(device)
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(epochs, 1))

    generator = torch.Generator().manual_seed(seed)
    dataset = TensorDataset(
        torch.from_numpy(x_train.astype(np.float32)),
        torch.from_numpy(y_train.astype(np.int64)),
    )
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, generator=generator)

    x_val_tensor = torch.from_numpy(x_val.astype(np.float32)).to(device)
    y_val_tensor = torch.from_numpy(y_val.astype(np.int64)).to(device)

    history: list[dict[str, float]] = []
    best_state: dict[str, torch.Tensor] | None = None
    best_f1 = -1.0

    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        total = 0
        for features, targets in loader:
            features = features.to(device)
            targets = targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(features), targets)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * features.size(0)
            total += features.size(0)

        model.eval()
        with torch.no_grad():
            logits = model(x_val_tensor)
            predictions = logits.argmax(dim=1).cpu().tolist()
        metrics = compute_metrics(y_val_tensor.cpu().tolist(), predictions)
        history.append(
            {
                "epoch": epoch,
                "train_loss": total_loss / total,
                "val_accuracy": metrics["accuracy"],
                "val_macro_f1": metrics["macro_f1"],
            }
        )
        if metrics["macro_f1"] > best_f1:
            best_f1 = metrics["macro_f1"]
            best_state = copy.deepcopy(model.state_dict())
        scheduler.step()

    assert best_state is not None
    model.load_state_dict(best_state)
    return model, history


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    set_seed(int(config["seed"]))
    torch.set_num_threads(int(config.get("threads", 2)))
    device = get_device(args.device)

    data_config = config["data"]
    image_size = int(data_config["image_size"])
    transform = build_transforms(image_size, train=False, pretrained=True)
    batch_size = args.batch_size or int(data_config["batch_size"])
    num_workers = int(data_config["num_workers"])

    train_dataset = GTSRBDataset(
        data_config["root"],
        split="train",
        transform=transform,
        return_path=True,
    )
    test_dataset = GTSRBDataset(
        data_config["root"],
        split="test",
        transform=transform,
        return_path=True,
    )
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        persistent_workers=num_workers > 0,
    )
    test_loader = DataLoader(
        test_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        persistent_workers=num_workers > 0,
    )

    backbone, pool = build_backbone(device)
    cache_dir = Path(args.cache_dir)
    train_features, train_labels, _ = load_features(
        cache_dir / "features_mobilenet_v3_small_train.npz",
        train_loader,
        backbone,
        pool,
        device,
        force=args.force_extract,
    )
    test_features, test_labels, test_paths = load_features(
        cache_dir / "features_mobilenet_v3_small_test.npz",
        test_loader,
        backbone,
        pool,
        device,
        force=args.force_extract,
    )

    train_idx, val_idx = stratified_split(
        train_labels.tolist(),
        val_fraction=float(data_config["val_fraction"]),
        seed=int(config["seed"]),
    )
    x_train_raw = train_features[train_idx]
    y_train = train_labels[train_idx]
    x_val_raw = train_features[val_idx]
    y_val = train_labels[val_idx]
    x_test_raw = test_features

    x_train, x_val, x_test = standardize(x_train_raw, x_val_raw, x_test_raw)

    search_results: list[dict[str, Any]] = []
    best_model: nn.Linear | None = None
    best_config: dict[str, float] | None = None
    best_history: list[dict[str, float]] = []
    best_f1 = -1.0

    for lr, weight_decay in ((1e-3, 1e-4), (1e-2, 1e-4), (1e-3, 1e-2)):
        model, history = train_linear_head(
            x_train,
            y_train,
            x_val,
            y_val,
            lr=lr,
            weight_decay=weight_decay,
            seed=int(config["seed"]),
            device=device,
        )
        best_epoch = max(history, key=lambda row: row["val_macro_f1"])
        search_results.append(
            {
                "lr": lr,
                "weight_decay": weight_decay,
                "val_accuracy": best_epoch["val_accuracy"],
                "val_macro_f1": best_epoch["val_macro_f1"],
            }
        )
        print(
            f"lr={lr:g} wd={weight_decay:g}: val_acc={best_epoch['val_accuracy']:.4f} "
            f"val_f1={best_epoch['val_macro_f1']:.4f}"
        )
        if best_epoch["val_macro_f1"] > best_f1:
            best_f1 = best_epoch["val_macro_f1"]
            best_model = model
            best_config = {"lr": lr, "weight_decay": weight_decay}
            best_history = history

    assert best_model is not None and best_config is not None
    best_model.eval()
    with torch.no_grad():
        logits = best_model(torch.from_numpy(x_test.astype(np.float32)).to(device))
        probabilities = torch.softmax(logits, dim=1).cpu().numpy()
    predictions = probabilities.argmax(axis=1)
    confidences = probabilities.max(axis=1)
    metrics = compute_metrics(test_labels.tolist(), predictions.tolist())

    output_dir = Path(
        args.output
        or Path(config["output"]["results_dir"]) / "mobilenet_v3_small_linear"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(best_history).to_csv(output_dir / "history.csv", index=False)

    payload = {
        "model": "mobilenet_v3_small_frozen_linear_probe",
        "backbone": "mobilenet_v3_small (ImageNet, frozen)",
        "classifier": "multinomial logistic regression (PyTorch nn.Linear)",
        "best_hyperparameters": best_config,
        "config": config,
        "validation_search": search_results,
        "metrics": metrics,
    }
    with (output_dir / "metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    pd.DataFrame(metrics["per_class"]).to_csv(
        output_dir / "classification_report.csv", index=False
    )
    pd.DataFrame(top_confusions(metrics["confusion_matrix"])).to_csv(
        output_dir / "top_confusions.csv", index=False
    )

    misclassified = np.flatnonzero(test_labels != predictions)
    pd.DataFrame(
        {
            "path": [test_paths[index] for index in misclassified],
            "true_id": test_labels[misclassified],
            "true_name": [CLASS_NAMES[index] for index in test_labels[misclassified]],
            "pred_id": predictions[misclassified],
            "pred_name": [CLASS_NAMES[index] for index in predictions[misclassified]],
            "confidence": confidences[misclassified],
        }
    ).to_csv(output_dir / "misclassified.csv", index=False)

    plot_confusion_matrix(metrics["confusion_matrix"], output_dir / "confusion_matrix.png")

    roi_by_path = {str(path): roi for path, _, roi in test_dataset.samples}
    error_images: list[torch.Tensor] = []
    for index in misclassified[:16]:
        path = Path(test_paths[index])
        with Image.open(path) as image:
            image = image.convert("RGB").crop(roi_by_path[str(path)])
            image = image.resize((image_size, image_size))
            error_images.append(
                torch.from_numpy(np.asarray(image, dtype=np.float32) / 255.0).permute(2, 0, 1)
            )
    plot_errors(
        error_images,
        test_labels[misclassified[:16]].tolist(),
        predictions[misclassified[:16]].tolist(),
        confidences[misclassified[:16]].tolist(),
        output_dir / "errors.png",
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
    )

    print(f"Best hyperparameters: {best_config}")
    print(f"Accuracy: {metrics['accuracy']:.4f}")
    print(f"Macro-F1: {metrics['macro_f1']:.4f}")
    print(f"Weighted-F1: {metrics['weighted_f1']:.4f}")
    print(f"Artifacts: {output_dir}")


if __name__ == "__main__":
    main()
