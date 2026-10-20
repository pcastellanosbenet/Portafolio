"""Tests for model construction and output shapes."""

from __future__ import annotations

import pytest
import torch

from src.model import SmallCNN, build_model, count_parameters


def test_small_cnn_output_shape() -> None:
    model = SmallCNN(num_classes=43)
    output = model(torch.zeros(2, 3, 32, 32))
    assert tuple(output.shape) == (2, 43)
    assert count_parameters(model) > 0


def test_build_small_cnn() -> None:
    config = {"model": {"name": "small_cnn", "dropout": 0.1}}
    model = build_model(config)
    assert isinstance(model, SmallCNN)


def test_build_mobilenet_without_pretrained_weights() -> None:
    config = {
        "model": {
            "name": "mobilenet_v3_small",
            "pretrained": False,
            "freeze_backbone": True,
        }
    }
    model = build_model(config)
    output = model(torch.zeros(2, 3, 96, 96))
    assert tuple(output.shape) == (2, 43)
    assert count_parameters(model, trainable_only=True) < count_parameters(model)


def test_unknown_model_raises() -> None:
    with pytest.raises(ValueError):
        build_model({"model": {"name": "does_not_exist"}})
