"""Validate the curated traces shipped with the documentation."""

from __future__ import annotations

import json
from pathlib import Path

from src.citations import validate_citations
from src.models import FinalReport


def test_curated_examples_are_valid_final_reports() -> None:
    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples"
    paths = sorted(example_dir.glob("*.json"))
    assert len(paths) == 5

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        report = FinalReport.model_validate(payload["report"])
        validation = validate_citations(report)

        assert payload["question"], path.name
        assert report.claims, path.name
        assert report.sources, path.name
        assert validation.valid, (path.name, validation.issues)
