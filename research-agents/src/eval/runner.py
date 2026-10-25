"""Resumable evaluation runner.

Results are appended to ``records.jsonl`` after every run. A second invocation
with ``--resume`` and the same run id skips the completed
(question, system, repetition) keys. Raw records are never rewritten, so an
interrupted batch keeps the runs that already finished.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config import Settings
from src.eval.corpus import Corpus, QuestionSet, validate_questions_against_corpus
from src.eval.judge import Judge, build_judge
from src.eval.metrics import compute_metrics
from src.eval.models import EvalQuestion, EvaluationRecord, SystemName
from src.eval.report import load_records, write_summary
from src.eval.systems import SystemRun, run_system
from src.graph import build_graph
from src.services import build_services


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _system_run_id(run_id: str, question_id: str, system: str, repetition: int) -> str:
    return f"{run_id}-{question_id}-{system}-r{repetition}"


_SYSTEM_ORDER = {"b0": 0, "b1": 1, "b2": 2}


def merge_run_meta(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Merge metadata from a resumed batch without losing earlier systems.

    A run id can be reused to complete B1/B2 after B0. Rewriting the metadata
    with only the latest ``--systems`` would make the run look as if the earlier
    systems had never been evaluated, so the union is kept here. If the limits
    changed between batches, the distinct configurations are preserved under
    ``configs`` while ``config`` keeps the effective latest one.
    """
    if not existing:
        return new
    merged = dict(new)
    created_at = existing.get("created_at") or new.get("created_at")
    if created_at:
        merged["created_at"] = created_at
    merged["systems"] = sorted(
        set(existing.get("systems", [])) | set(new.get("systems", [])),
        key=lambda system: _SYSTEM_ORDER.get(system, len(_SYSTEM_ORDER)),
    )
    configs = list(existing.get("configs") or [])
    if existing.get("config") and existing["config"] not in configs:
        configs.append(existing["config"])
    if new.get("config") and new["config"] not in configs:
        configs.append(new["config"])
    if len(configs) > 1:
        merged["configs"] = configs
    if existing.get("question_ids") and new.get("question_ids"):
        merged["question_ids"] = sorted(
            set(existing["question_ids"]) | set(new["question_ids"])
        )
    merged["resumed"] = True
    return merged


def load_done_keys(path: Path) -> set[tuple[str, str, int]]:
    """Return the resumable keys from a JSONL file.

    A partially written final line (for example after a hard kill) is ignored;
    all earlier records remain usable.
    """
    done: set[tuple[str, str, int]] = set()
    if not path.is_file():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = EvaluationRecord.model_validate_json(line)
        except Exception:  # noqa: BLE001 - tolerate a partially written last line
            continue
        done.add((record.question_id, record.system, record.repetition))
    return done


class EvaluationRunner:
    """Execute the selected systems over a frozen corpus."""

    def __init__(
        self,
        settings: Settings,
        *,
        corpus: Corpus,
        questions: QuestionSet,
        systems: Iterable[SystemName],
        run_id: str,
        output_dir: Path,
        corpus_path: Path,
        questions_path: Path,
        repetitions: int = 1,
        use_judge: bool = True,
        use_fallback: bool = False,
        limit: int | None = None,
        question_ids: set[str] | None = None,
        categories: set[str] | None = None,
    ) -> None:
        validate_questions_against_corpus(questions, corpus)
        self.corpus = corpus
        self.questions = questions
        self.systems = list(dict.fromkeys(systems))
        self.run_id = run_id
        self.output_dir = output_dir / run_id
        self.corpus_path = corpus_path
        self.questions_path = questions_path
        self.repetitions = repetitions
        self.use_judge = use_judge
        self.limit = limit
        self.question_ids = question_ids or set()
        self.categories = categories or set()

        self.run_dir = self.output_dir
        self.records_path = self.run_dir / "records.jsonl"
        self.eval_settings = settings.model_copy(
            update={
                "search_backend": "frozen",
                "search_primary": "frozen",
                "search_fallback": "none",
                "frozen_corpus_path": corpus_path.resolve(),
                "hitl": False,
                "llm_fallback_provider": settings.llm_fallback_provider if use_fallback else None,
                "llm_fallback_model": settings.llm_fallback_model if use_fallback else "",
            }
        )
        self.services = build_services(self.eval_settings)
        self.graph = (
            build_graph(self.services) if "b2" in self.systems else None
        )
        self.judge: Judge | None = None
        if use_judge:
            self.judge = build_judge(settings)
        self.run_config = {
            "llm_provider": self.eval_settings.llm_provider,
            "llm_model": self.eval_settings.llm_model,
            "llm_fast_model": self.eval_settings.fast_model,
            "fallback_enabled": bool(self.eval_settings.llm_fallback_provider),
            "search_backend": "frozen",
            "max_llm_calls": self.eval_settings.max_llm_calls,
            "max_tokens": self.eval_settings.max_tokens,
            "max_rounds": self.eval_settings.max_rounds,
            "max_workers": self.eval_settings.max_workers,
            "max_tool_steps": self.eval_settings.max_tool_steps,
            "judge_provider": settings.judge_target[0] if use_judge else None,
            "judge_model": settings.judge_target[1] if use_judge else None,
        }

    def selected_questions(self) -> list[EvalQuestion]:
        selected = [
            question
            for question in self.questions.questions
            if (not self.question_ids or question.id in self.question_ids)
            and (not self.categories or question.category in self.categories)
        ]
        return selected[: self.limit] if self.limit is not None else selected

    def _load_done(self) -> set[tuple[str, str, int]]:
        return load_done_keys(self.records_path)

    def _write_meta(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self.run_dir / "run_meta.json"
        meta: dict[str, Any] = {
            "run_id": self.run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "systems": self.systems,
            "question_count": len(self.selected_questions()),
            "repetitions": self.repetitions,
            "corpus": {
                "path": str(self.corpus_path),
                "sha256": _sha256_file(self.corpus_path),
                "documents": len(self.corpus.documents),
                "license": self.corpus.license,
            },
            "questions": {
                "path": str(self.questions_path),
                "sha256": _sha256_file(self.questions_path),
                "version": self.questions.version,
            },
            "config": self.run_config,
            "resume_supported": True,
        }
        if self.question_ids:
            meta["question_ids"] = sorted(self.question_ids)
        if self.categories:
            meta["categories"] = sorted(self.categories)
        if self.limit is not None:
            meta["limit"] = self.limit
        if meta_path.is_file():
            try:
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            if isinstance(existing, dict):
                meta = merge_run_meta(existing, meta)
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _append(self, record: EvaluationRecord) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.records_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _make_record(
        self,
        run: SystemRun,
        question: EvalQuestion,
        *,
        repetition: int,
        system_run_id: str,
    ) -> EvaluationRecord:
        report = run.report
        record = EvaluationRecord(
            run_id=self.run_id,
            system_run_id=system_run_id,
            system=run.system,
            question_id=question.id,
            category=question.category,
            question=question.question,
            repetition=repetition,
            answer_markdown=report.answer_markdown if report else "",
            claims=report.claims if report else [],
            sources=report.sources if report else [],
            limitations=report.limitations if report else [],
            confidence=report.confidence if report else "low",
            status=run.status,
            errors=list(run.errors),
            usage=run.usage,
            duration_s=run.duration_s,
            trace=list(run.trace),
            run_config=self.run_config,
        )
        if self.judge is not None:
            try:
                judged = self.judge.evaluate(question, record)
                record = record.model_copy(
                    update={
                        "judge": judged.output,
                        "judge_usage": judged.usage,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - judge failures are data, not a crash
                record = record.model_copy(
                    update={"judge_error": f"{type(exc).__name__}: {exc}"}
                )
        return record.model_copy(
            update={"metrics": compute_metrics(record, question)}
        )

    def _recompute_metrics(self, records: list[EvaluationRecord]) -> list[EvaluationRecord]:
        """Recompute derived metrics from the stored raw answers.

        This keeps a resumed summary consistent when the metric code changes;
        it does not call a model or alter the recorded answer, claims or usage.
        """
        questions = {question.id: question for question in self.questions.questions}
        updated: list[EvaluationRecord] = []
        for record in records:
            question = questions.get(record.question_id)
            if question is None:
                updated.append(record)
                continue
            updated.append(
                record.model_copy(update={"metrics": compute_metrics(record, question)})
            )
        return updated

    def run(self, *, resume: bool = False) -> dict[str, Any]:
        """Run all selected combinations, then write the summary."""
        if self.records_path.exists() and not resume:
            raise FileExistsError(
                f"Results already exist at {self.records_path}. "
                "Use --resume or choose another --run-id."
            )
        self._write_meta()
        done = self._load_done() if resume else set()
        questions = self.selected_questions()
        total = len(questions) * self.repetitions * len(self.systems)
        completed = 0
        skipped = 0
        for question in questions:
            for repetition in range(1, self.repetitions + 1):
                for system in self.systems:
                    key = (question.id, system, repetition)
                    if key in done:
                        skipped += 1
                        completed += 1
                        continue
                    system_run_id = _system_run_id(
                        self.run_id, question.id, system, repetition
                    )
                    completed += 1
                    print(
                        f"[{completed}/{total}] {system.upper()} {question.id} "
                        f"rep={repetition}",
                        flush=True,
                    )
                    run = run_system(
                        system,
                        self.services,
                        question.question,
                        run_id=system_run_id,
                        graph=self.graph,
                    )
                    record = self._make_record(
                        run,
                        question,
                        repetition=repetition,
                        system_run_id=system_run_id,
                    )
                    self._append(record)
                    if record.errors:
                        print(f"  errors: {len(record.errors)}", flush=True)
                    if record.judge_error:
                        print(f"  judge error: {record.judge_error}", flush=True)
        records = self._recompute_metrics(load_records(self.records_path))
        summary = write_summary(records, run_id=self.run_id, output_dir=self.run_dir)
        print(
            f"Wrote {len(records)} records and summary to {self.run_dir} "
            f"({skipped} skipped on resume).",
            flush=True,
        )
        return summary
