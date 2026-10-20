"""Dataset, transforms and split utilities for GTSRB."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from sklearn.model_selection import train_test_split
from torch.utils.data import Dataset
from torchvision import transforms

from src.labels import NUM_CLASSES

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
SCRATCH_MEAN = (0.5, 0.5, 0.5)
SCRATCH_STD = (0.5, 0.5, 0.5)

Roi = tuple[int, int, int, int]
Sample = tuple[Path, int, Roi]


class GTSRBDataset(Dataset):
    """GTSRB images cropped to their region of interest.

    The expected layout is the one produced by ``torchvision.datasets.GTSRB``::

        <data_dir>/gtsrb/GTSRB/Training/00000/00000_00000.ppm
        <data_dir>/gtsrb/GTSRB/Training/00000/GT-00000.csv
        <data_dir>/gtsrb/GTSRB/Final_Test/Images/00000.ppm
        <data_dir>/gtsrb/GTSRB/Final_Test/GT-final_test.csv
    """

    def __init__(
        self,
        data_dir: str | Path,
        split: str = "train",
        transform: Any | None = None,
        return_path: bool = False,
    ) -> None:
        self.root = Path(data_dir) / "gtsrb" / "GTSRB"
        self.split = split
        self.transform = transform
        self.return_path = return_path
        self.samples: list[Sample] = self._load_samples()
        self.labels: list[int] = [label for _, label, _ in self.samples]

    def _load_samples(self) -> list[Sample]:
        if self.split == "train":
            return self._load_train_samples()
        if self.split == "test":
            return self._load_test_samples()
        raise ValueError(f"Unknown split: {self.split!r}")

    def _load_train_samples(self) -> list[Sample]:
        training_dir = self.root / "Training"
        if not training_dir.is_dir():
            raise FileNotFoundError(
                f"Training split not found at {training_dir}. "
                "Run `python scripts/download_data.py` first."
            )

        samples: list[Sample] = []
        for class_dir in sorted(path for path in training_dir.iterdir() if path.is_dir()):
            csv_path = class_dir / f"GT-{class_dir.name}.csv"
            if not csv_path.is_file():
                continue
            with csv_path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle, delimiter=";"):
                    samples.append(
                        (
                            class_dir / row["Filename"],
                            int(row["ClassId"]),
                            (
                                int(row["Roi.X1"]),
                                int(row["Roi.Y1"]),
                                int(row["Roi.X2"]),
                                int(row["Roi.Y2"]),
                            ),
                        )
                    )
        if not samples:
            raise FileNotFoundError(f"No training images found under {training_dir}.")
        return samples

    def _load_test_samples(self) -> list[Sample]:
        test_dir = self.root / "Final_Test"
        csv_path = test_dir / "GT-final_test.csv"
        if not csv_path.is_file():
            raise FileNotFoundError(
                f"Test annotations not found at {csv_path}. "
                "Run `python scripts/download_data.py` first."
            )

        samples: list[Sample] = []
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter=";"):
                samples.append(
                    (
                        test_dir / "Images" / row["Filename"],
                        int(row["ClassId"]),
                        (
                            int(row["Roi.X1"]),
                            int(row["Roi.Y1"]),
                            int(row["Roi.X2"]),
                            int(row["Roi.Y2"]),
                        ),
                    )
                )
        if not samples:
            raise FileNotFoundError(f"No test images found under {test_dir / 'Images'}.")
        return samples

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> Any:
        path, label, roi = self.samples[index]
        with Image.open(path) as image:
            image = image.convert("RGB").crop(roi)
            if self.transform is not None:
                image = self.transform(image)
        if self.return_path:
            return image, label, str(path)
        return image, label


def normalization(
    pretrained: bool,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return the channel mean and standard deviation used for a model."""
    if pretrained:
        return IMAGENET_MEAN, IMAGENET_STD
    return SCRATCH_MEAN, SCRATCH_STD


def build_transforms(
    image_size: int,
    train: bool,
    pretrained: bool = False,
) -> transforms.Compose:
    """Return the augmentation/evaluation pipeline for a model."""
    mean, std = normalization(pretrained)
    if train:
        return transforms.Compose(
            [
                transforms.RandomAffine(
                    degrees=10,
                    translate=(0.1, 0.1),
                    scale=(0.9, 1.1),
                ),
                transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
                transforms.Resize((image_size, image_size)),
                transforms.ToTensor(),
                transforms.Normalize(mean, std),
            ]
        )
    return transforms.Compose(
        [
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean, std),
        ]
    )


def stratified_split(
    labels: list[int],
    val_fraction: float = 0.15,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Split indices into train/validation keeping the class proportions."""
    if not 0 < val_fraction < 1:
        raise ValueError("val_fraction must be in (0, 1).")
    indices = np.arange(len(labels))
    train_idx, val_idx = train_test_split(
        indices,
        test_size=val_fraction,
        random_state=seed,
        stratify=labels,
    )
    return np.sort(train_idx), np.sort(val_idx)


def class_counts(labels: list[int], num_classes: int = NUM_CLASSES) -> np.ndarray:
    """Count samples per class, including classes with zero samples."""
    return np.bincount(np.asarray(labels, dtype=np.int64), minlength=num_classes)


def compute_class_weights(
    labels: list[int],
    num_classes: int = NUM_CLASSES,
) -> torch.Tensor:
    """Inverse-frequency weights for CrossEntropyLoss."""
    counts = class_counts(labels, num_classes=num_classes)
    weights = len(labels) / (num_classes * np.maximum(counts, 1))
    weights[counts == 0] = 0.0
    return torch.tensor(weights, dtype=torch.float32)


def dataset_summary(labels: list[int]) -> dict[str, Any]:
    """Return counts and basic statistics for a label list."""
    counts = class_counts(labels)
    present = counts[counts > 0]
    return {
        "num_samples": len(labels),
        "num_classes": int((counts > 0).sum()),
        "min_class_count": int(present.min()),
        "max_class_count": int(present.max()),
        "median_class_count": float(np.median(present)),
        "class_counts": counts.tolist(),
    }
