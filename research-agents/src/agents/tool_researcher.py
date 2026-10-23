"""Tool-using researcher built as a small ReAct subgraph."""

from __future__ import annotations

import json
import operator
import time
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from src.agents.base import ResearchResult, ToolLLM, json_payload
from src.budget import BudgetExceeded, usage_from_ai_message
from src.citations import collect_sources_from_messages, sanitize_research_output
from src.models import ResearchAnswer, ResearchOutput, ResearchTask, Usage
from src.prompts import RESEARCHER, TOOL_FINALIZER
from src.state import merge_usage
from src.trace import TraceEvent, trace


class ToolResearchState(TypedDict, total=False):
    task: ResearchTask
    messages: Annotated[list[AnyMessage], add_messages]
    steps: int
    max_steps: int
    usage: Annotated[Usage, merge_usage]
    initial_usage: Usage
    output: ResearchOutput | None
    budget_exhausted: bool
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[TraceEvent], operator.add]


def _format_tool_evidence(content: Any) -> str:
    """Render tool JSON as a compact evidence list with prominent source ids."""
    payload = content
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return content
    if isinstance(payload, list):
        chunks = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            source_id = item.get("source_id")
            if not source_id:
                continue
            snippet = str(item.get("snippet") or item.get("text") or "")
            chunks.append(
                f"[{source_id}] {item.get('title', '')}\n"
                f"{snippet[:1_200]}\n"
                f"URL: {item.get('url', '')}"
            )
        if chunks:
            return "\n\n".join(chunks)
    if isinstance(payload, dict):
        source_id = payload.get("source_id")
        if source_id:
            return (
                f"[{source_id}] {payload.get('title', '')}\n"
                f"{str(payload.get('text') or payload.get('snippet') or '')[:3_000]}\n"
                f"URL: {payload.get('url', '')}"
            )
        if payload.get("error"):
            return f"Tool error: {payload['error']}"
    return str(content)


def messages_for_finalization(state: ToolResearchState) -> list[AnyMessage]:
    """Build a clean context without unresolved tool calls.

    Groq validates the whole message history of structured-output requests. If
    the step limit stops the loop after the model asked for a tool, keeping that
    pending tool call makes the final request fail with ``tool_use_failed``.
    Tool results are serialized as a compact evidence list instead.
    """
    task = state.get("task")
    parts = [
        json_payload({"task": task.model_dump(mode="json")}) if task is not None else "",
        "Evidence collected by executed tools. Cite only the IDs shown in brackets:",
    ]
    tool_count = 0
    remaining_chars = 8_000
    truncated = False
    for message in state.get("messages", []):
        if isinstance(message, ToolMessage):
            if remaining_chars <= 0:
                break
            content = _format_tool_evidence(message.content)
            if len(content) > min(4_000, remaining_chars):
                content = content[: min(4_000, remaining_chars)] + "… [truncated]"
                truncated = True
            parts.append(f"- {message.name or 'tool'}:\n{content}")
            remaining_chars -= len(content)
            tool_count += 1
        elif isinstance(message, AIMessage) and message.content and not message.tool_calls:
            parts.append(f"- assistant note: {message.content}")
    if tool_count == 0:
        parts.append("No tool results were collected.")
    elif truncated:
        parts.append("Some tool output was truncated to fit the context window.")
    return [
        SystemMessage(content=TOOL_FINALIZER),
        HumanMessage(content="\n\n".join(part for part in parts if part)),
        HumanMessage(
            content=(
                "Return ONLY one JSON object with this shape:\n"
                '{"summary": "...", "claims": [{"claim_id": "c1", "text": "...", '
                '"source_ids": ["src_..."]}], "gaps": ["..."], '
                '"confidence": "low|medium|high"}\n'
                "Use only source_id values that appeared in the tool results above. "
                "Keep the summary under 100 words and at most 4 atomic claims. "
                "Do not include source metadata, URLs, or Markdown fences. If evidence "
                "is insufficient, leave claims empty and explain the gaps."
            )
        ),
    ]


def parse_research_answer(text: str) -> ResearchAnswer:
    """Parse a compact JSON answer, tolerating fences and a tool-call wrapper."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("The researcher did not return a JSON object.")
    data, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    if not isinstance(data, dict):
        raise ValueError("The researcher returned JSON that is not an object.")
    if "arguments" in data and isinstance(data["arguments"], (dict, str)):
        arguments = data["arguments"]
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if isinstance(arguments, dict):
            data = arguments
    return ResearchAnswer.model_validate(data)


class ToolResearcherBackend:
    """ReAct researcher with a hard step limit and deterministic fallbacks."""

    def __init__(
        self,
        llm: ToolLLM,
        tools: list[BaseTool],
        *,
        budget,
        max_steps: int = 3,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.budget = budget
        self.max_steps = max_steps
        self._graph = self._build_graph()

    def research(
        self,
        task: ResearchTask,
        *,
        max_steps: int = 3,
        usage: Usage | None = None,
    ) -> ResearchResult:
        initial_usage = usage or Usage()
        state: ToolResearchState = {
            "task": task,
            "messages": [
                SystemMessage(content=RESEARCHER),
                HumanMessage(
                    content=json_payload(
                        {
                            "task": task.model_dump(mode="json"),
                            "max_steps": min(max_steps, self.max_steps),
                        }
                    )
                ),
            ],
            "steps": 0,
            "max_steps": min(max_steps, self.max_steps),
            "usage": Usage(),
            "initial_usage": initial_usage,
            "output": None,
            "budget_exhausted": False,
            "errors": [],
            "trace": [],
        }
        try:
            result = self._graph.invoke(
                state,
                config={"recursion_limit": min(max_steps, self.max_steps) * 4 + 10},
            )
        except Exception as exc:  # noqa: BLE001 - the graph handles one failed subquestion
            return ResearchResult(
                output=ResearchOutput(
                    summary="The researcher could not complete this subquestion.",
                    gaps=[f"{type(exc).__name__}: {exc}"],
                    confidence="low",
                ),
                usage=Usage(),
                errors=[f"researcher: {type(exc).__name__}: {exc}"],
                trace=[
                    trace(
                        "researcher",
                        "failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                ],
            )

        output = result.get("output") or ResearchOutput(
            summary="No structured research output was produced.",
            gaps=["The researcher did not return an output."],
            confidence="low",
        )
        total_usage = result.get("usage", Usage())
        tool_messages = [
            message for message in result.get("messages", []) if isinstance(message, ToolMessage)
        ]
        tools_used = sorted(
            {
                str(getattr(message, "name", "") or "")
                for message in tool_messages
                if getattr(message, "name", "")
            }
        )
        search_calls = sum(
            1
            for message in tool_messages
            if getattr(message, "name", "") in {"search_web", "search_arxiv", "search_wikipedia"}
        )
        if search_calls:
            total_usage = total_usage.model_copy(
                update={"search_calls": total_usage.search_calls + search_calls}
            )
        return ResearchResult(
            output=output,
            usage=total_usage,
            tools_used=tools_used,
            trace=list(result.get("trace", [])),
            errors=list(result.get("errors", [])),
        )

    def _build_graph(self):
        builder = StateGraph(ToolResearchState)
        builder.add_node("agent", self._agent)
        if self.tools:
            builder.add_node("tools", ToolNode(self.tools, handle_tool_errors=True))
        builder.add_node("finalize", self._finalize)
        builder.add_edge(START, "agent")
        if self.tools:
            builder.add_conditional_edges(
                "agent",
                self._should_continue,
                {"tools": "tools", "finalize": "finalize"},
            )
            builder.add_conditional_edges(
                "tools",
                self._after_tools,
                {"agent": "agent", "finalize": "finalize"},
            )
        else:
            builder.add_edge("agent", "finalize")
        builder.add_edge("finalize", END)
        return builder.compile()

    def _agent(self, state: ToolResearchState) -> dict[str, object]:
        initial = state.get("initial_usage", Usage())
        current = state.get("usage", Usage())
        try:
            self.budget.check_llm_usage(initial.merged(current))
        except BudgetExceeded as exc:
            return {
                "budget_exhausted": True,
                "steps": state.get("max_steps", self.max_steps),
                "errors": [str(exc)],
                "trace": [
                    trace(
                        "researcher:agent",
                        "budget_exhausted",
                        error=str(exc),
                    )
                ],
            }

        started = time.perf_counter()
        response = self.llm.invoke_with_tools(state["messages"], self.tools, fast=True)
        if not isinstance(response, AIMessage):
            raise TypeError(f"Expected AIMessage from tool call, got {type(response)!r}")
        delta = usage_from_ai_message(response, latency_s=time.perf_counter() - started)
        model_name = str(response.response_metadata.get("model_name") or "tool-model")
        tool_names = [
            str(call.get("name", ""))
            for call in response.tool_calls
            if call.get("name")
        ]
        return {
            "messages": [response],
            "steps": state.get("steps", 0) + 1,
            "usage": delta,
            "trace": [
                trace(
                    "researcher:agent",
                    "tool_call" if response.tool_calls else "answer",
                    step=state.get("steps", 0) + 1,
                    tool_calls=len(response.tool_calls),
                    tools=tool_names,
                    model=model_name,
                    tokens=delta.total_tokens,
                    latency_s=delta.latency_s,
                    llm_calls=delta.llm_calls,
                )
            ],
        }

    def _should_continue(self, state: ToolResearchState) -> str:
        if state.get("budget_exhausted"):
            return "finalize"
        messages = state.get("messages", [])
        if not messages:
            return "finalize"
        last = messages[-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "finalize"

    def _after_tools(self, state: ToolResearchState) -> str:
        if state.get("budget_exhausted"):
            return "finalize"
        if state.get("steps", 0) >= state.get("max_steps", self.max_steps):
            return "finalize"
        return "agent"

    def _finalize(self, state: ToolResearchState) -> dict[str, object]:
        if state.get("budget_exhausted"):
            return {
                "output": ResearchOutput(
                    summary="The LLM budget was exhausted before this subquestion was finished.",
                    gaps=["Budget exhausted during tool use."],
                    confidence="low",
                )
            }

        initial = state.get("initial_usage", Usage())
        current = state.get("usage", Usage())
        try:
            self.budget.check_llm_usage(initial.merged(current))
        except BudgetExceeded as exc:
            return {
                "output": ResearchOutput(
                    summary="The LLM budget was exhausted before the final answer.",
                    gaps=[str(exc)],
                    confidence="low",
                )
            }

        started = time.perf_counter()
        try:
            response = self.llm.invoke_text(
                messages_for_finalization(state),
                fast=True,
            )
            answer = parse_research_answer(str(response.content))
            output = ResearchOutput(
                summary=answer.summary,
                claims=answer.claims,
                sources=[],
                gaps=answer.gaps,
                confidence=answer.confidence,
            )
        except Exception as exc:  # noqa: BLE001 - keep the graph alive with a gap
            return {
                "output": ResearchOutput(
                    summary="The researcher could not produce a structured answer.",
                    gaps=[f"{type(exc).__name__}: {exc}"],
                    confidence="low",
                ),
                "errors": [f"researcher: {type(exc).__name__}: {exc}"],
                "trace": [
                    trace(
                        "researcher:finalize",
                        "llm_error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                ],
            }

        output = sanitize_research_output(
            output,
            collect_sources_from_messages(state["messages"]),
        )
        delta = usage_from_ai_message(response, latency_s=time.perf_counter() - started)
        model_name = str(response.response_metadata.get("model_name") or "tool-model")
        tools_used = sorted(
            {
                str(getattr(message, "name", "") or "")
                for message in state.get("messages", [])
                if isinstance(message, ToolMessage) and getattr(message, "name", "")
            }
        )
        return {
            "output": output,
            "usage": delta,
            "trace": [
                trace(
                    "researcher:finalize",
                    "output_created",
                    claims=len(output.claims),
                    sources=len(output.sources),
                    model=model_name,
                    tools=tools_used,
                    tokens=delta.total_tokens,
                    latency_s=delta.latency_s,
                    llm_calls=delta.llm_calls,
                )
            ],
        }
