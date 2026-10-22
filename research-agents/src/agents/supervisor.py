"""Supervisor node and deterministic routing guards."""

from __future__ import annotations

import time

from langgraph.graph import END
from langgraph.types import Command

from src.agents.base import AgentServices, json_payload
from src.budget import usage_from_metadata
from src.models import Route, RouteName, Status, Usage
from src.prompts import messages
from src.state import ResearchState
from src.trace import trace

_STATUS_BY_ROUTE: dict[RouteName, Status] = {
    "planner": "planning",
    "researcher": "researching",
    "analyst": "analyzing",
    "critic": "reviewing",
    "writer": "writing",
    "finish": "done",
}


def allowed_routes(state: ResearchState, services: AgentServices) -> list[RouteName]:
    """Return the routes that make sense for the current state."""
    if state.get("report") is not None:
        return ["finish"]
    if state.get("plan") is None:
        return ["planner"]
    if not state.get("notes"):
        if services.budget.can_research(state):
            return ["researcher"]
        return ["writer"]
    if state.get("analysis") is None:
        return ["analyst"]
    if state.get("critique") is None:
        return ["critic"]
    if state["critique"].verdict == "revise" and services.budget.can_research(state):
        return ["researcher", "writer"]
    return ["writer"]


def _route_payload(state: ResearchState, allowed: list[RouteName], max_rounds: int) -> str:
    critique = state.get("critique")
    return json_payload(
        {
            "question": state["brief"].question,
            "has_plan": state.get("plan") is not None,
            "notes": len(state.get("notes", [])),
            "sources": len(state.get("sources", {})),
            "analysis": state.get("analysis") is not None,
            "critique": critique.model_dump(mode="json") if critique else None,
            "round": state.get("round", 0),
            "max_rounds": max_rounds,
            "allowed_routes": allowed,
            "instruction": "Choose exactly one of allowed_routes.",
        }
    )


def make_supervisor(services: AgentServices):
    def supervisor(state: ResearchState) -> Command:
        if state.get("report") is not None:
            return Command(
                goto=END,
                update={
                    "route": Route(next="finish", reason="Report exists."),
                    "status": "done",
                    "trace": [trace("supervisor", "run_finished")],
                },
            )

        allowed = allowed_routes(state, services)
        route: Route
        usage = Usage()
        errors: list[str] = []
        trace_data: dict[str, object] = {"allowed": allowed}

        if len(allowed) > 1:
            started = time.perf_counter()
            try:
                services.budget.check_llm(state)
                route, metadata = services.llm.invoke_structured(
                    Route,
                    messages(
                        "supervisor",
                        _route_payload(state, allowed, services.settings.max_rounds),
                    ),
                    fast=True,
                )
                usage = usage_from_metadata(metadata, latency_s=time.perf_counter() - started)
                trace_data["model"] = metadata.model
                if route.next not in allowed:
                    errors.append(
                        f"supervisor: invalid route {route.next!r}; using {allowed[0]!r}"
                    )
                    route = Route(
                        next=allowed[0],
                        reason="Deterministic fallback after an invalid route.",
                    )
            except Exception as exc:  # noqa: BLE001 - the graph must keep moving
                errors.append(f"supervisor: {type(exc).__name__}: {exc}")
                route = Route(
                    next=allowed[0],
                    reason="Deterministic fallback after a routing error.",
                )
        else:
            route = Route(next=allowed[0], reason="Only one valid route for this state.")
            trace_data["deterministic"] = True

        update: dict[str, object] = {
            "route": route,
            "status": _STATUS_BY_ROUTE[route.next],
            "usage": usage,
            "trace": [
                trace(
                    "supervisor",
                    "route_selected",
                    next=route.next,
                    reason=route.reason,
                    **trace_data,
                )
            ],
        }
        if errors:
            update["errors"] = errors
        if route.next == "researcher" and state.get("critique") is not None:
            update["analysis"] = None
            update["critique"] = None

        return Command(goto=END if route.next == "finish" else route.next, update=update)

    return supervisor
