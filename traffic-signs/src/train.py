"""Train and validate a traffic-sign classifier."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, Subset
from tqdm import tqdm

from src.config import get_device, load_config, set_seed
from src.data import (
    GTSRBDataset,
    build_transforms,
    compute_class_weights,
    dataset_summary,
    stratified_split,
)
from src.labels import CLASS_NAMES
from src.metrics import compute_metrics
from src.model import build_model, count_parameters
from src.viz import plot_training_curves


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to a YAML config.")
    parser.add_argument("--epochs", type=int, default=None, help="Override the epoch count.")
    parser.add_argument("--device", default=None, help="cpu, cuda or mps.")
    parser.add_argument(
        "--limit-train",
        type=int,
        default=None,
        help="Use at most N training images per class (useful for smoke tests).",
    )
    parser.add_argument("--run-name", default=None, help="Override the run name.")
    return parser.parse_args()


def limit_per_class(
    indices: np.ndarray,
    labels: list[int],
    limit: int,
    seed: int,
) -> np.ndarray:
    """Keep at most ``limit`` training indices per class."""
    rng = np.random.default_rng(seed)
    labels_array = np.asarray(labels)
    selected: list[int] = []
    for class_id in np.unique(labels_array[indices]):
        class_indices = indices[labels_array[indices] == class_id]
        take = min(limit, len(class_indices))
        selected.extend(rng.choice(class_indices, size=take, replace=False).tolist())
    return np.sort(np.asarray(selected))


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> tuple[float, float]:
    model.train()
    total_loss = 0.0
    correct = 0
    total = 0

    for images, labels in tqdm(loader, desc="train", leave=False):
        images = images.to(device)
        labels = labels.to(device)

        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()

        total_loss += loss.item() * images.size(0)
        correct += (logits.argmax(dim=1) == labels).sum().item()
        total += images.size(0)

    return total_loss / total, correct / total


@torch.no_grad()
def validate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> tuple[float, dict[str, Any]]:
    model.eval()
    total_loss = 0.0
    total = 0
    targets: list[int] = []
    predictions: list[int] = []

    for images, labels in tqdm(loader, desc="validation", leave=False):
        images = images.to(device)
        labels = labels.to(device)
        logits = model(images)
        loss = criterion(logits, labels)

        total_loss += loss.item() * images.size(0)
        total += images.size(0)
        targets.extend(labels.cpu().tolist())
        predictions.extend(logits.argmax(dim=1).cpu().tolist())

    metrics = compute_metrics(targets, predictions)
    return total_loss / total, metrics


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.epochs is not None:
        config["training"]["epochs"] = args.epochs
    if args.run_name is not None:
        config["output"]["run_name"] = args.run_name
    if args.limit_train is not None:
        config["output"]["run_name"] = f"{config['output']['run_name']}-smoke"

    set_seed(int(config["seed"]))
    torch.set_num_threads(int(config.get("threads", 4)))
    device = get_device(args.device)

    data_config = config["data"]
    model_config = config["model"]
    training_config = config["training"]
    output_config = config["output"]
    image_size = int(data_config["image_size"])
    pretrained = bool(model_config.get("pretrained", False))

    train_full = GTSRBDataset(
        data_config["root"],
        split="train",
        transform=build_transforms(image_size, train=True, pretrained=pretrained),
    )
    val_full = GTSRBDataset(
        data_config["root"],
        split="train",
        transform=build_transforms(image_size, train=False, pretrained=pretrained),
    )
    train_idx, val_idx = stratified_split(
        train_full.labels,
        val_fraction=float(data_config["val_fraction"]),
        seed=int(config["seed"]),
    )
    if args.limit_train is not None:
        train_idx = limit_per_class(
            train_idx,
            train_full.labels,
            limit=args.limit_train,
            seed=int(config["seed"]),
        )

    train_dataset = Subset(train_full, train_idx.tolist())
    val_dataset = Subset(val_full, val_idx.tolist())
    train_labels = [train_full.labels[index] for index in train_idx]

    generator = torch.Generator().manual_seed(int(config["seed"]))
    train_loader = DataLoader(
        train_dataset,
        batch_size=int(data_config["batch_size"]),
        shuffle=True,
        num_workers=int(data_config["num_workers"]),
        pin_memory=device.type == "cuda",
        generator=generator,
        persistent_workers=int(data_config["num_workers"]) > 0,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=int(data_config["batch_size"]),
        shuffle=False,
        num_workers=int(data_config["num_workers"]),
        pin_memory=device.type == "cuda",
        persistent_workers=int(data_config["num_workers"]) > 0,
    )

    model = build_model(config).to(device)
    if training_config.get("class_weights", True):
        weights = compute_class_weights(train_labels).to(device)
    else:
        weights = None
    criterion = nn.CrossEntropyLoss(weight=weights)
    trainable_parameters = [
        parameter for parameter in model.parameters() if parameter.requires_grad
    ]
    optimizer = torch.optim.AdamW(
        trainable_parameters,
        lr=float(training_config["lr"]),
        weight_decay=float(training_config["weight_decay"]),
    )
    epochs = int(training_config["epochs"])
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(epochs, 1))

    results_dir = Path(output_config["results_dir"]) / output_config["run_name"]
    checkpoint_dir = Path(output_config["checkpoint_dir"])
    results_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / f"{output_config['run_name']}.pt"

    print(f"Device: {device}")
    print(f"Model: {model_config['name']} ({count_parameters(model):,} parameters, "
          f"{count_parameters(model, trainable_only=True):,} trainable)")
    print(f"Train: {len(train_dataset):,} images | Validation: {len(val_dataset):,} images")
    print(f"Class distribution: {dataset_summary(train_labels)}")

    history: list[dict[str, float]] = []
    best_f1 = -1.0
    best_epoch = 0
    epochs_without_improvement = 0

    for epoch in range(1, epochs + 1):
        train_loss, train_accuracy = train_one_epoch(
            model, train_loader, criterion, optimizer, device
        )
        val_loss, val_metrics = validate(model, val_loader, criterion, device)
        val_accuracy = float(val_metrics["accuracy"])
        val_f1 = float(val_metrics["macro_f1"])
        learning_rate = float(optimizer.param_groups[0]["lr"])

        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "train_accuracy": train_accuracy,
                "val_loss": val_loss,
                "val_accuracy": val_accuracy,
                "val_macro_f1": val_f1,
                "lr": learning_rate,
            }
        )
        pd.DataFrame(history).to_csv(results_dir / "history.csv", index=False)

        print(
            f"epoch {epoch:02d}/{epochs} | train_loss={train_loss:.4f} "
            f"train_acc={train_accuracy:.4f} | val_loss={val_loss:.4f} "
            f"val_acc={val_accuracy:.4f} val_f1={val_f1:.4f}"
        )

        if val_f1 > best_f1 + 1e-4:
            best_f1 = val_f1
            best_epoch = epoch
            epochs_without_improvement = 0
            torch.save(
                {
                    "model_state": model.state_dict(),
                    "config": config,
                    "class_names": CLASS_NAMES,
                    "epoch": epoch,
                    "val_metrics": {
                        "accuracy": val_accuracy,
                        "macro_f1": val_f1,
                    },
                },
                checkpoint_path,
            )
        else:
            epochs_without_improvement += 1

        scheduler.step()
        if (
            int(training_config["patience"]) > 0
            and epochs_without_improvement >= int(training_config["patience"])
        ):
            print(f"Early stopping at epoch {epoch}.")
            break

    plot_training_curves(results_dir / "history.csv", results_dir / "training_curves.png")
    print(f"Best validation macro-F1: {best_f1:.4f} (epoch {best_epoch})")
    print(f"Checkpoint: {checkpoint_path}")
    print(f"Artifacts: {results_dir}")


if __name__ == "__main__":
    main()
