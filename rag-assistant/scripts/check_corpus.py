"""Validate a local, licensed KNX corpus against the published manifest.

The repository does not redistribute the KNX PDFs.  This utility lets a user
confirm that the copy they obtained is the edition used for the reported
evaluation, without uploading or copying the documents.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.manifest import build_document_info, iter_pdf_paths
from src.models import DocumentInfo

DEFAULT_MANIFEST = Path("docs/corpus_manifest.json")


@dataclass
class CorpusCheckResult:
    """Summary of a corpus validation run."""

    corpus_dir: str
    expected_pdfs: int
    available_pdfs: int
    checked: int = 0
    missing: list[str] = field(default_factory=list)
    page_mismatches: list[dict[str, object]] = field(default_factory=list)
    doc_id_mismatches: list[dict[str, object]] = field(default_factory=list)
    hash_mismatches: list[dict[str, object]] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.missing
            or self.page_mismatches
            or self.doc_id_mismatches
            or self.hash_mismatches
        )

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def load_expected_documents(path: Path) -> list[DocumentInfo]:
    """Load a JSON object or JSONL file containing document metadata."""
    if not path.exists():
        raise FileNotFoundError(f"No existe el manifiesto: {path}")

    if path.suffix.lower() == ".jsonl":
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = payload.get("documents", [])
        else:
            raise ValueError("El manifiesto debe ser un objeto, una lista o JSONL.")
    if not records:
        raise ValueError(f"El manifiesto no contiene documentos: {path}")
    return [DocumentInfo.from_dict(record) for record in records]


def check_corpus(
    corpus_dir: Path,
    expected: list[DocumentInfo],
    *,
    verify_hashes: bool = True,
    check_extra: bool = False,
) -> CorpusCheckResult:
    """Compare the local PDFs with the expected metadata.

    Missing files, page-count differences, doc-id differences and (optionally)
    SHA-256 differences are reported.  Extra PDFs are ignored by default because
    the published manifest covers the 25-document evaluation subset, not the
    complete 178-document corpus.
    """
    available = iter_pdf_paths(corpus_dir)
    available_paths = {path.relative_to(corpus_dir).as_posix() for path in available}
    expected_paths = {document.path for document in expected}
    result = CorpusCheckResult(
        corpus_dir=str(corpus_dir),
        expected_pdfs=len(expected),
        available_pdfs=len(available),
    )

    for document in expected:
        path = corpus_dir / document.path
        if not path.is_file():
            result.missing.append(document.path)
            continue

        actual = build_document_info(path, corpus_dir)
        result.checked += 1

        if actual.pages != document.pages:
            result.page_mismatches.append(
                {
                    "path": document.path,
                    "expected": document.pages,
                    "actual": actual.pages,
                }
            )
        if actual.doc_id != document.doc_id:
            result.doc_id_mismatches.append(
                {
                    "path": document.path,
                    "expected": document.doc_id,
                    "actual": actual.doc_id,
                }
            )
        if verify_hashes and actual.sha256 != document.sha256:
            result.hash_mismatches.append(
                {
                    "path": document.path,
                    "expected": document.sha256,
                    "actual": actual.sha256,
                }
            )

    if check_extra:
        result.extra = sorted(available_paths - expected_paths)

    return result


def _print_result(result: CorpusCheckResult, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Corpus: {result.corpus_dir}")
    print(f"PDFs esperados: {result.expected_pdfs}")
    print(f"PDFs encontrados en el corpus: {result.available_pdfs}")
    print(f"PDFs comprobados: {result.checked}")

    if result.missing:
        print("\nFaltan:")
        for path in result.missing:
            print(f"  - {path}")
    if result.page_mismatches:
        print("\nPáginas distintas:")
        for item in result.page_mismatches:
            print(
                f"  - {item['path']}: esperadas {item['expected']}, "
                f"encontradas {item['actual']}"
            )
    if result.doc_id_mismatches:
        print("\nDOC IDs distintos:")
        for item in result.doc_id_mismatches:
            print(
                f"  - {item['path']}: esperado {item['expected']}, "
                f"encontrado {item['actual']}"
            )
    if result.hash_mismatches:
        print("\nSHA-256 distintos:")
        for item in result.hash_mismatches:
            print(f"  - {item['path']}")
            print(f"    esperado: {item['expected']}")
            print(f"    actual:   {item['actual']}")
    if result.extra:
        print("\nPDFs extra (no están en el manifiesto):")
        for path in result.extra:
            print(f"  - {path}")

    if result.ok:
        print("\nOK: el corpus coincide con el manifiesto.")
    else:
        print("\nERROR: el corpus no coincide con el manifiesto.")
        print(
            "Comprueba la edición del estándar y revisa docs/corpus.md. "
            "Si el PDF se volvió a guardar, su SHA-256 puede cambiar aunque "
            "el contenido sea equivalente."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Valida una copia local del corpus KNX contra el manifiesto."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="Directorio raíz de la copia local del estándar KNX.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Manifiesto de metadatos (por defecto: {DEFAULT_MANIFEST}).",
    )
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="No comparar SHA-256 (útil si los PDFs se volvieron a guardar).",
    )
    parser.add_argument(
        "--check-extra",
        action="store_true",
        help="Listar PDFs que no aparecen en el manifiesto.",
    )
    parser.add_argument("--json", action="store_true", help="Emitir JSON.")
    args = parser.parse_args()

    try:
        expected = load_expected_documents(args.manifest)
        result = check_corpus(
            args.corpus,
            expected,
            verify_hashes=not args.no_hash,
            check_extra=args.check_extra,
        )
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(str(error)) from error

    _print_result(result, as_json=args.json)
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
