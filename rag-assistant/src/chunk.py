"""Turn parsed PDF sections and tables into retrievable chunks."""

from __future__ import annotations

from dataclasses import dataclass

from src.entities import extract_entities, extract_entities_from_table
from src.models import Chunk, DocumentInfo, EntityRecord
from src.parse import ParseResult, Section, TableBlock
from src.text import estimate_tokens, normalize_text


@dataclass
class ChunkBundle:
    chunks: list[Chunk]
    entities: list[EntityRecord]


def _content_type(section: Section) -> str:
    heading = section.heading.lower()
    if any(token in heading for token in ("procedure", "process", "step", "installation")):
        return "procedure"
    if any(token in heading for token in ("definition", "terms", "glossary")):
        return "definition"
    if "table" in heading:
        return "table"
    return "text"


def _split_words(text: str, max_words: int, overlap_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks: list[str] = []
    start = 0
    step = max(1, max_words - overlap_words)
    while start < len(words):
        end = min(len(words), start + max_words)
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += step
    return chunks


def _make_chunk(
    document: DocumentInfo,
    section: Section,
    text: str,
    chunk_id: str,
    content_type: str,
    *,
    section_path: str | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
) -> Chunk:
    clean_text = normalize_text(text)
    path = section_path or section.section_path
    return Chunk(
        chunk_id=chunk_id,
        doc_id=document.doc_id,
        title=document.title,
        volume=document.volume,
        volume_number=document.volume_number,
        doc_number=document.doc_number,
        section=section.heading,
        section_path=path,
        page_start=page_start if page_start is not None else section.page_start,
        page_end=page_end if page_end is not None else section.page_end,
        content_type=content_type,
        text=clean_text,
        token_count=estimate_tokens(clean_text),
        entities=extract_entities(f"{path}\n{clean_text}"),
        source_sha=document.sha256,
        language=document.language,
    )


@dataclass
class _Unit:
    text: str
    section: Section
    content_type: str
    page_start: int
    page_end: int


def _section_units(
    sections: list[Section],
    *,
    max_words: int,
    overlap_words: int,
) -> list[_Unit]:
    units: list[_Unit] = []
    for section in sections:
        text = section.text
        if not text:
            continue
        for part in _split_words(text, max_words=max_words, overlap_words=overlap_words):
            units.append(
                _Unit(
                    text=f"{section.section_path}\n{part}",
                    section=section,
                    content_type=_content_type(section),
                    page_start=section.page_start,
                    page_end=section.page_end,
                )
            )
    return units


def _section_chunks(
    document: DocumentInfo,
    sections: list[Section],
    max_words: int,
    overlap_words: int,
) -> list[Chunk]:
    """Pack consecutive small sections into substantial, cited chunks.

    A DPT catalogue contains hundreds of tiny sections (one per datapoint
    type). Emitting one vector per section wastes storage and produces chunks
    without enough context. We keep section boundaries for citations but pack
    neighbouring sections up to roughly ``max_words`` words.
    """
    units = _section_units(
        sections,
        max_words=max_words,
        overlap_words=overlap_words,
    )
    if not units:
        return []
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    current_words = 0
    for unit in units:
        unit_words = len(unit.text.split())
        if current and current_words + unit_words > max_words:
            groups.append(current)
            current = []
            current_words = 0
        current.append(unit)
        current_words += unit_words
        if current_words >= max_words:
            groups.append(current)
            current = []
            current_words = 0
    if current:
        groups.append(current)

    chunks: list[Chunk] = []
    for group_index, group in enumerate(groups):
        first = group[0]
        text = "\n\n".join(unit.text for unit in group)
        chunks.append(
            _make_chunk(
                document,
                first.section,
                text,
                f"{document.doc_id}::section::{group_index}",
                first.content_type,
                section_path=first.section.section_path,
                page_start=first.page_start,
                page_end=group[-1].page_end,
            )
        )
    return chunks


def _table_groups(table: TableBlock, max_rows: int = 30) -> list[list[list[str]]]:
    if len(table.rows) <= max_rows:
        return [table.rows]
    header = table.rows[0]
    groups: list[list[list[str]]] = []
    for start in range(1, len(table.rows), max_rows):
        groups.append([header] + table.rows[start : start + max_rows])
    return groups


def _table_chunks(
    document: DocumentInfo,
    tables: list[TableBlock],
    max_words: int,
) -> tuple[list[Chunk], list[EntityRecord]]:
    chunks: list[Chunk] = []
    entities: list[EntityRecord] = []
    for table_index, table in enumerate(tables):
        for group_index, rows in enumerate(_table_groups(table)):
            markdown = "\n".join(
                "| " + " | ".join(row) + " |" for row in rows
            )
            text = normalize_text(
                f"{table.section_path}\n\n{markdown}"
            )
            if not text:
                continue
            # Keep huge tables bounded even after row grouping.
            for part_index, part in enumerate(
                _split_words(text, max_words=max_words, overlap_words=0)
            ):
                chunk_id = (
                    f"{document.doc_id}::table::{table.page}::"
                    f"{table_index}::{group_index}::{part_index}"
                )
                section = Section(
                    heading=table.section,
                    level=1,
                    path=table.section_path.split(" > "),
                )
                chunk = _make_chunk(
                    document,
                    section,
                    part,
                    chunk_id,
                    "table",
                    section_path=table.section_path,
                    page_start=table.page,
                    page_end=table.page,
                )
                chunks.append(chunk)
                entities.extend(
                    extract_entities_from_table(
                        rows,
                        document=document,
                        chunk_id=chunk_id,
                        section=table.section,
                        page=table.page,
                    )
                )
    return chunks, entities


def build_chunks(
    parsed: ParseResult,
    *,
    max_words: int = 500,
    overlap_words: int = 80,
) -> ChunkBundle:
    """Build section-aware chunks and structured table entities."""
    chunks = _section_chunks(
        parsed.document,
        parsed.sections,
        max_words=max_words,
        overlap_words=overlap_words,
    )
    table_chunks, entities = _table_chunks(
        parsed.document,
        parsed.tables,
        max_words=max_words,
    )
    return ChunkBundle(chunks=chunks + table_chunks, entities=entities)
