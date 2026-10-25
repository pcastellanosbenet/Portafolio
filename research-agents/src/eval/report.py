"""Aggregate evaluation records into a reproducible summary and plot."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.eval.models import EvaluationRecord

_SYSTEM_ORDER = ("b0", "b1", "b2")
_SYSTEM_LABELS = {
    "b0": "B0 · agente único",
    "b1": "B1 · pipeline fijo",
    "b2": "B2 · equipo completo",
}


def load_records(path: Path) -> list[EvaluationRecord]:
    """Read a JSONL file, ignoring blank lines."""
    records: list[EvaluationRecord] = []
    if not path.is_file():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(EvaluationRecord.model_validate_json(line))
    return records


def _mean(values: list[float | int | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return round(sum(present) / len(present), 4) if present else None


def _percentile(values: list[float | int | None], percentile: float) -> float | None:
    present = sorted(float(value) for value in values if value is not None)
    if not present:
        return None
    index = max(0, math.ceil(percentile * len(present)) - 1)
    return round(present[index], 3)


def _metric(records: list[EvaluationRecord], name: str) -> list[float | int | None]:
    return [record.metrics.get(name) for record in records]


def _aggregate_group(records: list[EvaluationRecord]) -> dict[str, Any]:
    answerable = [record for record in records if record.category != "unanswerable"]
    unanswerable = [record for record in records if record.category == "unanswerable"]
    claims = [record for record in records if record.claims]
    return {
        "records": len(records),
        "records_with_errors": sum(1 for record in records if record.errors),
        "judge_errors": sum(1 for record in records if record.judge_error),
        "task_success_rate": _mean(_metric(records, "task_success_binary")),
        "mean_judge_score": _mean(_metric(records, "task_success_score")),
        "factual_coverage": _mean(_metric(answerable, "factual_coverage")),
        "judge_factual_coverage": _mean(_metric(answerable, "judge_factual_coverage")),
        "citation_precision": _mean(_metric(answerable, "citation_precision")),
        "citation_validity": _mean(_metric(answerable, "citation_validity")),
        "source_recall": _mean(_metric(answerable, "source_recall")),
        "claim_support_rate": _mean(_metric(claims, "claim_support_rate")),
        "claim_relevance_rate": _mean(_metric(claims, "claim_relevance_rate")),
        "abstention_accuracy": _mean(_metric(unanswerable, "abstention_correct")),
        "abstention_rate": _mean(_metric(unanswerable, "abstained")),
        "avg_llm_calls": _mean([record.usage.llm_calls for record in records]),
        "avg_tokens": _mean([record.usage.total_tokens for record in records]),
        "avg_search_calls": _mean([record.usage.search_calls for record in records]),
        "p50_latency_s": _percentile([record.duration_s for record in records], 0.50),
        "p95_latency_s": _percentile([record.duration_s for record in records], 0.95),
        "total_tokens": sum(record.usage.total_tokens for record in records),
        "total_llm_calls": sum(record.usage.llm_calls for record in records),
    }


def aggregate(records: list[EvaluationRecord], *, run_id: str) -> dict[str, Any]:
    """Group records by system and category."""
    by_system: dict[str, list[EvaluationRecord]] = defaultdict(list)
    by_category: dict[str, dict[str, list[EvaluationRecord]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for record in records:
        by_system[record.system].append(record)
        by_category[record.category][record.system].append(record)
    systems = [system for system in _SYSTEM_ORDER if system in by_system]
    overall = {system: _aggregate_group(by_system[system]) for system in systems}
    categories = {
        category: {
            system: _aggregate_group(by_category[category][system])
            for system in systems
            if by_category[category][system]
        }
        for category in ("factual", "comparison", "multi_hop", "unanswerable")
        if by_category[category]
    }
    return {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "systems": systems,
        "record_count": len(records),
        "overall": overall,
        "by_category": categories,
    }


def _format_number(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:.{digits}f}"


def _overall_table(summary: dict[str, Any]) -> str:
    systems = summary["systems"]
    headers = [
        "Sistema",
        "Éxito tarea",
        "Score juez",
        "Cobertura",
        "Precisión citas",
        "Validez citas",
        "Recall fuentes",
        "Soporte claims",
        "Abstención",
        "Llamadas",
        "Tokens",
        "Latencia p50",
        "Latencia p95",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join([":---"] + [":---:"] * (len(headers) - 1)) + " |",
    ]
    for system in systems:
        row = summary["overall"][system]
        label = f"{_SYSTEM_LABELS.get(system, system)} ({row['records']})"
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    _format_number(row["task_success_rate"]),
                    _format_number(row["mean_judge_score"]),
                    _format_number(row["factual_coverage"]),
                    _format_number(row["citation_precision"]),
                    _format_number(row["citation_validity"]),
                    _format_number(row["source_recall"]),
                    _format_number(row["claim_support_rate"]),
                    _format_number(row["abstention_accuracy"]),
                    _format_number(row["avg_llm_calls"]),
                    _format_number(row["avg_tokens"]),
                    _format_number(row["p50_latency_s"], 1),
                    _format_number(row["p95_latency_s"], 1),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _category_table(summary: dict[str, Any]) -> str:
    systems = summary["systems"]
    headers = ["Categoría", *[_SYSTEM_LABELS.get(system, system) for system in systems]]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join([":---"] + [":---:"] * len(systems)) + " |",
    ]
    for category, groups in summary["by_category"].items():
        values = []
        for system in systems:
            group = groups.get(system)
            values.append(
                "—"
                if group is None
                else _format_number(group["task_success_rate"])
            )
        lines.append(f"| {category} | " + " | ".join(values) + " |")
    return "\n".join(lines)


def _svg_plot(summary: dict[str, Any]) -> str:
    """A dependency-free scatter plot of task success versus tokens."""
    systems = summary["systems"]
    points = []
    for system in systems:
        row = summary["overall"][system]
        x = row["avg_tokens"] or 0
        y = row["task_success_rate"]
        if y is None:
            continue
        points.append((system, float(x), float(y), row["records"]))
    width, height, margin = 720, 420, 64
    max_x = max((point[1] for point in points), default=1.0) or 1.0
    def sx(value: float) -> float:
        return margin + (value / max_x) * (width - 2 * margin)
    def sy(value: float) -> float:
        return height - margin - value * (height - 2 * margin)
    circles = []
    for system, x, y, records in points:
        circles.append(
            f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="9" '
            f'fill="#2563eb" stroke="#1e3a8a" stroke-width="2" />'
        )
        circles.append(
            f'<text x="{sx(x) + 14:.1f}" y="{sy(y) + 5:.1f}" '
            f'font-family="sans-serif" font-size="14">{system.upper()} ({records})</text>'
        )
    grid = []
    for step in range(6):
        y = step / 5
        grid.append(
            f'<line x1="{margin}" y1="{sy(y):.1f}" x2="{width - margin}" '
            f'y2="{sy(y):.1f}" stroke="#e5e7eb" stroke-width="1" />'
        )
        grid.append(
            f'<text x="{margin - 12}" y="{sy(y) + 4:.1f}" text-anchor="end" '
            f'font-family="sans-serif" font-size="12">{y:.1f}</text>'
        )
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white" />',
            *grid,
            f'<line x1="{margin}" y1="{height - margin}" x2="{width - margin}" '
            f'y2="{height - margin}" stroke="#111827" stroke-width="2" />',
            f'<line x1="{margin}" y1="{margin}" x2="{margin}" '
            f'y2="{height - margin}" stroke="#111827" stroke-width="2" />',
            *circles,
            f'<text x="{width / 2}" y="{height - 20}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="14">Tokens medios por ejecución</text>',
            f'<text x="20" y="{height / 2}" text-anchor="middle" '
            f'transform="rotate(-90 20 {height / 2})" font-family="sans-serif" '
            f'font-size="14">Éxito de tarea</text>',
            "</svg>",
        ]
    )


def write_summary(
    records: list[EvaluationRecord],
    *,
    run_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Write ``summary.json``, ``summary.md`` and the SVG plot."""
    summary = aggregate(records, run_id=run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown = "\n".join(
        [
            f"# Evaluación {run_id}",
            "",
            f"Generado: {summary['generated_at']}",
            "",
            f"Registros: {summary['record_count']}",
            "",
            "Este resumen agrega ejecuciones reales; la metodología, la revisión "
            "manual y las limitaciones están en `docs/evaluation.md`.",
            "",
            "## Resultados globales",
            "",
            _overall_table(summary),
            "",
            "## Éxito de tarea por categoría",
            "",
            _category_table(summary),
            "",
            "El número entre paréntesis de la tabla global es el total de registros por "
            "sistema; una categoría con pocos registros (por ejemplo, n=1) no es comparable "
            "con una de n=5.",
            "",
            "## Calidad frente a coste",
            "",
            "El gráfico usa el éxito de tarea medio y los tokens medios por ejecución.",
            "",
            "![Calidad frente a tokens](quality_vs_tokens.svg)",
            "",
        ]
    )
    (output_dir / "summary.md").write_text(markdown, encoding="utf-8")
    (output_dir / "quality_vs_tokens.svg").write_text(_svg_plot(summary), encoding="utf-8")
    return summary
