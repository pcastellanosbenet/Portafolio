"""Tests for the GTSRB dataset, splits and class weights."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from torchvision import transforms

from src.data import (
    GTSRBDataset,
    class_counts,
    compute_class_weights,
    dataset_summary,
    stratified_split,
)


def write_ppm(path: Path, size: tuple[int, int] = (40, 40)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(200, 30, 30)).save(path)


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture()
def fake_dataset(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    root = data_dir / "gtsrb" / "GTSRB"
    class_dir = root / "Training" / "00000"
    write_ppm(class_dir / "image.ppm")
    write_csv(
        class_dir / "GT-00000.csv",
        ["Filename", "Width", "Height", "Roi.X1", "Roi.Y1", "Roi.X2", "Roi.Y2", "ClassId"],
        [["image.ppm", "40", "40", "10", "10", "30", "30", "0"]],
    )

    test_dir = root / "Final_Test" / "Images"
    write_ppm(test_dir / "test.ppm")
    write_csv(
        root / "Final_Test" / "GT-final_test.csv",
        ["Filename", "Width", "Height", "Roi.X1", "Roi.Y1", "Roi.X2", "Roi.Y2", "ClassId"],
        [["test.ppm", "40", "40", "5", "5", "25", "25", "0"]],
    )
    return data_dir


def test_train_dataset_crops_roi_and_reads_label(fake_dataset: Path) -> None:
    dataset = GTSRBDataset(fake_dataset, split="train", transform=transforms.ToTensor())
    assert len(dataset) == 1
    image, label = dataset[0]
    assert label == 0
    assert tuple(image.shape) == (3, 20, 20)


def test_test_dataset_reads_annotations(fake_dataset: Path) -> None:
    dataset = GTSRBDataset(fake_dataset, split="test", transform=transforms.ToTensor())
    assert len(dataset) == 1
    _, label = dataset[0]
    assert label == 0


def test_return_path(fake_dataset: Path) -> None:
    dataset = GTSRBDataset(
        fake_dataset,
        split="train",
        transform=transforms.ToTensor(),
        return_path=True,
    )
    _, _, path = dataset[0]
    assert path.endswith("image.ppm")


def test_missing_test_annotations_raises(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "gtsrb" / "GTSRB" / "Final_Test" / "Images").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        GTSRBDataset(data_dir, split="test")


def test_stratified_split_is_deterministic_and_disjoint() -> None:
    labels = [0] * 10 + [1] * 10 + [2] * 10
    train_a, val_a = stratified_split(labels, val_fraction=0.2, seed=42)
    train_b, val_b = stratified_split(labels, val_fraction=0.2, seed=42)

    assert np.array_equal(train_a, train_b)
    assert np.array_equal(val_a, val_b)
    assert len(train_a) == 24
    assert len(val_a) == 6
    assert set(train_a).isdisjoint(set(val_a))
    assert sorted(np.asarray(labels)[val_a].tolist()) == [0, 0, 1, 1, 2, 2]


def test_invalid_val_fraction_raises() -> None:
    with pytest.raises(ValueError):
        stratified_split([0, 1], val_fraction=0)


def test_class_counts_and_weights() -> None:
    labels = [0, 0, 0, 1]
    assert class_counts(labels, num_classes=3).tolist() == [3, 1, 0]
    weights = compute_class_weights(labels, num_classes=3)
    assert weights[0].item() == pytest.approx(4 / 9)
    assert weights[1].item() == pytest.approx(4 / 3)
    assert weights[2].item() == 0.0


def test_dataset_summary() -> None:
    summary = dataset_summary([0, 0, 1, 2])
    assert summary["num_samples"] == 4
    assert summary["num_classes"] == 3
    assert summary["min_class_count"] == 1
    assert summary["max_class_count"] == 2
