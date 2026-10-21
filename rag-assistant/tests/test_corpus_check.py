import json
from pathlib import Path

import pymupdf
from scripts.check_corpus import check_corpus, load_expected_documents

from src.manifest import build_document_info


def _write_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_check_corpus_accepts_matching_document(tmp_path: Path) -> None:
    pdf = tmp_path / "03 Volume 3" / "03_07_02 Datapoint Types v02.02.01 AS.pdf"
    _write_pdf(pdf, "Synthetic corpus validation fixture.")
    expected = build_document_info(pdf, tmp_path)

    result = check_corpus(tmp_path, [expected])

    assert result.ok
    assert result.checked == 1
    assert result.expected_pdfs == 1
    assert result.available_pdfs == 1


def test_check_corpus_reports_missing_file(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, "Synthetic corpus validation fixture.")
    expected = build_document_info(pdf, tmp_path)
    pdf.unlink()

    result = check_corpus(tmp_path, [expected])

    assert not result.ok
    assert result.missing == [expected.path]
    assert result.checked == 0


def test_check_corpus_reports_hash_mismatch(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, "Synthetic corpus validation fixture.")
    expected = build_document_info(pdf, tmp_path)
    _write_pdf(pdf, "A different PDF with different bytes.")

    result = check_corpus(tmp_path, [expected])

    assert not result.ok
    assert result.hash_mismatches
    assert result.hash_mismatches[0]["path"] == expected.path


def test_published_corpus_manifest_has_only_metadata() -> None:
    manifest_path = Path("docs/corpus_manifest.json")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = payload["documents"]

    assert payload["edition"] == "The KNX Standard v3.0.0"
    assert payload["pdfs"] == 25
    assert payload["pages"] == 2111
    assert len(documents) == 25
    assert sum(document["pages"] for document in documents) == 2111
    assert all("text" not in document for document in documents)
    assert all("chunks" not in document for document in documents)


def test_load_expected_documents_supports_json_object(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    _write_pdf(pdf, "Synthetic corpus validation fixture.")
    expected = build_document_info(pdf, tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"documents": [expected.to_dict()]}),
        encoding="utf-8",
    )

    loaded = load_expected_documents(manifest)

    assert loaded == [expected]
