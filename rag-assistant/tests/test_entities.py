from src.entities import (
    build_query_plan,
    extract_entities,
    extract_entities_from_table,
    normalize_entity,
)
from src.models import DocumentInfo


def test_extract_entities_normalises_identifiers() -> None:
    entities = extract_entities(
        "Explain DPT 1.001, PID_LOAD_STATE_CONTROL and AN193."
    )
    assert entities == ["dpt:1.001", "pid:PID_LOAD_STATE_CONTROL", "an:AN193"]


def test_normalize_entity_accepts_prefixed_forms() -> None:
    assert normalize_entity("DPT 01.001") == "dpt:1.001"
    assert normalize_entity("pid_load_state_control") == "pid:PID_LOAD_STATE_CONTROL"


def test_query_plan_classifies_and_extracts_filters() -> None:
    plan = build_query_plan("What is DPT 1.001 in volume 3?")
    assert plan.query_type == "identifier"
    assert "dpt:1.001" in plan.entities
    assert plan.filters.volume_number == "03"
    assert "datapoint type" in plan.expanded.lower()


def test_table_entity_extraction() -> None:
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
    rows = [
        ["DPT_ID", "Format", "DPT_Name"],
        ["14.046", "F32", "DPT_Value_Magnetic_FluxDensity"],
    ]
    records = extract_entities_from_table(
        rows,
        document,
        chunk_id="doc::table::1",
        section="Datapoint Types",
        page=20,
    )
    assert len(records) == 1
    assert records[0].entity_id == "dpt:14.046"
    assert records[0].name == "DPT_Value_Magnetic_FluxDensity"
