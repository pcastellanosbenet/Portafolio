"""PDF parsing with layout-aware sections and optional table extraction."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from src.models import DocumentInfo
from src.text import clean_cell, normalize_text

NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,4})\s+\S")
ANNEX_RE = re.compile(r"^(?:Annex|Appendix)\s+[A-Z0-9]", re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?\d+(?:\s*/\s*\d+)?$", re.IGNORECASE)
PAGE_FOOTER_RE = re.compile(
    r"^v?\d{2}\.\d{2}\.\d{2}\s*-\s*page\s+\d+\s+of\s+\d+$",
    re.IGNORECASE,
)
TOC_RE = re.compile(r"(?:\.\s*){4,}|\.{4,}")
ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9 /&()\-]{3,}$")


@dataclass
class Line:
    text: str
    page: int
    size: float
    bold: bool
    y: float


@dataclass
class Section:
    heading: str
    level: int
    path: list[str]
    lines: list[Line] = field(default_factory=list)

    @property
    def page_start(self) -> int:
        return self.lines[0].page if self.lines else 0

    @property
    def page_end(self) -> int:
        return self.lines[-1].page if self.lines else 0

    @property
    def text(self) -> str:
        return normalize_text("\n".join(line.text for line in self.lines))

    @property
    def section_path(self) -> str:
        return " > ".join(self.path)


@dataclass
class TableBlock:
    page: int
    section: str
    section_path: str
    markdown: str
    rows: list[list[str]]


@dataclass
class ParseResult:
    document: DocumentInfo
    sections: list[Section]
    tables: list[TableBlock] = field(default_factory=list)


def _is_bold(flags: int) -> bool:
    # PyMuPDF span flag 16 means bold.
    return bool(flags & 16)


def _extract_lines(path: Path) -> list[Line]:
    lines: list[Line] = []
    with pymupdf.open(path) as document:
        for page_index, page in enumerate(document, start=1):
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = normalize_text("".join(span.get("text", "") for span in spans))
                    if not text:
                        continue
                    sizes = [float(span.get("size", 0)) for span in spans]
                    flags = [int(span.get("flags", 0)) for span in spans]
                    lines.append(
                        Line(
                            text=text,
                            page=page_index,
                            size=max(sizes) if sizes else 0.0,
                            bold=any(_is_bold(flag) for flag in flags),
                            y=float(line.get("bbox", (0, 0, 0, 0))[1]),
                        )
                    )
    return lines


def _remove_repeated_lines(lines: list[Line], page_count: int) -> list[Line]:
    """Drop running headers, footers and page numbers.

    A line is considered boilerplate when the same short text appears on a
    significant fraction of pages. This is intentionally conservative.
    """
    pages_by_text: dict[str, set[int]] = defaultdict(set)
    for line in lines:
        key = re.sub(r"\s+", " ", line.text.lower()).strip()
        # Page numbers vary from page to page; normalise them before counting.
        key = re.sub(r"\bpage\s+\d+\s+of\s+\d+\b", "page N of M", key)
        key = re.sub(r"\bpage\s+\d+\b", "page N", key)
        if len(key) <= 120:
            pages_by_text[key].add(line.page)
    threshold = max(3, int(page_count * 0.25))
    boilerplate = {
        key
        for key, pages in pages_by_text.items()
        if len(pages) >= threshold and len(key) <= 120
    }
    cleaned: list[Line] = []
    for line in lines:
        key = re.sub(r"\s+", " ", line.text.lower()).strip()
        key = re.sub(r"\bpage\s+\d+\s+of\s+\d+\b", "page N of M", key)
        key = re.sub(r"\bpage\s+\d+\b", "page N", key)
        if key in boilerplate:
            continue
        if PAGE_NUMBER_RE.match(line.text) or PAGE_FOOTER_RE.match(line.text):
            continue
        if len(line.text) <= 1 or TOC_RE.search(line.text):
            continue
        cleaned.append(line)
    return cleaned


def _body_size(lines: list[Line]) -> float:
    sizes = Counter(round(line.size * 2) / 2 for line in lines if line.size > 0)
    return sizes.most_common(1)[0][0] if sizes else 10.0


def _heading_level(line: Line, body_size: float) -> int:
    text = line.text.strip()
    if not text or len(text) > 140 or TOC_RE.search(text):
        return 0
    numbered = NUMBERED_HEADING_RE.match(text)
    if numbered:
        return numbered.group(1).count(".") + 1
    if ANNEX_RE.match(text):
        return 1
    words = len(text.split())
    if words > 14:
        return 0
    if ALL_CAPS_RE.match(text) and words <= 10:
        return 1
    if line.size >= body_size + 2.0:
        return 1
    if line.size >= body_size + 1.0 and line.bold:
        return 2
    if line.bold and words <= 8 and not text.endswith((".", ",", ";", ":")):
        return 2
    return 0


def _build_sections(lines: list[Line], document_title: str) -> list[Section]:
    if not lines:
        return [Section(heading=document_title, level=0, path=[document_title])]
    body_size = _body_size(lines)
    sections: list[Section] = []
    current = Section(heading=document_title, level=0, path=[document_title])
    stack: list[tuple[int, str]] = []

    def close_current() -> None:
        if current.lines:
            sections.append(current)

    for line in lines:
        level = _heading_level(line, body_size)
        if level > 0:
            close_current()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, line.text.strip()))
            path = [document_title] + [heading for _, heading in stack]
            # Avoid a duplicate when the first heading is the document title.
            if len(path) > 1 and path[0].lower() == path[1].lower():
                path = path[1:]
            current = Section(heading=line.text.strip(), level=level, path=path)
        else:
            current.lines.append(line)
    close_current()
    sections = [section for section in sections if section.text]
    if not sections or sum(len(section.text) for section in sections) < 100:
        return _fallback_page_sections(lines, document_title)
    return sections


def _fallback_page_sections(lines: list[Line], document_title: str) -> list[Section]:
    by_page: dict[int, list[Line]] = defaultdict(list)
    for line in lines:
        by_page[line.page].append(line)
    return [
        Section(
            heading=f"{document_title} — page {page}",
            level=1,
            path=[document_title, f"page {page}"],
            lines=page_lines,
        )
        for page, page_lines in sorted(by_page.items())
        if page_lines
    ]


def _section_for_page(sections: list[Section], page: int, fallback: str) -> Section | None:
    candidates = [section for section in sections if section.page_start <= page <= section.page_end]
    if not candidates:
        return None
    return min(candidates, key=lambda section: section.page_end - section.page_start)


def _table_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    separator = ["---"] * width
    body = normalized[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _table_is_useful(rows: list[list[str]]) -> bool:
    """Reject fragments and diagram grids that are not actual tables."""
    non_empty_cells = [cell for row in rows for cell in row if cell]
    if len(non_empty_cells) < 6:
        return False
    widths = [sum(1 for cell in row if cell) for row in rows]
    if max(widths, default=0) < 2:
        return False
    if sum(1 for width in widths if width >= 2) < 2:
        return False
    # Keep DPT/PID catalog tables even when they are short.
    joined = " ".join(non_empty_cells)
    if re.search(r"\b\d{1,2}\.\d{3}\b", joined) or "PID_" in joined:
        return True
    # Generic tables are useful only when they have enough structure. Smaller
    # fragments are usually diagrams or duplicated page text.
    return len(rows) >= 5 and max(widths, default=0) >= 3 and len(non_empty_cells) >= 20


def _extract_tables(
    path: Path,
    document: DocumentInfo,
    sections: list[Section],
) -> list[TableBlock]:
    tables: list[TableBlock] = []
    with pymupdf.open(path) as pdf:
        for page_index, page in enumerate(pdf, start=1):
            try:
                finder = page.find_tables()
            except Exception:
                continue
            for table in getattr(finder, "tables", []):
                try:
                    raw_rows = table.extract()
                except Exception:
                    continue
                rows = [
                    [clean_cell(cell) for cell in row]
                    for row in raw_rows
                    if row and any(clean_cell(cell) for cell in row)
                ]
                if len(rows) < 2 or not _table_is_useful(rows):
                    continue
                markdown = _table_markdown(rows)
                if len(markdown) < 60:
                    continue
                section = _section_for_page(sections, page_index, document.title)
                tables.append(
                    TableBlock(
                        page=page_index,
                        section=section.heading if section else document.title,
                        section_path=(
                            section.section_path if section else document.title
                        ),
                        markdown=markdown,
                        rows=rows,
                    )
                )
    return tables


def parse_pdf(
    path: Path,
    document: DocumentInfo,
    *,
    extract_tables: bool = True,
) -> ParseResult:
    """Parse one PDF into sections and optional table blocks."""
    lines = _extract_lines(path)
    with pymupdf.open(path) as pdf:
        page_count = pdf.page_count
    lines = _remove_repeated_lines(lines, page_count)
    sections = _build_sections(lines, document.title)
    tables = _extract_tables(path, document, sections) if extract_tables else []
    return ParseResult(document=document, sections=sections, tables=tables)
