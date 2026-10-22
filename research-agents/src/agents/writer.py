"""Writer node and deterministic fallback report."""

from __future__ import annotations

import time

from src.agents.base import AgentServices, json_payload
from src.budget import BudgetExceeded, usage_from_metadata
from src.models import Claim, FinalReport, Note, ReportDraft, Source, Usage
from src.prompts import messages
from src.state import ResearchState
from src.trace import trace


def _dedupe_claims(notes: list[Note]) -> list[Claim]:
    merged: dict[str, Claim] = {}
    for note in notes:
        for claim in note.claims:
            current = merged.get(claim.claim_id)
            if current is None:
                merged[claim.claim_id] = claim
            else:
                source_ids = sorted(set(current.source_ids) | set(claim.source_ids))
                merged[claim.claim_id] = current.model_copy(update={"source_ids": source_ids})
    return list(merged.values())


def _limitations(state: ResearchState, draft: ReportDraft | None) -> list[str]:
    limitations: list[str] = []
    if draft is not None:
        limitations.extend(draft.limitations)
    critique = state.get("critique")
    if critique is not None:
        limitations.extend(critique.gaps)
        if critique.verdict == "revise":
            limitations.append(
                "The critic requested another research round; this report uses the evidence "
                "available when the budget or round limit was reached."
            )
    limitations.extend(state.get("errors", []))
    for note in state.get("notes", []):
        limitations.extend(note.gaps)
    if not state.get("notes"):
        limitations.append("No research notes were collected.")
    return list(dict.fromkeys(limitations))


def fallback_draft(state: ResearchState) -> ReportDraft:
    claims = _dedupe_claims(state.get("notes", []))
    if claims:
        lines = ["## Findings", ""]
        for claim in claims:
            citations = ", ".join(f"[{source_id}]" for source_id in claim.source_ids)
            lines.append(f"- {claim.text}" + (f" {citations}" if citations else ""))
    else:
        lines = [
            "## Findings",
            "",
            "The available evidence was insufficient to support a factual answer.",
        ]
    limitations = _limitations(state, None)
    if limitations:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {limitation}" for limitation in limitations)
    return ReportDraft(
        title=f"Research report: {state['brief'].question[:80]}",
        answer_markdown="\n".join(lines),
        confidence="low",
        limitations=limitations,
    )


def build_final_report(
    state: ResearchState,
    draft: ReportDraft,
    *,
    usage: Usage,
) -> FinalReport:
    claims = _dedupe_claims(state.get("notes", []))
    sources: list[Source] = sorted(
        state.get("sources", {}).values(),
        key=lambda source: source.source_id,
    )
    return FinalReport(
        title=draft.title,
        answer_markdown=draft.answer_markdown,
        claims=claims,
        sources=sources,
        confidence=draft.confidence,
        limitations=_limitations(state, draft),
        usage=usage,
    )


def make_writer(services: AgentServices):
    def writer(state: ResearchState) -> dict[str, object]:
        started = time.perf_counter()
        current_usage = state.get("usage", Usage())
        try:
            services.budget.check_llm(state)
            draft, metadata = services.llm.invoke_structured(
                ReportDraft,
                messages(
                    "writer",
                    json_payload(
                        {
                            "question": state["brief"].question,
                            "language": state["brief"].language,
                            "analysis": state.get("analysis"),
                            "notes": state.get("notes", []),
                            "sources": list(state.get("sources", {}).values()),
                            "critique": state.get("critique"),
                        }
                    ),
                ),
            )
            delta = usage_from_metadata(metadata, latency_s=time.perf_counter() - started)
            report = build_final_report(
                state,
                draft,
                usage=current_usage.merged(delta),
            )
            return {
                "report": report,
                "status": "writing",
                "usage": delta,
                "trace": [
                    trace(
                        "writer",
                        "report_created",
                        claims=len(report.claims),
                        sources=len(report.sources),
                        fallback=False,
                        model=metadata.model,
                    )
                ],
            }
        except BudgetExceeded as exc:
            draft = fallback_draft(state)
            report = build_final_report(state, draft, usage=current_usage)
            return {
                "report": report,
                "status": "writing",
                "errors": [str(exc)],
                "trace": [trace("writer", "budget_exhausted", fallback=True)],
            }
        except Exception as exc:  # noqa: BLE001 - always return a report
            draft = fallback_draft(state)
            report = build_final_report(state, draft, usage=current_usage)
            return {
                "report": report,
                "status": "writing",
                "errors": [f"writer: {type(exc).__name__}: {exc}"],
                "trace": [trace("writer", "llm_error", fallback=True)],
            }

    return writer
