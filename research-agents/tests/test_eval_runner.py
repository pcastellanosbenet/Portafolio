"""Tests for resumability and aggregate reporting."""

from __future__ import annotations

import json
from pathlib import Path

from src.eval.models import EvaluationRecord
from src.eval.report import aggregate, load_records, write_summary
from src.eval.runner import load_done_keys, merge_run_meta
from src.models import Usage


def make_record(
    system: str,
    question_id: str,
    *,
    repetition: int = 1,
    category: str = "factual",
    metrics: dict[str, object] | None = None,
) -> EvaluationRecord:
    return EvaluationRecord(
        run_id="run",
        system=system,  # type: ignore[arg-type]
        question_id=question_id,
        category=category,  # type: ignore[arg-type]
        question="Question?",
        repetition=repetition,
        answer_markdown="Answer.",
        status="done",
        usage=Usage(llm_calls=2, total_tokens=100),
        duration_s=1.5,
        metrics=metrics
        or {
            "task_success_binary": 1.0,
            "task_success_score": 2,
            "factual_coverage": 1.0,
            "citation_precision": 1.0,
            "source_recall": 1.0,
            "claim_support_rate": 1.0,
            "abstention_correct": None,
            "abstained": False,
        },
    )


def test_load_done_keys_tolerates_a_partial_last_line(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    record = make_record("b0", "F01")
    path.write_text(
        record.model_dump_json() + "\n" + '{"run_id": "partial"',
        encoding="utf-8",
    )

    assert load_done_keys(path) == {("F01", "b0", 1)}


def test_load_records_ignores_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(
        "\n" + make_record("b1", "F01").model_dump_json() + "\n\n",
        encoding="utf-8",
    )

    records = load_records(path)

    assert len(records) == 1
    assert records[0].system == "b1"


def test_merge_run_meta_preserves_earlier_systems_and_creation_time() -> None:
    existing = {
        "created_at": "2026-10-24T07:02:45+00:00",
        "systems": ["b0"],
        "question_ids": ["F01"],
        "config": {"max_llm_calls": 12},
    }
    new = {
        "created_at": "2026-10-25T08:00:00+00:00",
        "systems": ["b1"],
        "question_ids": ["F02"],
        "config": {"max_llm_calls": 12},
    }

    merged = merge_run_meta(existing, new)

    assert merged["created_at"] == existing["created_at"]
    assert merged["systems"] == ["b0", "b1"]
    assert merged["question_ids"] == ["F01", "F02"]
    assert merged["resumed"] is True
    assert "configs" not in merged


def test_merge_run_meta_keeps_distinct_configs() -> None:
    existing = {"systems": ["b0"], "config": {"max_llm_calls": 12}}
    new = {"systems": ["b1"], "config": {"max_llm_calls": 20}}

    merged = merge_run_meta(existing, new)

    assert merged["config"] == {"max_llm_calls": 20}
    assert merged["configs"] == [{"max_llm_calls": 12}, {"max_llm_calls": 20}]


def test_aggregate_groups_by_system_and_category() -> None:
    records = [
        make_record("b0", "F01"),
        make_record("b1", "F01"),
        make_record(
            "b0",
            "U01",
            category="unanswerable",
            metrics={
                "task_success_binary": 0.0,
                "task_success_score": 0,
                "factual_coverage": 0.0,
                "citation_precision": 0.0,
                "source_recall": 0.0,
                "claim_support_rate": None,
                "abstention_correct": 0.0,
                "abstained": False,
            },
        ),
    ]

    summary = aggregate(records, run_id="run")

    assert summary["systems"] == ["b0", "b1"]
    assert summary["record_count"] == 3
    assert summary["overall"]["b0"]["records"] == 2
    assert summary["by_category"]["unanswerable"]["b0"]["abstention_accuracy"] == 0.0
    assert summary["overall"]["b1"]["task_success_rate"] == 1.0


def test_write_summary_creates_json_markdown_and_svg(tmp_path: Path) -> None:
    records = [make_record("b0", "F01"), make_record("b1", "F01")]
    output_dir = tmp_path / "run"

    summary = write_summary(records, run_id="run", output_dir=output_dir)

    assert summary["record_count"] == 2
    assert (output_dir / "summary.json").is_file()
    assert (output_dir / "summary.md").is_file()
    assert (output_dir / "quality_vs_tokens.svg").is_file()
    svg = (output_dir / "quality_vs_tokens.svg").read_text(encoding="utf-8")
    assert "<svg" in svg and "B0" in svg


def test_summary_json_is_valid_and_contains_no_settings_secrets(tmp_path: Path) -> None:
    write_summary([make_record("b0", "F01")], run_id="run", output_dir=tmp_path)
    data = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert data["run_id"] == "run"
    assert "api_key" not in json.dumps(data).lower()
