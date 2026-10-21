"""CLI ingestion: PDFs -> manifest -> chunks -> embeddings -> Qdrant."""

from __future__ import annotations

import argparse
import json
import logging
import resource
import time
from datetime import UTC, datetime
from pathlib import Path

from tqdm import tqdm

from src.chunk import ChunkBundle, build_chunks
from src.config import Settings
from src.embeddings import get_embedder
from src.index import QdrantIndex
from src.manifest import build_document_info, iter_pdf_paths, write_manifest
from src.models import Chunk, DocumentInfo, EntityRecord
from src.parse import parse_pdf

logger = logging.getLogger(__name__)


def _write_jsonl(items: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _read_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _selected_paths(
    settings: Settings,
    limit: int | None,
    doc_filter: str | list[str] | None,
) -> list[Path]:
    paths = iter_pdf_paths(settings.corpus_dir)
    filters = [doc_filter] if isinstance(doc_filter, str) else (doc_filter or [])
    needles = [needle.lower() for needle in filters if needle]
    if needles:
        paths = [
            path
            for path in paths
            if any(
                needle in path.relative_to(settings.corpus_dir).as_posix().lower()
                for needle in needles
            )
        ]
    if limit is not None:
        paths = paths[:limit]
    if not paths:
        raise SystemExit("No hay PDFs que coincidan con los filtros.")
    return paths


def _parse_documents(
    paths: list[Path],
    settings: Settings,
    *,
    extract_tables: bool,
) -> tuple[list[DocumentInfo], ChunkBundle]:
    documents: list[DocumentInfo] = []
    all_chunks: list[Chunk] = []
    all_entities: list[EntityRecord] = []
    for path in tqdm(paths, desc="Parse", unit="pdf"):
        document = build_document_info(path, settings.corpus_dir)
        documents.append(document)
        parsed = parse_pdf(path, document, extract_tables=extract_tables)
        bundle = build_chunks(
            parsed,
            max_words=settings.chunk_max_words,
            overlap_words=settings.chunk_overlap_words,
        )
        all_chunks.extend(bundle.chunks)
        all_entities.extend(bundle.entities)
        logger.debug(
            "%s: %d secciones, %d chunks, %d tablas",
            document.doc_id,
            len(parsed.sections),
            len(bundle.chunks),
            len(parsed.tables),
        )
    # Deduplicate entity records by (entity_id, chunk_id).
    unique_entities: list[EntityRecord] = []
    seen: set[tuple[str, str]] = set()
    for record in all_entities:
        key = (record.entity_id, record.chunk_id)
        if key not in seen:
            seen.add(key)
            unique_entities.append(record)
    return documents, ChunkBundle(chunks=all_chunks, entities=unique_entities)


def _index_chunks(
    chunks: list[Chunk],
    settings: Settings,
    *,
    rebuild: bool,
) -> dict:
    embedder = get_embedder(settings)
    index = QdrantIndex(
        settings.collection_name,
        url=settings.qdrant_url,
        path=str(settings.qdrant_path) if not settings.qdrant_url else None,
        timeout=settings.qdrant_timeout,
    )
    meta = _read_meta(settings.index_meta_path)
    recreate = rebuild
    if meta:
        if meta.get("embedding_model") != settings.embedding_model:
            logger.warning("El modelo de embeddings cambió; se reconstruye el índice.")
            recreate = True
        if int(meta.get("embedding_dimension", 0)) != embedder.dimension:
            logger.warning("La dimensión de embeddings cambió; se reconstruye el índice.")
            recreate = True
    index.ensure_collection(embedder.dimension, recreate=recreate)
    if index.vector_size() not in (None, embedder.dimension):
        logger.warning("La colección existente tiene otra dimensión; se reconstruye.")
        index.ensure_collection(embedder.dimension, recreate=True)
        recreate = True

    existing: set[str] = set()
    if not recreate:
        existing = index.existing_chunk_ids([chunk.chunk_id for chunk in chunks])
    missing = [chunk for chunk in chunks if chunk.chunk_id not in existing]
    logger.info(
        "Chunks: %d total, %d ya indexados, %d pendientes",
        len(chunks),
        len(existing),
        len(missing),
    )

    batch_size = max(1, settings.embedding_batch_size)
    for start in tqdm(range(0, len(missing), batch_size), desc="Embed", unit="batch"):
        batch = missing[start : start + batch_size]
        vectors = embedder.embed_documents([chunk.text for chunk in batch])
        index.upsert_chunks(batch, vectors, batch_size=batch_size)

    meta = {
        "embedding_model": settings.embedding_model,
        "embedding_backend": settings.embedding_backend,
        "embedding_dimension": embedder.dimension,
        "collection_name": settings.collection_name,
        "chunks": len(chunks),
        "indexed": index.count(),
        "chunk_max_words": settings.chunk_max_words,
        "chunk_overlap_words": settings.chunk_overlap_words,
        "created_at": datetime.now(UTC).isoformat(),
    }
    settings.index_meta_path.parent.mkdir(parents=True, exist_ok=True)
    settings.index_meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    index.close()
    return meta


def ingest(
    settings: Settings,
    *,
    limit: int | None = None,
    doc_filter: str | list[str] | None = None,
    extract_tables: bool = True,
    rebuild: bool = False,
    parse_only: bool = False,
) -> dict:
    started = time.perf_counter()
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    paths = _selected_paths(settings, limit, doc_filter)
    logger.info("PDFs seleccionados: %d", len(paths))
    documents, bundle = _parse_documents(
        paths,
        settings,
        extract_tables=extract_tables,
    )
    write_manifest(documents, settings.manifest_path)
    _write_jsonl(
        [chunk.to_dict() for chunk in bundle.chunks],
        settings.chunks_path,
    )
    _write_jsonl(
        [entity.to_dict() for entity in bundle.entities],
        settings.entities_path,
    )
    summary = {
        "pdfs": len(documents),
        "pages": sum(document.pages for document in documents),
        "sections": None,
        "chunks": len(bundle.chunks),
        "entities": len(bundle.entities),
        "tables": sum(
            1 for chunk in bundle.chunks if chunk.content_type == "table"
        ),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "parse_peak_rss_mb": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            1,
        ),
    }
    if not parse_only:
        index_meta = _index_chunks(bundle.chunks, settings, rebuild=rebuild)
        summary["index"] = index_meta
    summary["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    summary["peak_rss_mb"] = round(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        1,
    )
    summary["artifacts_dir"] = str(settings.artifacts_dir)
    (settings.artifacts_dir / "ingest_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexa el estándar KNX en Qdrant.")
    parser.add_argument("--corpus", type=Path, help="Directorio raíz del corpus KNX.")
    parser.add_argument("--artifacts", type=Path, help="Directorio de artefactos.")
    parser.add_argument("--limit", type=int, help="Limitar a los primeros N PDFs.")
    parser.add_argument(
        "--doc",
        action="append",
        help="Filtrar por parte del nombre/ruta del PDF. Se puede repetir.",
    )
    parser.add_argument("--no-tables", action="store_true", help="No extraer tablas.")
    parser.add_argument("--rebuild", action="store_true", help="Recrear la colección.")
    parser.add_argument("--parse-only", action="store_true", help="Solo parsear, sin embeddings.")
    parser.add_argument(
        "--embedding-backend",
        choices=["transformers", "hashing"],
        help="Backend de embeddings (hashing solo para pruebas).",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    updates: dict = {}
    if args.corpus:
        updates["corpus_dir"] = args.corpus
    if args.artifacts:
        updates["artifacts_dir"] = args.artifacts
    if args.embedding_backend:
        updates["embedding_backend"] = args.embedding_backend
    settings = Settings(**updates)
    summary = ingest(
        settings,
        limit=args.limit,
        doc_filter=args.doc,
        extract_tables=not args.no_tables,
        rebuild=args.rebuild,
        parse_only=args.parse_only,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
