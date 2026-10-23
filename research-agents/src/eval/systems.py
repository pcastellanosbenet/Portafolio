"""B0, B1 and B2 system runners for the Phase 4 evaluation.

B0 is one tool-using ReAct agent. B1 is a fixed planner -> researchers -> writer
pipeline without the supervisor, analyst or critic. B2 is the full graph from
``src.graph``. All three use the same frozen tools and the same hard budgets.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.agents.base import AgentServices, compact_notes, compact_sources, json_payload
from src.agents.planner import fallback_plan
from src.agents.writer import build_final_report, fallback_draft
from src.budget import BudgetExceeded, usage_from_metadata
from src.citations import validate_citations
from src.eval.models import SystemName
from src.graph import build_graph, run_research
from src.models import (
    FinalReport,
    ReportDraft,
    ResearchBrief,
    ResearchOutput,
    ResearchPlan,
    ResearchTask,
    SubQuestion,
    Usage,
)
from src.prompts import messages
from src.state import ResearchState
from src.trace import TraceEvent, trace


@dataclass
class SystemRun:
    """A system report plus the resources and audit trail it produced."""

    system: SystemName
    report: FinalReport | None
    usage: Usage = field(default_factory=Usage)
    trace: list[TraceEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "failed"
    duration_s: float = 0.0


def _validate_report(report: FinalReport) -> FinalReport:
    validation = validate_citations(report)
    if not validation.issues:
        return report
    return report.model_copy(
        update={"limitations": list(dict.fromkeys([*report.limitations, *validation.issues]))}
    )


def _check_budget(services: AgentServices, usage: Usage) -> None:
    services.budget.check_llm_usage(usage)


def _output_report(
    brief: ResearchBrief,
    output: ResearchOutput,
    *,
    usage: Usage,
    errors: list[str],
) -> FinalReport:
    """Turn a single agent's structured answer into a citable report."""
    note = output.to_note(brief.question)
    notes = [note] if output.claims or output.sources else []
    state: ResearchState = {
        "brief": brief,
        "notes": notes,
        "sources": {source.source_id: source for source in output.sources},
        "analysis": None,
        "critique": None,
        "errors": errors,
        "usage": usage,
    }
    lines = [output.summary.strip()]
    if output.claims:
        lines.extend(["", "## Hallazgos", ""])
        for claim in output.claims:
            citations = " ".join(f"[{source_id}]" for source_id in claim.source_ids)
            lines.append(f"- {claim.text}" + (f" {citations}" if citations else ""))
    if output.gaps:
        lines.extend(["", "## Limitaciones", ""])
        lines.extend(f"- {gap}" for gap in output.gaps)
    draft = fallback_draft(state)
    draft = draft.model_copy(
        update={
            "title": f"Respuesta directa: {brief.question[:80]}",
            "answer_markdown": "\n".join(line for line in lines if line is not None).strip(),
            "confidence": output.confidence,
            "limitations": output.gaps,
        }
    )
    return _validate_report(build_final_report(state, draft, usage=usage))


def run_b0(services: AgentServices, question: str, *, run_id: str) -> SystemRun:
    """Run a single ReAct agent with the same tools and step budget."""
    started = time.perf_counter()
    brief = ResearchBrief(question=question, language="es")
    task = ResearchTask(
        subquestion=SubQuestion(
            question=question,
            rationale="Answer the original question directly with the available tools.",
        ),
        brief=brief,
    )
    try:
        result = services.researcher.research(
            task,
            max_steps=services.settings.max_tool_steps,
        )
        report = _output_report(
            brief,
            result.output,
            usage=result.usage,
            errors=list(result.errors),
        )
        return SystemRun(
            system="b0",
            report=report,
            usage=result.usage,
            trace=[
                *result.trace,
                trace(
                    "b0",
                    "answer_created",
                    claims=len(report.claims),
                    sources=len(report.sources),
                    tokens=result.usage.total_tokens,
                    latency_s=result.usage.latency_s,
                ),
            ],
            errors=list(result.errors),
            status="done" if report is not None else "failed",
            duration_s=round(time.perf_counter() - started, 3),
        )
    except Exception as exc:  # noqa: BLE001 - one failed run must not stop the evaluation
        return SystemRun(
            system="b0",
            report=None,
            errors=[f"b0: {type(exc).__name__}: {exc}"],
            status="failed",
            duration_s=round(time.perf_counter() - started, 3),
        )


def run_b1(services: AgentServices, question: str, *, run_id: str) -> SystemRun:
    """Run the fixed planner -> researchers -> writer pipeline."""
    del run_id
    started = time.perf_counter()
    brief = ResearchBrief(question=question, language="es")
    usage = Usage()
    errors: list[str] = []
    events: list[TraceEvent] = []

    plan = fallback_plan(brief)
    try:
        _check_budget(services, usage)
        planned, metadata = services.llm.invoke_structured(
            ResearchPlan,
            messages("planner", json_payload(brief.model_dump(mode="json"))),
        )
        plan = planned
        delta = usage_from_metadata(metadata)
        usage = usage.merged(delta)
        events.append(
            trace(
                "planner",
                "plan_created",
                subquestions=len(plan.subquestions),
                model=metadata.model,
                tokens=delta.total_tokens,
                llm_calls=delta.llm_calls,
            )
        )
    except Exception as exc:  # noqa: BLE001 - use the deterministic plan
        errors.append(f"b1 planner: {type(exc).__name__}: {exc}")
        events.append(trace("planner", "fallback", error=str(exc)))

    notes = []
    sources = {}
    for subquestion in plan.subquestions:
        try:
            _check_budget(services, usage)
            result = services.researcher.research(
                ResearchTask(subquestion=subquestion, brief=brief),
                max_steps=services.settings.max_tool_steps,
                usage=usage,
            )
            usage = usage.merged(result.usage)
            note = result.output.to_note(subquestion.question)
            if note.claims or result.output.sources:
                notes.append(note)
            sources.update({source.source_id: source for source in result.output.sources})
            errors.extend(result.errors)
            events.extend(result.trace)
            events.append(
                trace(
                    "researcher:worker",
                    "completed",
                    subquestion=subquestion.question,
                    claims=len(note.claims),
                    sources=len(result.output.sources),
                    tokens=result.usage.total_tokens,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one failed subquestion is recoverable
            errors.append(f"b1 researcher: {type(exc).__name__}: {exc}")
            events.append(
                trace("researcher:worker", "failed", error=f"{type(exc).__name__}: {exc}")
            )

    state: ResearchState = {
        "brief": brief,
        "notes": notes,
        "sources": sources,
        "analysis": None,
        "critique": None,
        "errors": errors,
        "usage": usage,
    }
    try:
        _check_budget(services, usage)
        draft, metadata = services.llm.invoke_structured(
            ReportDraft,
            messages(
                "writer",
                json_payload(
                    {
                        "question": brief.question,
                        "language": brief.language,
                        "analysis": None,
                        "notes": compact_notes(notes, summary_chars=300, max_gaps=4),
                        "sources": compact_sources(sources.values(), snippet_chars=120),
                        "critique": None,
                    }
                ),
            ),
        )
        delta = usage_from_metadata(metadata)
        usage = usage.merged(delta)
        report = _validate_report(build_final_report(state, draft, usage=usage))
        status = "done"
        events.append(
            trace(
                "writer",
                "report_created",
                claims=len(report.claims),
                sources=len(report.sources),
                fallback=False,
                model=metadata.model,
                tokens=delta.total_tokens,
                llm_calls=delta.llm_calls,
            )
        )
    except BudgetExceeded as exc:
        errors.append(str(exc))
        report = _validate_report(
            build_final_report(state, fallback_draft(state), usage=usage)
        )
        status = "done"
        events.append(trace("writer", "budget_exhausted", fallback=True, error=str(exc)))
    except Exception as exc:  # noqa: BLE001 - always return a report
        errors.append(f"b1 writer: {type(exc).__name__}: {exc}")
        report = _validate_report(
            build_final_report(state, fallback_draft(state), usage=usage)
        )
        status = "done"
        events.append(trace("writer", "llm_error", fallback=True, error=str(exc)))

    return SystemRun(
        system="b1",
        report=report,
        usage=usage,
        trace=events,
        errors=errors,
        status=status,
        duration_s=round(time.perf_counter() - started, 3),
    )


def run_b2(
    services: AgentServices,
    question: str,
    *,
    run_id: str,
    graph: Any | None = None,
) -> SystemRun:
    """Run the full supervisor/critic/writer graph."""
    started = time.perf_counter()
    try:
        graph = graph or build_graph(services)
        state = run_research(
            graph,
            ResearchBrief(question=question, language="es"),
            run_id=run_id,
            max_concurrency=services.settings.max_workers,
        )
        report = state.get("report")
        return SystemRun(
            system="b2",
            report=report,
            usage=state.get("usage", Usage()),
            trace=list(state.get("trace", [])),
            errors=list(state.get("errors", [])),
            status=state.get("status", "done" if report is not None else "failed"),
            duration_s=round(time.perf_counter() - started, 3),
        )
    except Exception as exc:  # noqa: BLE001 - one failed run must not stop the evaluation
        return SystemRun(
            system="b2",
            report=None,
            errors=[f"b2: {type(exc).__name__}: {exc}"],
            status="failed",
            duration_s=round(time.perf_counter() - started, 3),
        )


def run_system(
    system: SystemName,
    services: AgentServices,
    question: str,
    *,
    run_id: str,
    graph: Any | None = None,
) -> SystemRun:
    """Dispatch to the selected baseline."""
    if system == "b0":
        return run_b0(services, question, run_id=run_id)
    if system == "b1":
        return run_b1(services, question, run_id=run_id)
    return run_b2(services, question, run_id=run_id, graph=graph)
