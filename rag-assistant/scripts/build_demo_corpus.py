"""Build the synthetic PDF corpus used by the public demo.

The demo corpus is deliberately fictional and is not a redistribution of the
KNX Standard.  Its only purpose is to let a fork exercise the complete
ingestion, retrieval, citation and evaluation flow without licensed material.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf

PAGE_WIDTH, PAGE_HEIGHT = pymupdf.paper_size("a4")
MARGIN = 56.0
BODY_SIZE = 10.0
HEADING_SIZES = {1: 16.0, 2: 13.0, 3: 11.0}
TABLE_SIZE = 8.0
TABLE_LINE_HEIGHT = 9.5
TABLE_PADDING = 4.0


def load_documents(source: Path) -> list[dict]:
    """Load the synthetic document definitions from JSON."""
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("El archivo de documentos debe contener una lista.")
    for document in payload:
        if not isinstance(document, dict) or "filename" not in document:
            raise ValueError("Cada documento necesita un campo 'filename'.")
        if not isinstance(document.get("blocks"), list):
            raise ValueError(f"El documento {document['filename']} no tiene bloques.")
    return payload


def _wrap(text: str, *, fontsize: float, max_width: float) -> list[str]:
    """Wrap text using the same Helvetica metrics used to draw it."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pymupdf.get_text_length(candidate, fontsize=fontsize) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class _PdfWriter:
    """Small top-down PDF writer with headings, paragraphs and grid tables."""

    def __init__(self, document: pymupdf.Document) -> None:
        self.document = document
        self.page: pymupdf.Page | None = None
        self.y = MARGIN

    def new_page(self) -> None:
        self.page = self.document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.y = MARGIN

    def _ensure(self, height: float) -> None:
        if self.page is None:
            self.new_page()
        assert self.page is not None
        if self.y + height > PAGE_HEIGHT - MARGIN:
            self.new_page()

    def heading(self, text: str, level: int) -> None:
        size = HEADING_SIZES.get(level, BODY_SIZE + 1)
        lines = _wrap(
            text,
            fontsize=size,
            max_width=PAGE_WIDTH - 2 * MARGIN,
        )
        for line in lines:
            self._ensure(size + 12)
            assert self.page is not None
            self.y += size + 2
            self.page.insert_text(
                (MARGIN, self.y),
                line,
                fontsize=size,
                fontname="helv",
            )
            self.y += 4
        self.y += 6

    def paragraph(self, text: str) -> None:
        lines = _wrap(
            text,
            fontsize=BODY_SIZE,
            max_width=PAGE_WIDTH - 2 * MARGIN,
        )
        for line in lines:
            self._ensure(BODY_SIZE * 1.5)
            assert self.page is not None
            self.y += BODY_SIZE * 1.35
            self.page.insert_text(
                (MARGIN, self.y),
                line,
                fontsize=BODY_SIZE,
                fontname="helv",
            )
        self.y += 7

    def _column_widths(self, column_count: int) -> list[float]:
        available = PAGE_WIDTH - 2 * MARGIN
        if column_count == 4:
            # Wide enough for identifiers such as PID_LOAD_STATE_CONTROL.
            # Overflowing a cell makes PyMuPDF's table extractor interleave the
            # text with the next column, which breaks exact identifier lookup.
            widths = [140.0, 110.0, 130.0, 0.0]
            widths[-1] = available - sum(widths[:-1])
            return widths
        return [available / column_count] * column_count

    def _row_lines(self, row: list[str], widths: list[float]) -> list[list[str]]:
        return [
            _wrap(
                cell,
                fontsize=TABLE_SIZE,
                max_width=max(10.0, width - 2 * TABLE_PADDING),
            )
            for cell, width in zip(row, widths, strict=True)
        ]

    def _draw_row(
        self,
        row: list[str],
        widths: list[float],
        lines: list[list[str]],
        *,
        header: bool = False,
    ) -> float:
        assert self.page is not None
        height = max(len(cell_lines) for cell_lines in lines) * TABLE_LINE_HEIGHT
        height += 2 * TABLE_PADDING
        x = MARGIN
        top = self.y
        for cell_lines, width in zip(lines, widths, strict=True):
            rect = pymupdf.Rect(x, top, x + width, top + height)
            self.page.draw_rect(rect, color=(0, 0, 0), width=0.6)
            for index, line in enumerate(cell_lines):
                baseline = top + TABLE_PADDING + TABLE_SIZE + index * TABLE_LINE_HEIGHT
                self.page.insert_text(
                    (x + TABLE_PADDING, baseline),
                    line,
                    fontsize=TABLE_SIZE,
                    fontname="helv",
                )
            x += width
        self.y = top + height
        if header:
            self.y += 0.6
        return height

    def table(self, rows: list[list[str]]) -> None:
        if len(rows) < 2:
            return
        column_count = max(len(row) for row in rows)
        padded = [row + [""] * (column_count - len(row)) for row in rows]
        widths = self._column_widths(column_count)
        header = padded[0]
        header_lines = self._row_lines(header, widths)
        header_height = max(len(cell_lines) for cell_lines in header_lines)
        header_height = header_height * TABLE_LINE_HEIGHT + 2 * TABLE_PADDING

        self._ensure(header_height)
        self._draw_row(header, widths, header_lines, header=True)

        for row in padded[1:]:
            lines = self._row_lines(row, widths)
            height = max(len(cell_lines) for cell_lines in lines)
            height = height * TABLE_LINE_HEIGHT + 2 * TABLE_PADDING
            if self.y + height > PAGE_HEIGHT - MARGIN:
                self.new_page()
                self._draw_row(header, widths, header_lines, header=True)
            self._draw_row(row, widths, lines)
        self.y += 10


def _write_document(document: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    pdf = pymupdf.open()
    pdf.set_metadata({"title": str(document.get("title", output_path.stem))})
    writer = _PdfWriter(pdf)
    try:
        for block in document["blocks"]:
            block_type = block.get("type")
            if block_type == "heading":
                writer.heading(str(block.get("text", "")), int(block.get("level", 1)))
            elif block_type == "paragraph":
                writer.paragraph(str(block.get("text", "")))
            elif block_type == "table":
                rows = block.get("rows", [])
                if not isinstance(rows, list):
                    raise ValueError(f"Tabla inválida en {document['filename']}")
                writer.table([[str(cell) for cell in row] for row in rows])
            else:
                raise ValueError(f"Tipo de bloque desconocido: {block_type}")
        pdf.save(output_path)
    finally:
        pdf.close()


def build_demo_corpus(
    source: Path = Path("demo/documents.json"),
    output: Path = Path("demo/corpus"),
    *,
    clean: bool = False,
) -> list[Path]:
    """Generate the synthetic PDFs and return their paths."""
    documents = load_documents(source)
    output.mkdir(parents=True, exist_ok=True)
    if clean:
        for path in output.rglob("*.pdf"):
            path.unlink()

    paths: list[Path] = []
    for document in documents:
        relative = Path(str(document["filename"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Ruta de documento no permitida: {relative}")
        path = output / relative
        _write_document(document, path)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera el corpus sintético de demostración en PDF."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("demo/documents.json"),
        help="Definición JSON del corpus de demostración.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("demo/corpus"),
        help="Directorio donde se generarán los PDFs.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Elimina los PDFs existentes antes de generar.",
    )
    args = parser.parse_args()

    paths = build_demo_corpus(args.source, args.output, clean=args.clean)
    print(f"Generados {len(paths)} PDFs sintéticos en {args.output}")
    for path in paths:
        print(f"  - {path.relative_to(args.output)}")


if __name__ == "__main__":
    main()
