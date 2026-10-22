"""LangGraph assembly for the research team."""

from __future__ import annotations

from typing import Any

from langgraph.graph import START, StateGraph

from src.agents.analyst import make_analyst
from src.agents.base import AgentServices
from src.agents.critic import make_critic
from src.agents.planner import make_planner
from src.agents.researcher import make_researcher
from src.agents.supervisor import make_supervisor
from src.agents.writer import make_writer
from src.models import ResearchBrief
from src.state import ResearchState, initial_state


def build_graph(services: AgentServices, *, checkpointer: Any | None = None):
    """Build and compile the research graph."""
    builder = StateGraph(ResearchState)
    builder.add_node("supervisor", make_supervisor(services))
    builder.add_node("planner", make_planner(services))
    builder.add_node("researcher", make_researcher(services))
    builder.add_node("analyst", make_analyst(services))
    builder.add_node("critic", make_critic(services))
    builder.add_node("writer", make_writer(services))

    builder.add_edge(START, "supervisor")
    for node in ("planner", "researcher", "analyst", "critic", "writer"):
        builder.add_edge(node, "supervisor")
    return builder.compile(checkpointer=checkpointer)


def run_research(
    graph: Any,
    brief: ResearchBrief,
    *,
    run_id: str | None = None,
    recursion_limit: int = 30,
    config: dict[str, Any] | None = None,
) -> ResearchState:
    """Invoke the graph with a fresh state and a hard recursion limit."""
    state = initial_state(brief, run_id=run_id)
    run_config: dict[str, Any] = {"recursion_limit": recursion_limit}
    if config:
        run_config.update(config)
    return graph.invoke(state, config=run_config)
