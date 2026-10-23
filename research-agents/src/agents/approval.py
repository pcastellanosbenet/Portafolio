"""Human-in-the-loop approval gate before the report writer."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END
from langgraph.types import Command, interrupt

from src.agents.base import AgentServices, compact_notes, compact_sources
from src.state import ResearchState
from src.trace import trace


def normalize_hitl_decision(value: Any) -> tuple[bool, str]:
    """Accept a boolean, a short string or a JSON-like decision object."""
    feedback = ""
    if isinstance(value, dict):
        approved = bool(value.get("approved", value.get("approve", False)))
        feedback = str(value.get("feedback") or value.get("reason") or "").strip()
        return approved, feedback[:2_000]
    if isinstance(value, bool):
        return value, ""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"approve", "approved", "yes", "y", "ok", "true"}:
            return True, ""
        return False, value.strip()[:2_000]
    return False, ""


def _approval_payload(state: ResearchState) -> dict[str, Any]:
    analysis = state.get("analysis")
    critique = state.get("critique")
    return {
        "question": state["brief"].question,
        "analysis_summary": analysis.summary if analysis else "",
        "critique": critique.model_dump(mode="json") if critique else None,
        "notes": compact_notes(state.get("notes", [])),
        "sources": compact_sources(state.get("sources", {}).values(), snippet_chars=160),
        "instructions": (
            "Resume with {'approved': true} to write the report, or "
            "{'approved': false, 'feedback': '...'} to stop the run."
        ),
    }


def make_approval(services: AgentServices):
    """Pause before the writer and resume with the human decision."""

    def approval(state: ResearchState) -> Command:
        raw = interrupt(_approval_payload(state))
        approved, feedback = normalize_hitl_decision(raw)
        decision = {
            "approved": approved,
            "feedback": feedback,
        }
        if approved:
            return Command(
                goto="writer",
                update={
                    "hitl": decision,
                    "status": "writing",
                    "trace": [
                        trace(
                            "approval",
                            "hitl_decision",
                            approved=True,
                            feedback=feedback,
                        )
                    ],
                },
            )

        message = "Human reviewer rejected the draft before writing."
        if feedback:
            message = f"{message} Feedback: {feedback}"
        return Command(
            goto=END,
            update={
                "hitl": decision,
                "status": "failed",
                "errors": [message],
                "trace": [
                    trace(
                        "approval",
                        "hitl_decision",
                        approved=False,
                        feedback=feedback,
                    )
                ],
            },
        )

    return approval
