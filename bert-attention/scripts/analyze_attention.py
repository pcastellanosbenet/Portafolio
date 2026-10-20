"""Reproduce the qualitative analysis of BERT attention.

The script runs three probe sentences through ``bert-base-uncased``, saves a
curated set of layer/head heatmaps and writes the raw attention values needed
to verify the observations in ``analysis.md``.

Usage::

    uv run python -m scripts.analyze_attention
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from src.mask import (
    attention_to_token,
    generate_diagram,
    load_pipeline,
    predict_masked_token,
)

SENTENCES = {
    "simple": "The [MASK] sat on the mat.",
    "coref": "The animal did not cross the street because it was too [MASK].",
    "course": "I learned a lot from this [MASK] artificial intelligence course.",
}

# Layer/head pairs chosen after inspecting the 12x12 grid of heads for each
# sentence.  The selection is intentionally small and curated for the README.
CURATED_MAPS = {
    "simple": [(1, 6), (3, 1), (7, 4)],
    "coref": [(4, 11), (7, 12), (11, 7)],
    "course": [(8, 5), (11, 11)],
}

FOCUS = {
    "simple": ("[MASK]", "sat"),
    "coref": ("it", "animal"),
    "course": ("[MASK]", "course"),
}


def attention_matrix(attentions: list[torch.Tensor], layer: int, head: int) -> np.ndarray:
    """Return one layer/head matrix as a NumPy array."""
    return torch.as_tensor(attentions[layer - 1])[0, head - 1].detach().cpu().numpy()


def top_pairs(
    tokens: list[str],
    weights: np.ndarray,
    *,
    limit: int = 12,
    threshold: float = 0.05,
) -> list[dict[str, float | int | str]]:
    """Return the strongest query->key pairs in a matrix."""
    pairs: list[dict[str, float | int | str]] = []
    for query_index, query in enumerate(tokens):
        for key_index, key in enumerate(tokens):
            weight = float(weights[query_index, key_index])
            if weight >= threshold:
                pairs.append(
                    {
                        "query": query,
                        "key": key,
                        "query_index": query_index,
                        "key_index": key_index,
                        "weight": weight,
                    }
                )
    pairs.sort(key=lambda row: float(row["weight"]), reverse=True)
    return pairs[:limit]


def entropy_by_layer(attentions: list[torch.Tensor]) -> list[float]:
    """Mean attention entropy for each layer (lower = more concentrated)."""
    values = []
    for layer_attention in attentions:
        attention = torch.as_tensor(layer_attention)[0]
        entropy = -(attention * torch.log(attention + 1e-12)).sum(dim=-1).mean()
        values.append(float(entropy))
    return values


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    repo_root = project_root.parent
    output_dir = repo_root / "docs" / "attention"
    output_dir.mkdir(parents=True, exist_ok=True)
    tokenizer, model, device = load_pipeline()

    payload: dict[str, object] = {
        "model": "bert-base-uncased",
        "method": "masked-language-model attention, eager implementation",
        "sentences": {},
    }
    sentences_payload: dict[str, object] = {}

    for slug, text in SENTENCES.items():
        result = predict_masked_token(
            text,
            tokenizer,
            model,
            top_k=5,
            device=device,
            output_attentions=True,
        )
        attentions = result["attentions"]
        tokens = result["tokens"]
        mask_index = result["mask_index"]

        maps_payload = []
        for layer, head in CURATED_MAPS[slug]:
            weights = attention_matrix(attentions, layer, head)
            filename = f"{slug}_layer{layer:02d}_head{head:02d}.png"
            generate_diagram(
                layer,
                head,
                tokens,
                weights,
                output_dir / filename,
            )
            maps_payload.append(
                {
                    "layer": layer,
                    "head": head,
                    "file": str((output_dir / filename).relative_to(repo_root)),
                    "attention": weights.round(6).tolist(),
                    "top_pairs": top_pairs(tokens, weights),
                }
            )

        # Quantitative probe: pronoun -> antecedent across all layers/heads.
        coreference = None
        query, key = FOCUS[slug]
        if query in tokens and key in tokens:
            query_index = tokens.index(query)
            key_index = tokens.index(key)
            values = attention_to_token(attentions, query_index, key_index)
            flat_order = np.argsort(values.ravel())[::-1][:10]
            coreference = {
                "query": query,
                "key": key,
                "by_layer_head": [
                    {
                        "layer": int(index // values.shape[1]) + 1,
                        "head": int(index % values.shape[1]) + 1,
                        "weight": float(values.ravel()[index]),
                    }
                    for index in flat_order
                ],
            }

        mask_row = torch.as_tensor(attentions[-1])[0, :, mask_index].mean(dim=0).cpu().numpy()
        mask_top_keys = [
            {"token": tokens[index], "weight": float(mask_row[index])}
            for index in np.argsort(mask_row)[::-1][:8]
        ]

        sentences_payload[slug] = {
            "text": text,
            "tokens": tokens,
            "mask_index": mask_index,
            "predictions": result["predictions"],
            "maps": maps_payload,
            "focus_probe": coreference,
            "last_layer_mean_mask_attention": mask_top_keys,
            "entropy_by_layer": entropy_by_layer(attentions),
        }
        print(f"{slug}: {[prediction['word'] for prediction in result['predictions']]}")
        for item in maps_payload:
            print(f"  saved {item['file']}")

    payload["sentences"] = sentences_payload
    output_file = project_root / "results" / "analysis.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {output_file}")


if __name__ == "__main__":
    main()
