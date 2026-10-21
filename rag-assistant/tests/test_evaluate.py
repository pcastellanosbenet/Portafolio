from src.evaluate import EvalQuestion, evaluate
from src.retrieve import Retriever


def test_retrieval_metrics_for_known_document(retriever: Retriever) -> None:
    question = EvalQuestion(
        id="q1",
        question="What is DPT 1.001?",
        relevant_doc_ids=["doc-dpt"],
        relevant_pages=[21],
    )
    report = evaluate(retriever, [question], k=3)
    assert report["questions"] == 1
    assert report["overall"]["recall_at_k"] == 1.0
    assert report["overall"]["hit_at_k"] == 1.0
    assert report["overall"]["mrr"] == 1.0
    assert report["overall"]["page_hit_at_k"] == 1.0
    assert report["by_type"]["general"]["recall_at_k"] == 1.0


def test_page_hit_is_omitted_without_reference_pages(retriever: Retriever) -> None:
    question = EvalQuestion(
        id="q2",
        question="What is DPT 1.001?",
        relevant_doc_ids=["doc-dpt"],
    )
    report = evaluate(retriever, [question], k=3)

    assert "page_hit_at_k" not in report["overall"]
    assert "page_hit_at_k" not in report["details"][0]
