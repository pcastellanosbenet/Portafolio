"""Run the Phase 4 evaluation from the command line."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.config import Settings
from src.eval.corpus import load_corpus, load_questions, validate_questions_against_corpus
from src.eval.report import load_records, write_summary
from src.eval.runner import EvaluationRunner

SYSTEMS = ("b0", "b1", "b2")
CATEGORIES = ("factual", "comparison", "multi_hop", "unanswerable")


def _parse_systems(value: str) -> list[str]:
    systems = [item.strip().lower() for item in value.split(",") if item.strip()]
    unknown = [item for item in systems if item not in SYSTEMS]
    if unknown:
        raise argparse.ArgumentTypeError(f"Unknown systems: {', '.join(unknown)}")
    return list(dict.fromkeys(systems))


def _parse_categories(value: str) -> list[str]:
    categories = [item.strip().lower() for item in value.split(",") if item.strip()]
    unknown = [item for item in categories if item not in CATEGORIES]
    if unknown:
        raise argparse.ArgumentTypeError(f"Unknown categories: {', '.join(unknown)}")
    return list(dict.fromkeys(categories))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the B0/B1/B2 evaluation on the frozen corpus."
    )
    parser.add_argument(
        "--systems",
        type=_parse_systems,
        default=list(SYSTEMS),
        help="Comma-separated systems: b0,b1,b2 (default: all).",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path("eval/questions.json"),
        help="Question set JSON.",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("eval/frozen/corpus.json"),
        help="Frozen corpus JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("eval/results"),
        help="Directory for run results.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run identifier. Required for a deterministic resume.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip runs already present in records.jsonl.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only evaluate the first N selected questions.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="Repetitions per question/system (default: 1).",
    )
    parser.add_argument(
        "--question-id",
        action="append",
        default=[],
        help="Evaluate only this question id; can be repeated.",
    )
    parser.add_argument(
        "--category",
        type=_parse_categories,
        default=[],
        help="Evaluate only these categories; can be repeated or comma-separated.",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip the LLM judge and keep only deterministic metrics.",
    )
    parser.add_argument(
        "--judge-provider",
        choices=("groq", "gemini"),
        default=None,
        help="Provider for the independent judge.",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Model for the independent judge.",
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Allow the system to switch to the fallback provider mid-run.",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="Override RESEARCH_MAX_ROUNDS.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Override RESEARCH_MAX_WORKERS.",
    )
    parser.add_argument(
        "--max-tool-steps",
        type=int,
        default=None,
        help="Override RESEARCH_MAX_TOOL_STEPS.",
    )
    parser.add_argument(
        "--max-llm-calls",
        type=int,
        default=None,
        help="Override RESEARCH_MAX_LLM_CALLS.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Override RESEARCH_MAX_TOKENS.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the corpus and questions, print the plan and exit.",
    )
    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    env_file = Path(__file__).resolve().parents[1] / ".env"
    settings = Settings(_env_file=env_file)
    update: dict[str, object] = {}
    if args.max_rounds is not None:
        update["max_rounds"] = args.max_rounds
    if args.max_workers is not None:
        update["max_workers"] = args.max_workers
    if args.max_tool_steps is not None:
        update["max_tool_steps"] = args.max_tool_steps
    if args.max_llm_calls is not None:
        update["max_llm_calls"] = args.max_llm_calls
    if args.max_tokens is not None:
        update["max_tokens"] = args.max_tokens
    if args.judge_provider:
        update["judge_provider"] = args.judge_provider
    if args.judge_model:
        update["judge_model"] = args.judge_model
    if update:
        settings = settings.model_copy(update=update)
    return settings


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than zero.")
    if args.repetitions <= 0:
        parser.error("--repetitions must be greater than zero.")
    if args.judge_provider and not args.judge_model:
        parser.error("--judge-provider requires --judge-model.")
    if args.resume and not args.run_id:
        parser.error("--resume requires --run-id so the runner knows where to look.")

    corpus = load_corpus(args.corpus)
    questions = load_questions(args.questions)
    try:
        validate_questions_against_corpus(questions, corpus)
    except ValueError as exc:
        print(f"Invalid evaluation data: {exc}", file=sys.stderr)
        return 2

    selected = [
        question
        for question in questions.questions
        if (not args.question_id or question.id in set(args.question_id))
        and (not args.category or question.category in set(args.category))
    ]
    if args.limit is not None:
        selected = selected[: args.limit]
    if not selected:
        print("No question matches the filters.", file=sys.stderr)
        return 2

    if args.dry_run:
        counts = {
            category: sum(1 for question in selected if question.category == category)
            for category in CATEGORIES
        }
        print(f"Corpus: {len(corpus.documents)} documents ({corpus.license})")
        print(f"Questions: {len(selected)} selected from {len(questions.questions)}")
        print(f"Systems: {', '.join(system.upper() for system in args.systems)}")
        print(f"Repetitions: {args.repetitions}")
        print(f"Planned runs: {len(selected) * args.repetitions * len(args.systems)}")
        print("By category: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
        return 0

    run_id = args.run_id or f"eval-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    settings = _settings_from_args(args)
    try:
        runner = EvaluationRunner(
            settings,
            corpus=corpus,
            questions=questions,
            systems=args.systems,
            run_id=run_id,
            output_dir=args.output_dir,
            corpus_path=args.corpus,
            questions_path=args.questions,
            repetitions=args.repetitions,
            use_judge=not args.no_judge,
            use_fallback=args.allow_fallback,
            limit=None,
            question_ids=set(args.question_id),
            categories=set(args.category),
        )
    except (OSError, ValueError) as exc:
        print(f"Could not start the evaluation: {exc}", file=sys.stderr)
        return 2
    try:
        summary = runner.run(resume=args.resume)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted. Existing records were preserved.", file=sys.stderr)
        records = load_records(runner.records_path)
        if records:
            write_summary(records, run_id=run_id, output_dir=runner.run_dir)
            print(f"Partial summary: {runner.run_dir / 'summary.md'}", file=sys.stderr)
        return 130
    print(f"Summary: {runner.run_dir / 'summary.md'}")
    print(f"Records: {runner.records_path}")
    if summary["record_count"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
