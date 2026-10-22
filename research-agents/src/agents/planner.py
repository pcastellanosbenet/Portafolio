"""Planner node."""

from __future__ import annotations

import time

from src.agents.base import AgentServices, json_payload
from src.budget import BudgetExceeded, usage_from_metadata
from src.models import ResearchBrief, ResearchPlan, SubQuestion
from src.prompts import messages
from src.state import ResearchState
from src.trace import trace


def fallback_plan(brief: ResearchBrief) -> ResearchPlan:
    """A safe plan when the planner cannot call a model."""
    return ResearchPlan(
        subquestions=[
            SubQuestion(
                question=brief.question,
                rationale="Use the original question as the only research task.",
            )
        ],
        search_strategy="Search the web, Wikipedia and arXiv for direct evidence.",
    )


def make_planner(services: AgentServices):
    def planner(state: ResearchState) -> dict[str, object]:
        brief = state["brief"]
        started = time.perf_counter()
        try:
            services.budget.check_llm(state)
            plan, metadata = services.llm.invoke_structured(
                ResearchPlan,
                messages("planner", json_payload(brief.model_dump(mode="json"))),
            )
            usage = usage_from_metadata(metadata, latency_s=time.perf_counter() - started)
            return {
                "plan": plan,
                "status": "planning",
                "usage": usage,
                "trace": [
                    trace(
                        "planner",
                        "plan_created",
                        subquestions=len(plan.subquestions),
                        model=metadata.model,
                        prompt_version="0.1.0",
                    )
                ],
            }
        except BudgetExceeded as exc:
            return {
                "plan": fallback_plan(brief),
                "status": "planning",
                "errors": [str(exc)],
                "trace": [trace("planner", "budget_exhausted", fallback=True)],
            }
        except Exception as exc:  # noqa: BLE001 - preserve the run with a safe plan
            return {
                "plan": fallback_plan(brief),
                "status": "planning",
                "errors": [f"planner: {type(exc).__name__}: {exc}"],
                "trace": [trace("planner", "llm_error", fallback=True)],
            }

    return planner
