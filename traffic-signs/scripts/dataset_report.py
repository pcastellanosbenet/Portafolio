"""Generate a small dataset report: counts, distribution and sample images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data import (
    GTSRBDataset,
    build_transforms,
    class_counts,
    dataset_summary,
    normalization,
)
from src.viz import plot_class_distribution, plot_samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="results")
    parser.add_argument("--image-size", type=int, default=32)
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = GTSRBDataset(
        args.data_dir,
        split="train",
        transform=build_transforms(args.image_size, train=False, pretrained=False),
    )
    summary = dataset_summary(dataset.labels)
    with (output_dir / "dataset_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)

    mean, std = normalization(pretrained=False)
    plot_class_distribution(class_counts(dataset.labels), output_dir / "class_distribution.png")
    plot_samples(dataset, output_dir / "samples.png", mean, std)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
