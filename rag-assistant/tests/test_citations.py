from src.citations import (
    build_citations,
    format_context,
    parse_answer,
    validate_citations,
)
from src.models import RetrievedChunk
from tests.conftest import make_chunk


def _results() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk=make_chunk("a", text="DPT 1.001 is a switching type."),
            score=0.9,
        ),
        RetrievedChunk(
            chunk=make_chunk("b", text="DPT 14.046 is a floating point type."),
            score=0.8,
        ),
    ]


def test_format_and_parse_json_answer() -> None:
    results = _results()
    context, source_map = format_context(results)
    assert "[S1]" in context
    payload = parse_answer(
        '{"answer": "DPT 1.001 switches [S1].", "citations": ["S1"], "abstained": false}',
        source_map,
    )
    valid, invalid = validate_citations(payload, source_map)
    assert valid == ["a"]
    assert invalid == []
    citations = build_citations(source_map, valid)
    assert citations[0].doc_id == "doc-dpt"
    assert citations[0].page_start == 10


def test_marker_fallback_without_json() -> None:
    results = _results()
    _, source_map = format_context(results)
    payload = parse_answer("DPT 1.001 switches [S1].", source_map)
    assert payload.citations == ["a"]
    assert "DPT 1.001" in payload.answer


def test_invalid_citation_is_detected() -> None:
    results = _results()
    _, source_map = format_context(results)
    payload = parse_answer(
        '{"answer": "Unknown [S9].", "citations": ["S9"], "abstained": false}',
        source_map,
    )
    valid, invalid = validate_citations(payload, source_map)
    assert valid == []
    assert "S9" in invalid
    assert "missing-citation" in invalid
