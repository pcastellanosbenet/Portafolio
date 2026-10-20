"""Configuration loading, reproducibility helpers and device selection."""

from __future__ import annotations

import copy
import random
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml

DEFAULTS: dict[str, Any] = {
    "seed": 42,
    "data": {
        "root": "data",
        "image_size": 32,
        "val_fraction": 0.15,
        "num_workers": 2,
        "batch_size": 128,
    },
    "model": {
        "name": "small_cnn",
        "dropout": 0.3,
        "pretrained": False,
        "freeze_backbone": False,
    },
    "training": {
        "epochs": 20,
        "lr": 0.001,
        "weight_decay": 0.0001,
        "patience": 6,
        "class_weights": True,
    },
    "output": {
        "run_name": "baseline",
        "results_dir": "results",
        "checkpoint_dir": "checkpoints",
    },
    "threads": 4,
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``base`` updated recursively with ``override``."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML config and merge it with the project defaults."""
    with Path(path).open(encoding="utf-8") as handle:
        user_config = yaml.safe_load(handle) or {}
    if not isinstance(user_config, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return _deep_merge(DEFAULTS, user_config)


def set_seed(seed: int) -> None:
    """Seed Python, NumPy and PyTorch for reproducible runs."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def get_device(preferred: str | None = None) -> torch.device:
    """Return the requested device, or the best available one."""
    if preferred:
        return torch.device(preferred)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
