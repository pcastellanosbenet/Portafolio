"""Tests for mask lookup, color mapping and attention visualization."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from src.mask import (
    attention_to_token,
    count_mask_tokens,
    generate_diagram,
    get_color_for_attention_score,
    get_mask_token_index,
    visualize_attentions,
)


def test_get_mask_token_index_1d() -> None:
    input_ids = torch.tensor([101, 1996, 103, 2001, 102])
    assert get_mask_token_index(103, input_ids) == 2


def test_get_mask_token_index_2d_and_missing() -> None:
    input_ids = torch.tensor([[101, 103, 102], [101, 2001, 102]])
    assert get_mask_token_index(103, input_ids) == 1
    assert get_mask_token_index(999, input_ids) is None


def test_get_mask_token_index_batch_encoding_like() -> None:
    class Inputs:
        input_ids = torch.tensor([101, 2023, 103, 102])

    assert get_mask_token_index(103, Inputs()) == 2
    assert count_mask_tokens(103, Inputs()) == 1


def test_get_color_for_attention_score() -> None:
    assert get_color_for_attention_score(0.0) == (0, 0, 0)
    assert get_color_for_attention_score(1.0) == (255, 255, 255)
    assert get_color_for_attention_score(0.5) == (128, 128, 128)
    assert get_color_for_attention_score(-1.0) == (0, 0, 0)
    assert get_color_for_attention_score(2.0) == (255, 255, 255)


def test_generate_diagram_creates_png(tmp_path: Path) -> None:
    tokens = ["[CLS]", "the", "[MASK]", "[SEP]"]
    weights = np.array(
        [
            [0.1, 0.2, 0.3, 0.4],
            [0.4, 0.3, 0.2, 0.1],
            [0.25, 0.25, 0.25, 0.25],
            [0.7, 0.1, 0.1, 0.1],
        ]
    )
    output = generate_diagram(2, 3, tokens, weights, tmp_path / "map.png")
    assert output.is_file()
    assert output.stat().st_size > 0


def test_generate_diagram_rejects_bad_shape(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        generate_diagram(1, 1, ["a", "b"], np.ones((3, 3)), tmp_path / "bad.png")


def test_visualize_attentions_creates_one_file_per_head(tmp_path: Path) -> None:
    tokens = ["[CLS]", "a", "[MASK]", "[SEP]"]
    layer = torch.full((1, 2, 4, 4), 0.25)
    paths = visualize_attentions(tokens, [layer, layer], tmp_path, prefix="demo")
    assert len(paths) == 4
    assert sorted(path.name for path in paths) == [
        "demo_layer01_head01.png",
        "demo_layer01_head02.png",
        "demo_layer02_head01.png",
        "demo_layer02_head02.png",
    ]
    assert all(path.is_file() for path in paths)


def test_visualize_attentions_selected_layers_and_heads(tmp_path: Path) -> None:
    tokens = ["[CLS]", "a", "[MASK]", "[SEP]"]
    layer = torch.full((1, 2, 4, 4), 0.25)
    paths = visualize_attentions(
        tokens,
        [layer, layer, layer],
        tmp_path,
        prefix="sel",
        layers=[2],
        heads=[1],
    )
    assert [path.name for path in paths] == ["sel_layer02_head01.png"]


def test_attention_to_token_shape() -> None:
    layer = torch.zeros((1, 2, 3, 3))
    layer[0, :, 1, 2] = 0.5
    values = attention_to_token([layer, layer], query_index=1, key_index=2)
    assert values.shape == (2, 2)
    assert np.allclose(values, 0.5)
