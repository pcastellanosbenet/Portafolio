"""BERT masked-language modelling and attention visualization.

The script loads a pretrained BERT model, predicts the token that fills a
``[MASK]`` and renders one heatmap per attention layer and head.  Attention
rows are normalized for visualization, because raw BERT attention is spread
over many tokens and would otherwise produce almost-black images.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import torch
from transformers import AutoTokenizer, BertForMaskedLM

MODEL_NAME = "bert-base-uncased"
DEFAULT_TOP_K = 3


def get_mask_token_index(mask_token_id: int, inputs: Any) -> int | None:
    """Return the position of the first ``[MASK]`` token, or ``None``.

    ``inputs`` can be a 1-D/2-D tensor of token ids or a Hugging Face
    ``BatchEncoding`` (anything with an ``input_ids`` attribute).
    """
    input_ids = getattr(inputs, "input_ids", inputs)
    input_ids = torch.as_tensor(input_ids)
    positions = torch.nonzero(input_ids == mask_token_id, as_tuple=False)
    if positions.numel() == 0:
        return None
    # For a batch, use the first sequence and its last coordinate.
    return int(positions[0][-1].item())


def count_mask_tokens(mask_token_id: int, inputs: Any) -> int:
    """Count how many ``[MASK]`` tokens are present in the input."""
    input_ids = getattr(inputs, "input_ids", inputs)
    input_ids = torch.as_tensor(input_ids)
    return int((input_ids == mask_token_id).sum().item())


def get_color_for_attention_score(attention_score: float) -> tuple[int, int, int]:
    """Map an attention score in ``[0, 1]`` to a grayscale RGB triple.

    The value is clamped so that malformed scores cannot produce invalid RGB
    values.  This helper is kept for compatibility with grayscale diagrams and
    is covered by the test suite; the main visualizations use a color map.
    """
    score = float(attention_score)
    if np.isnan(score):
        score = 0.0
    score = min(max(score, 0.0), 1.0)
    value = int(round(255 * score))
    return value, value, value


def load_pipeline(
    model_name: str = MODEL_NAME,
    device: str = "cpu",
) -> tuple[Any, BertForMaskedLM, torch.device]:
    """Load the tokenizer and masked-language model once."""
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    # Transformers >= 5 uses SDPA by default, which does not expose attention
    # matrices. Force eager attention because the matrices are the project's
    # main output.
    model = BertForMaskedLM.from_pretrained(model_name, attn_implementation="eager")
    target = torch.device(device)
    model.to(target).eval()
    return tokenizer, model, target


@torch.no_grad()
def predict_masked_token(
    text: str,
    tokenizer: Any,
    model: BertForMaskedLM,
    *,
    top_k: int = DEFAULT_TOP_K,
    device: torch.device | str = "cpu",
    output_attentions: bool = False,
) -> dict[str, Any]:
    """Predict the top-k replacements for the unique ``[MASK]`` in ``text``."""
    mask_id = tokenizer.mask_token_id
    if mask_id is None:
        raise ValueError(f"{tokenizer.name_or_path!r} has no mask token.")
    if text.count(tokenizer.mask_token) != 1:
        raise ValueError(f"Input must contain exactly one {tokenizer.mask_token} token.")

    inputs = tokenizer(text, return_tensors="pt").to(device)
    outputs = model(**inputs, output_attentions=output_attentions)
    mask_index = get_mask_token_index(mask_id, inputs)
    if mask_index is None:
        raise ValueError(f"Input must contain the mask token {tokenizer.mask_token!r}.")

    logits = outputs.logits[0, mask_index]
    probabilities = torch.softmax(logits, dim=-1)
    top = torch.topk(probabilities, k=top_k)
    token_ids = inputs["input_ids"][0].tolist()
    tokens = tokenizer.convert_ids_to_tokens(token_ids)

    predictions = []
    for token_id, probability in zip(top.indices.tolist(), top.values.tolist(), strict=True):
        token = tokenizer.convert_ids_to_tokens(token_id)
        predictions.append(
            {
                "token_id": int(token_id),
                "token": token,
                "word": tokenizer.decode([token_id]),
                "probability": float(probability),
                "sentence": text.replace(tokenizer.mask_token, tokenizer.decode([token_id])),
            }
        )

    return {
        "text": text,
        "tokens": tokens,
        "mask_index": mask_index,
        "predictions": predictions,
        "attentions": outputs.attentions if output_attentions else None,
        "attention_mask": inputs["attention_mask"][0].tolist(),
    }


def _as_attention_array(attention_weights: Any) -> np.ndarray:
    if torch.is_tensor(attention_weights):
        attention_weights = attention_weights.detach().cpu().numpy()
    array = np.asarray(attention_weights, dtype=np.float64)
    if array.ndim != 2 or array.shape[0] != array.shape[1]:
        raise ValueError(f"Expected a square attention matrix, got shape {array.shape}.")
    return array


def generate_diagram(
    layer_number: int,
    head_number: int,
    tokens: Sequence[str],
    attention_weights: Any,
    output_path: str | Path,
    *,
    normalize_rows: bool = True,
) -> Path:
    """Render one layer/head attention matrix as a heatmap.

    Rows are queries (the token that attends) and columns are keys (the token
    that receives attention).  With ``normalize_rows=True`` each row is divided
    by its maximum so the strongest connection is visible; raw weights are kept
    in ``results/analysis.json``.
    """
    weights = _as_attention_array(attention_weights)
    if len(tokens) != weights.shape[0]:
        raise ValueError(
            f"Number of tokens ({len(tokens)}) does not match attention shape "
            f"{weights.shape}."
        )
    if normalize_rows:
        row_max = weights.max(axis=1, keepdims=True)
        weights = weights / np.maximum(row_max, 1e-12)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    n_tokens = len(tokens)
    size = max(6.0, 0.48 * n_tokens + 2.5)
    fig, ax = plt.subplots(figsize=(size, max(5.0, 0.42 * n_tokens + 2.0)))
    image = ax.imshow(weights, cmap="viridis", vmin=0.0, vmax=1.0, aspect="auto")

    ax.set_xticks(range(n_tokens))
    ax.set_yticks(range(n_tokens))
    ax.set_xticklabels(tokens, rotation=90, fontsize=max(6, min(10, 140 // max(n_tokens, 1))))
    ax.set_yticklabels(tokens, fontsize=max(6, min(10, 140 // max(n_tokens, 1))))
    ax.set_xlabel("Key token (recibe atención)")
    ax.set_ylabel("Query token (atiende)")
    ax.set_title(f"Capa {layer_number} · Cabeza {head_number}")
    ax.set_xticks(np.arange(-0.5, n_tokens, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n_tokens, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.3, alpha=0.25)
    ax.tick_params(which="minor", length=0)

    colorbar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    colorbar.set_label("Atención normalizada por fila" if normalize_rows else "Peso de atención")

    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def _normalize_layer_indices(layers: Iterable[int] | None, num_layers: int) -> list[int]:
    if layers is None:
        return list(range(1, num_layers + 1))
    selected = [int(layer) for layer in layers]
    if any(layer < 1 or layer > num_layers for layer in selected):
        raise ValueError(f"Layers must be in [1, {num_layers}].")
    return selected


def _normalize_head_indices(heads: Iterable[int] | None, num_heads: int) -> list[int]:
    if heads is None:
        return list(range(1, num_heads + 1))
    selected = [int(head) for head in heads]
    if any(head < 1 or head > num_heads for head in selected):
        raise ValueError(f"Heads must be in [1, {num_heads}].")
    return selected


def visualize_attentions(
    tokens: Sequence[str],
    attentions: Sequence[Any],
    output_dir: str | Path,
    *,
    prefix: str = "attention",
    layers: Iterable[int] | None = None,
    heads: Iterable[int] | None = None,
    normalize_rows: bool = True,
) -> list[Path]:
    """Save one heatmap per selected layer and head.

    ``attentions`` is the tuple returned by Hugging Face with shape
    ``(batch, num_heads, seq_len, seq_len)`` per layer.
    """
    if not attentions:
        raise ValueError("No attention tensors were provided.")
    first = torch.as_tensor(attentions[0])
    num_layers = len(attentions)
    num_heads = int(first.shape[1])

    selected_layers = _normalize_layer_indices(layers, num_layers)
    selected_heads = _normalize_head_indices(heads, num_heads)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for layer in selected_layers:
        layer_attention = torch.as_tensor(attentions[layer - 1])[0]
        for head in selected_heads:
            path = output_dir / f"{prefix}_layer{layer:02d}_head{head:02d}.png"
            generate_diagram(
                layer,
                head,
                tokens,
                layer_attention[head - 1],
                path,
                normalize_rows=normalize_rows,
            )
            paths.append(path)
    return paths


def attention_to_token(
    attentions: Sequence[Any],
    query_index: int,
    key_index: int,
) -> np.ndarray:
    """Return the attention weight for one query/key pair across layers/heads.

    The result has shape ``(num_layers, num_heads)`` and is useful for
    quantitative analysis of a specific dependency (for example, a pronoun
    attending to its antecedent).
    """
    values = []
    for layer_attention in attentions:
        layer_tensor = torch.as_tensor(layer_attention)[0]
        values.append(layer_tensor[:, query_index, key_index].detach().cpu().numpy())
    return np.stack(values)


def _parse_indices(value: str | None) -> list[int] | None:
    if value is None:
        return None
    return [int(part) for part in re.split(r"[,\s]+", value.strip()) if part]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:50] or "sentence"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?", help="Sentence with exactly one [MASK].")
    parser.add_argument("--model", default=MODEL_NAME, help="Hugging Face model name.")
    parser.add_argument("--output", default="results/heatmaps", help="Output directory.")
    parser.add_argument("--prefix", default=None, help="Filename prefix.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--layers", default=None, help="Comma-separated 1-based layers.")
    parser.add_argument("--heads", default=None, help="Comma-separated 1-based heads.")
    parser.add_argument(
        "--no-row-normalize",
        action="store_true",
        help="Show raw attention weights instead of row-normalized values.",
    )
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    text = args.text or input("Text: ")
    tokenizer, model, device = load_pipeline(args.model, args.device)
    result = predict_masked_token(
        text,
        tokenizer,
        model,
        top_k=args.top_k,
        device=device,
        output_attentions=True,
    )

    print(f"Tokens: {result['tokens']}")
    for rank, prediction in enumerate(result["predictions"], start=1):
        print(f"{rank}. {prediction['sentence']}  (p={prediction['probability']:.4f})")

    prefix = args.prefix or _slugify(text)
    paths = visualize_attentions(
        result["tokens"],
        result["attentions"],
        args.output,
        prefix=prefix,
        layers=_parse_indices(args.layers),
        heads=_parse_indices(args.heads),
        normalize_rows=not args.no_row_normalize,
    )
    print(f"Saved {len(paths)} attention maps to {args.output}")


if __name__ == "__main__":
    main()
