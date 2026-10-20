"""Compare all evaluated runs and export a table and a bar chart."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    rows = []
    for metrics_path in sorted(results_dir.rglob("metrics.json")):
        with metrics_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        metrics = payload.get("metrics")
        if not metrics:
            continue
        rows.append(
            {
                "run": payload.get("run_name") or payload.get("model", metrics_path.parent.name),
                "split": payload.get("split", "test"),
                "accuracy": metrics["accuracy"],
                "macro_f1": metrics["macro_f1"],
                "weighted_f1": metrics["weighted_f1"],
                "samples": metrics["num_samples"],
            }
        )

    if not rows:
        raise SystemExit("No metrics.json files found.")

    table = pd.DataFrame(rows).sort_values("macro_f1", ascending=False)
    output_dir = results_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_dir / "comparison.csv", index=False)
    print(table.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    figure, axis = plt.subplots(figsize=(10, 4.5))
    positions = range(len(table))
    width = 0.38
    axis.bar([p - width / 2 for p in positions], table["accuracy"], width, label="Accuracy")
    axis.bar([p + width / 2 for p in positions], table["macro_f1"], width, label="Macro-F1")
    axis.set_xticks(list(positions))
    axis.set_xticklabels(table["run"], rotation=15, ha="right")
    axis.set_ylim(0, 1.05)
    axis.set_ylabel("Score")
    axis.set_title("Model comparison on the GTSRB test split")
    axis.legend()
    for position, value in zip(positions, table["accuracy"], strict=False):
        axis.text(position - width / 2, value + 0.01, f"{value:.3f}", ha="center", fontsize=8)
    for position, value in zip(positions, table["macro_f1"], strict=False):
        axis.text(position + width / 2, value + 0.01, f"{value:.3f}", ha="center", fontsize=8)
    figure.tight_layout()
    figure.savefig(results_dir / "comparison.png", dpi=150, bbox_inches="tight")
    plt.close(figure)


if __name__ == "__main__":
    main()
