from pathlib import Path

from scripts.build_demo_corpus import build_demo_corpus

from src.chunk import build_chunks
from src.config import Settings
from src.evaluate import load_questions
from src.ingest import ingest
from src.manifest import build_document_info, iter_pdf_paths
from src.parse import parse_pdf


def test_demo_corpus_generates_parseable_pdfs(tmp_path: Path) -> None:
    paths = build_demo_corpus(
        Path("demo/documents.json"),
        tmp_path,
        clean=True,
    )

    assert len(paths) == 6
    assert len(iter_pdf_paths(tmp_path)) == 6

    documents = [build_document_info(path, tmp_path) for path in paths]
    datapoints = next(
        document for document in documents if document.title == "NexaBus Datapoint Types"
    )
    path = next(
        path
        for path in paths
        if path.relative_to(tmp_path).as_posix() == datapoints.path
    )
    parsed = parse_pdf(path, datapoints)
    bundle = build_chunks(parsed)

    assert parsed.tables
    assert any(chunk.content_type == "table" for chunk in bundle.chunks)
    assert any(record.identifier == "1.001" for record in bundle.entities)

    generated_ids = {document.doc_id for document in documents}
    questions = load_questions(Path("demo/questions.jsonl"))
    assert all(
        set(question.relevant_doc_ids) <= generated_ids for question in questions
    )


def test_demo_corpus_can_be_ingested_with_hashing_backend(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    build_demo_corpus(Path("demo/documents.json"), corpus, clean=True)
    settings = Settings(
        corpus_dir=corpus,
        artifacts_dir=tmp_path / "artifacts",
        embedding_backend="hashing",
        embedding_dimension=64,
        use_reranker=False,
    )

    summary = ingest(settings, rebuild=True)

    assert summary["pdfs"] == 6
    assert summary["pages"] == 6
    assert summary["chunks"] == 12
    assert summary["tables"] == 6
    assert settings.chunks_path.exists()
    assert settings.manifest_path.exists()


def test_demo_corpus_has_no_knx_claims_in_the_questions() -> None:
    questions = Path("demo/questions.jsonl").read_text(encoding="utf-8").lower()
    assert "nexabus" in questions
    assert "the knx standard" not in questions
