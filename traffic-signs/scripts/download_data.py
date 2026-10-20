"""Download and validate the GTSRB dataset.

The archive is stored under ``data/`` (ignored by Git). Re-running the script is
safe: torchvision skips files that are already present.
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from torchvision.datasets import GTSRB

EXPECTED_TRAIN = 26_640
EXPECTED_TEST = 12_630
EXPECTED_CLASSES = 43


def extract_test_annotations(data_dir: Path) -> Path:
    """Extract GT-final_test.csv if torchvision has not done it yet."""
    gtsrb_dir = data_dir / "gtsrb"
    annotations = gtsrb_dir / "GTSRB" / "Final_Test" / "GT-final_test.csv"
    if annotations.is_file():
        return annotations

    archive = gtsrb_dir / "GTSRB_Final_Test_GT.zip"
    if not archive.is_file():
        raise FileNotFoundError(f"Missing test annotations archive: {archive}")

    with zipfile.ZipFile(archive) as zip_file:
        zip_file.extractall(annotations.parent)
    if not annotations.is_file():
        raise FileNotFoundError(f"GT-final_test.csv not found inside {archive}")
    return annotations


def count_images(path: Path) -> int:
    return sum(1 for _ in path.rglob("*.ppm"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", help="Directory for the dataset.")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)

    for split in ("train", "test"):
        dataset = GTSRB(root=str(data_dir), split=split, download=True)
        print(f"{split}: {len(dataset):,} images")

    annotations = extract_test_annotations(data_dir)
    root = data_dir / "gtsrb" / "GTSRB"
    train_images = count_images(root / "Training")
    test_images = count_images(root / "Final_Test" / "Images")
    classes = [
        path.name for path in (root / "Training").iterdir() if path.is_dir()
    ]

    print(f"Training images: {train_images:,}")
    print(f"Test images: {test_images:,}")
    print(f"Classes: {len(classes)}")
    print(f"Test annotations: {annotations}")

    if train_images != EXPECTED_TRAIN:
        raise RuntimeError(f"Expected {EXPECTED_TRAIN:,} training images, found {train_images:,}")
    if test_images != EXPECTED_TEST:
        raise RuntimeError(f"Expected {EXPECTED_TEST:,} test images, found {test_images:,}")
    if len(classes) != EXPECTED_CLASSES:
        raise RuntimeError(f"Expected {EXPECTED_CLASSES} classes, found {len(classes)}")

    print("Dataset ready.")


if __name__ == "__main__":
    main()
