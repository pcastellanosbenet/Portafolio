from src.agent import KNXAgent
from src.answer import AnswerService
from src.llm import LLMError, MockLLM


def test_agent_uses_exact_identifier_lookup(agent: KNXAgent) -> None:
    answer = agent.run("What is DPT 1.001?")
    assert answer.answer
    assert answer.citations
    assert answer.citations[0].chunk_id == "dpt::1"
    assert any(step["step"] == "exact_lookup" for step in answer.trace)
    assert answer.used_llm is True


def test_agent_answers_procedure_question(agent: KNXAgent) -> None:
    answer = agent.run("What is the certification procedure?")
    assert answer.answer
    assert answer.citations
    assert any(step["step"] == "retrieve" for step in answer.trace)


class FailingLLM:
    def generate(self, system: str, user: str) -> str:
        raise LLMError("modelo no disponible")


def test_extractive_fallback_keeps_a_citation(retriever) -> None:
    service = AnswerService(FailingLLM())
    results = retriever.search("DPT 1.001", top_k=2)
    answer = service.answer("What is DPT 1.001?", results)
    assert answer.used_llm is False
    assert answer.citations
    assert "No he podido generar" in answer.answer


def test_no_evidence_abstains() -> None:
    service = AnswerService(MockLLM("{}"))
    answer = service.answer("What is not in the corpus?", [])
    assert answer.abstained is True
    assert answer.citations == []
