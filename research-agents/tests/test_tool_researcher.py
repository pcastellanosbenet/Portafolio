"""Tests for the tool-using researcher subgraph."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import BaseModel

from src.agents.tool_researcher import (
    ToolResearcherBackend,
    messages_for_finalization,
    parse_research_answer,
)
from src.budget import BudgetGuard
from src.config import Settings
from src.llm import InvocationMetadata
from src.models import (
    Claim,
    ResearchBrief,
    ResearchOutput,
    ResearchTask,
    Source,
    SubQuestion,
    Usage,
)

VALID_ID = "src_0123456789ab"


class ScriptedChatModel(BaseChatModel):
    responses: list[AIMessage]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        del tools, kwargs
        return self


class ToolFakeLLM:
    def __init__(self, responses: list[AIMessage], output: ResearchOutput) -> None:
        self._responses = responses
        self._output = output
        self.structured_calls = 0
        self.text_calls = 0

    def chat_model(self, *, fast: bool = False) -> ScriptedChatModel:
        del fast
        return ScriptedChatModel(responses=list(self._responses))

    def invoke_text(
        self,
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> AIMessage:
        del messages, fast
        self.text_calls += 1
        answer = {
            "summary": self._output.summary,
            "claims": [claim.model_dump(mode="json") for claim in self._output.claims],
            "gaps": self._output.gaps,
            "confidence": self._output.confidence,
        }
        return AIMessage(
            content=json.dumps(answer),
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            response_metadata={"model_name": "fake-tool-model", "provider": "fake"},
        )

    def invoke_with_tools(
        self,
        messages: Sequence[BaseMessage],
        tools: Sequence[Any],
        *,
        fast: bool = False,
    ) -> AIMessage:
        del messages, tools, fast
        return self._responses.pop(0)

    def invoke_structured[T: BaseModel](
        self,
        schema: type[T],
        messages: Sequence[BaseMessage],
        *,
        fast: bool = False,
    ) -> tuple[T, InvocationMetadata]:
        del messages, fast
        self.structured_calls += 1
        assert schema is ResearchOutput
        return self._output, InvocationMetadata(  # type: ignore[return-value]
            provider="fake",
            model="fake-tool-model",
            method="json_schema",
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


@tool
def search_web(query: str) -> str:
    """Return deterministic test results."""
    del query
    return json.dumps(
        [
            {
                "source_id": VALID_ID,
                "title": "Test source",
                "url": "https://example.com/test",
                "snippet": "A test snippet.",
                "kind": "web",
            }
        ]
    )


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_model="test",
        groq_api_key="gsk-test",
        max_llm_calls=10,
        max_rounds=2,
    )


def make_task() -> ResearchTask:
    return ResearchTask(
        subquestion=SubQuestion(question="What is tested?"),
        brief=ResearchBrief(question="What is tested?"),
    )


def make_output() -> ResearchOutput:
    return ResearchOutput(
        summary="A test result.",
        claims=[Claim(claim_id="c1", text="Test claim", source_ids=[VALID_ID])],
        sources=[Source(source_id=VALID_ID, url="https://example.com/test", title="Test source")],
        confidence="high",
    )


def test_tool_researcher_calls_tool_and_returns_sanitized_output() -> None:
    first = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_web",
                "args": {"query": "test"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    llm = ToolFakeLLM([first, AIMessage(content="I have enough evidence.")], make_output())
    backend = ToolResearcherBackend(
        llm,  # type: ignore[arg-type]
        [search_web],
        budget=BudgetGuard(make_settings()),
        max_steps=2,
    )

    result = backend.research(make_task(), max_steps=2, usage=Usage())

    assert result.output.claims[0].source_ids == [VALID_ID]
    assert result.output.sources[0].source_id == VALID_ID
    assert result.usage.llm_calls == 3
    assert result.usage.search_calls == 1
    assert llm.text_calls == 1


def test_one_step_researcher_still_executes_its_tool_call() -> None:
    first = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_web",
                "args": {"query": "test"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    llm = ToolFakeLLM([first], make_output())
    backend = ToolResearcherBackend(
        llm,  # type: ignore[arg-type]
        [search_web],
        budget=BudgetGuard(make_settings()),
        max_steps=1,
    )

    result = backend.research(make_task(), max_steps=1, usage=Usage())

    assert result.usage.llm_calls == 2
    assert result.usage.search_calls == 1
    assert result.output.sources[0].source_id == VALID_ID
    assert llm.text_calls == 1


def test_tool_researcher_respects_exhausted_budget() -> None:
    llm = ToolFakeLLM([], make_output())
    backend = ToolResearcherBackend(
        llm,  # type: ignore[arg-type]
        [search_web],
        budget=BudgetGuard(make_settings()),
        max_steps=2,
    )

    result = backend.research(
        make_task(),
        max_steps=2,
        usage=Usage(llm_calls=10),
    )

    assert result.output.confidence == "low"
    assert result.usage.llm_calls == 0
    assert any("Budget" in gap for gap in result.output.gaps)


def test_finalization_context_highlights_source_ids() -> None:
    tool_message = ToolMessage(
        content=json.dumps(
            [
                {
                    "source_id": VALID_ID,
                    "title": "Test source",
                    "url": "https://example.com/test",
                    "snippet": "A test snippet.",
                    "kind": "web",
                }
            ]
        ),
        tool_call_id="call-1",
        name="search_web",
    )
    messages = messages_for_finalization(
        {
            "task": make_task(),
            "messages": [tool_message],
        }
    )
    evidence = str(messages[1].content)
    assert f"[{VALID_ID}]" in evidence
    assert "URL: https://example.com/test" in evidence
    assert "source_id" not in evidence


def test_parse_research_answer_accepts_tool_wrapper_and_fences() -> None:
    payload = {
        "summary": "Summary",
        "claims": [{"claim_id": "c1", "text": "Claim", "source_ids": [VALID_ID]}],
        "gaps": [],
        "confidence": "high",
    }
    wrapped = json.dumps({"name": "json", "arguments": json.dumps(payload)})
    assert parse_research_answer(wrapped).claims[0].source_ids == [VALID_ID]
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    assert parse_research_answer(fenced).summary == "Summary"
