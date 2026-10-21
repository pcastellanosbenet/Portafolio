"""Build and load the source-document manifest."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pymupdf
from tqdm import tqdm

from src.models import DocumentInfo
from src.text import normalize_text, slugify

VOLUME_RE = re.compile(r"^(\d{2})\s+Volume\s+(\d+)\s+(.*)$", re.IGNORECASE)
DOC_NUMBER_RE = re.compile(r"^(\d{2}_\d{2}_\d{2}|\d{2}|AN\d+)", re.IGNORECASE)
VERSION_RE = re.compile(r"\bv(\d{2}\.\d{2}\.\d{2})\b", re.IGNORECASE)
STATUS_RE = re.compile(r"\b(AS|PO|CD|WD)\b")


def sha256_file(path: Path) -> str:
    """Compute a file digest in chunks to avoid loading large PDFs in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_pdf_paths(corpus_dir: Path) -> list[Path]:
    """Return PDFs in deterministic order, ignoring hidden/system files."""
    if not corpus_dir.exists():
        raise FileNotFoundError(
            f"No existe el corpus en {corpus_dir}. Configura KNX_CORPUS_DIR."
        )
    return sorted(
        path
        for path in corpus_dir.rglob("*.pdf")
        if path.is_file() and not path.name.startswith(".")
    )


def _volume_fields(relative: Path) -> tuple[str, str]:
    parts = relative.parts
    if not parts:
        return "Other", "00"
    first = parts[0]
    match = VOLUME_RE.match(first)
    if match:
        return first, match.group(1)
    if first.lower() == "application notes":
        return first, "AN"
    return first, "00"


def _doc_number(stem: str) -> str:
    match = DOC_NUMBER_RE.match(stem)
    return match.group(1) if match else slugify(stem, max_length=24)


def _doc_version(stem: str) -> str:
    match = VERSION_RE.search(stem)
    return match.group(1) if match else "3.0.0"


def _doc_status(stem: str) -> str:
    matches = STATUS_RE.findall(stem.upper())
    return matches[-1] if matches else "UNKNOWN"


def _clean_title(stem: str, metadata_title: str | None) -> str:
    if metadata_title:
        title = normalize_text(metadata_title)
        if title and "microsoft word" not in title.lower() and len(title) > 2:
            return title
    title = re.sub(r"^(?:\d{2}_\d{2}_\d{2}|\d{2}|AN\d+)\s+", "", stem)
    title = re.sub(r"\bv\d{2}\.\d{2}\.\d{2}\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:AS|PO|CD|WD)\b", "", title, flags=re.IGNORECASE)
    title = title.replace("_", " ")
    return normalize_text(title) or stem


def build_document_info(path: Path, corpus_dir: Path) -> DocumentInfo:
    """Extract stable metadata and page count from one PDF."""
    relative = path.relative_to(corpus_dir)
    volume, volume_number = _volume_fields(relative)
    stem = path.stem
    with pymupdf.open(path) as document:
        metadata = document.metadata or {}
        pages = document.page_count
    title = _clean_title(stem, metadata.get("title"))
    return DocumentInfo(
        doc_id=slugify(relative.with_suffix("").as_posix()),
        path=relative.as_posix(),
        title=title,
        volume=volume,
        volume_number=volume_number,
        doc_number=_doc_number(stem),
        version=_doc_version(stem),
        status=_doc_status(stem),
        sha256=sha256_file(path),
        pages=pages,
        language="en",
    )


def build_manifest(corpus_dir: Path) -> list[DocumentInfo]:
    """Walk the corpus and return metadata for every PDF."""
    paths = iter_pdf_paths(corpus_dir)
    return [
        build_document_info(path, corpus_dir)
        for path in tqdm(paths, desc="Manifest", unit="pdf")
    ]


def write_manifest(documents: list[DocumentInfo], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for document in documents:
            handle.write(json.dumps(document.to_dict(), ensure_ascii=False) + "\n")


def load_manifest(path: Path) -> list[DocumentInfo]:
    if not path.exists():
        return []
    documents: list[DocumentInfo] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                documents.append(DocumentInfo.from_dict(json.loads(line)))
    return documents
