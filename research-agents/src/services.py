"""Runtime dependency assembly for CLI, API and tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from src.agents.base import AgentServices, ResearcherBackend, StructuredLLM
from src.agents.tool_researcher import ToolResearcherBackend
from src.budget import BudgetGuard
from src.cache import SQLiteCache
from src.config import Settings
from src.llm import LLMClient
from src.tavily_budget import TavilyBudget
from src.tools.registry import ToolRegistry, build_registry


def build_services(
    settings: Settings,
    *,
    llm: StructuredLLM | None = None,
    cache: SQLiteCache | None = None,
    tavily_budget: TavilyBudget | None = None,
    registry: ToolRegistry | None = None,
    researcher: ResearcherBackend | None = None,
    http_client: httpx.Client | None = None,
    ddg_search_fn: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> AgentServices:
    """Wire settings, cache, tools and the researcher backend."""
    settings.ensure_runtime_dirs()
    cache = cache or SQLiteCache(settings.db_path, default_ttl_s=settings.cache_ttl_s)
    tavily_budget = tavily_budget or TavilyBudget(
        settings.db_path,
        monthly_limit=settings.tavily_monthly_budget,
    )
    llm_client = llm or LLMClient(settings)
    registry = registry or build_registry(
        settings,
        cache=cache,
        tavily_budget=tavily_budget,
        http_client=http_client,
        ddg_search_fn=ddg_search_fn,
    )
    guard = BudgetGuard(settings)
    if researcher is None:
        if not hasattr(llm_client, "chat_model") or not hasattr(llm_client, "invoke_with_tools"):
            raise TypeError("A tool-capable LLM is required to build the researcher backend.")
        researcher = ToolResearcherBackend(
            llm_client,  # type: ignore[arg-type]
            registry.tools,
            budget=guard,
            max_steps=settings.max_tool_steps,
        )
    return AgentServices(
        llm=llm_client,
        researcher=researcher,
        settings=settings,
        budget=guard,
    )
