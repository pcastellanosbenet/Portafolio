"""Tests for configuration merging and reproducibility helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from src.config import get_device, load_config, set_seed


def test_load_config_merges_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("data:\n  image_size: 48\n", encoding="utf-8")
    config = load_config(config_path)
    assert config["data"]["image_size"] == 48
    assert config["data"]["batch_size"] == 128
    assert config["seed"] == 42


def test_load_config_rejects_non_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- not\n- a mapping\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(config_path)


def test_get_device_cpu() -> None:
    assert get_device("cpu").type == "cpu"


def test_set_seed_is_reproducible() -> None:
    set_seed(123)
    first = (np.random.rand(), torch.rand(1).item())
    set_seed(123)
    second = (np.random.rand(), torch.rand(1).item())
    assert first == second
