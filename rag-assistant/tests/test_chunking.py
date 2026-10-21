from src.chunk import build_chunks
from src.models import DocumentInfo
from src.parse import Line, ParseResult, Section, TableBlock


def test_build_chunks_keeps_breadcrumb_and_page_metadata() -> None:
    document = DocumentInfo(
        doc_id="doc",
        path="03_07_02.pdf",
        title="Datapoint Types",
        volume="03 Volume 3",
        volume_number="03",
        doc_number="03_07_02",
        version="02.02.01",
        status="AS",
        sha256="sha",
        pages=10,
    )
    section = Section(
        heading="3.7 Datapoint Types",
        level=2,
        path=["Datapoint Types", "3.7 Datapoint Types"],
        lines=[
            Line("DPT 1.001 is a switching datapoint.", page=21, size=10, bold=False, y=10),
            Line("It uses one bit.", page=21, size=10, bold=False, y=20),
        ],
    )
    parsed = ParseResult(document=document, sections=[section], tables=[])
    bundle = build_chunks(parsed, max_words=50)
    assert len(bundle.chunks) == 1
    chunk = bundle.chunks[0]
    assert chunk.section_path == "Datapoint Types > 3.7 Datapoint Types"
    assert chunk.page_start == 21
    assert "DPT 1.001" in chunk.text
    assert "dpt:1.001" in chunk.entities


def test_build_chunks_packs_consecutive_small_sections() -> None:
    document = DocumentInfo(
        doc_id="doc",
        path="03_07_02.pdf",
        title="Datapoint Types",
        volume="03 Volume 3",
        volume_number="03",
        doc_number="03_07_02",
        version="02.02.01",
        status="AS",
        sha256="sha",
        pages=10,
    )
    sections = [
        Section(
            heading="First",
            level=2,
            path=["Datapoint Types", "First"],
            lines=[
                Line("First section text.", page=5, size=10, bold=False, y=10),
            ],
        ),
        Section(
            heading="Second",
            level=2,
            path=["Datapoint Types", "Second"],
            lines=[
                Line("Second section text.", page=7, size=10, bold=False, y=10),
            ],
        ),
    ]
    parsed = ParseResult(document=document, sections=sections, tables=[])
    bundle = build_chunks(parsed, max_words=50)

    assert len(bundle.chunks) == 1
    chunk = bundle.chunks[0]
    assert chunk.page_start == 5
    assert chunk.page_end == 7
    assert "First section text." in chunk.text
    assert "Second section text." in chunk.text


def test_build_chunks_extracts_table_entities() -> None:
    document = DocumentInfo(
        doc_id="doc",
        path="03_07_02.pdf",
        title="Datapoint Types",
        volume="03 Volume 3",
        volume_number="03",
        doc_number="03_07_02",
        version="02.02.01",
        status="AS",
        sha256="sha",
        pages=10,
    )
    table = TableBlock(
        page=22,
        section="Datapoint Types",
        section_path="Datapoint Types > 3.7 Datapoint Types",
        markdown=(
            "| DPT_ID | Format | DPT_Name |\n"
            "| 14.046 | F32 | DPT_Value_Magnetic_FluxDensity |"
        ),
        rows=[
            ["DPT_ID", "Format", "DPT_Name"],
            ["14.046", "F32", "DPT_Value_Magnetic_FluxDensity"],
        ],
    )
    parsed = ParseResult(document=document, sections=[], tables=[table])
    bundle = build_chunks(parsed, max_words=100)
    assert bundle.chunks
    assert bundle.chunks[0].content_type == "table"
    assert any(record.entity_id == "dpt:14.046" for record in bundle.entities)
