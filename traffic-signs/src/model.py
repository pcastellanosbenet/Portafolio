"""Model definitions and builders."""

from __future__ import annotations

from typing import Any

import torch
from torch import nn
from torchvision import models

from src.labels import NUM_CLASSES


class SmallCNN(nn.Module):
    """Compact convolutional network designed for 32x32 traffic signs."""

    def __init__(self, num_classes: int = NUM_CLASSES, dropout: float = 0.3) -> None:
        super().__init__()
        self.features = nn.Sequential(
            self._block(3, 32),
            self._block(32, 64),
            self._block(64, 128),
        )
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(dropout),
            nn.Linear(128, num_classes),
        )

    @staticmethod
    def _block(in_channels: int, out_channels: int) -> nn.Sequential:
        return nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        x = self.pool(x)
        return self.classifier(x)


def build_model(config: dict[str, Any], num_classes: int = NUM_CLASSES) -> nn.Module:
    """Build a model from the ``model`` section of a config."""
    model_config = config["model"]
    name = model_config["name"]

    if name == "small_cnn":
        return SmallCNN(
            num_classes=num_classes,
            dropout=float(model_config.get("dropout", 0.3)),
        )

    pretrained = bool(model_config.get("pretrained", False))
    weights = "DEFAULT" if pretrained else None
    freeze = bool(model_config.get("freeze_backbone", False))

    if name == "mobilenet_v3_small":
        model = models.mobilenet_v3_small(weights=weights)
        if freeze:
            for parameter in model.features.parameters():
                parameter.requires_grad = False
        in_features = model.classifier[3].in_features
        model.classifier[3] = nn.Linear(in_features, num_classes)
        return model

    if name == "resnet18":
        model = models.resnet18(weights=weights)
        if freeze:
            for parameter_name, parameter in model.named_parameters():
                if not parameter_name.startswith("fc."):
                    parameter.requires_grad = False
        model.fc = nn.Linear(model.fc.in_features, num_classes)
        return model

    raise ValueError(f"Unknown model: {name!r}")


def count_parameters(model: nn.Module, trainable_only: bool = False) -> int:
    """Count model parameters."""
    parameters = model.parameters()
    if trainable_only:
        parameters = (parameter for parameter in parameters if parameter.requires_grad)
    return sum(parameter.numel() for parameter in parameters)
