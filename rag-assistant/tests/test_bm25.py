from src.bm25 import BM25Index
from src.text import tokenize


def test_bm25_ranks_matching_document_first() -> None:
    documents = [
        tokenize("DPT 1.001 is a one-bit switching datapoint type."),
        tokenize("The certification procedure includes laboratory testing."),
        tokenize("Group addresses connect group objects in KNX."),
    ]
    index = BM25Index()
    index.fit(documents)
    ranked = index.top_n(tokenize("datapoint type DPT 1.001"), n=3)
    assert ranked
    assert ranked[0][0] == 0


def test_bm25_returns_empty_without_matches() -> None:
    index = BM25Index()
    index.fit([tokenize("lighting actuator")])
    assert index.top_n(tokenize("certification"), n=1) == []
