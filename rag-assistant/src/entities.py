"""KNX identifier extraction and deterministic query planning."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.models import DocumentInfo, EntityRecord, SearchFilters
from src.text import normalize_text, unique_preserve_order

DPT_RE = re.compile(r"\b(?:DPT[_\s-]*)?(\d{1,2}\.\d{3})\b", re.IGNORECASE)
PID_RE = re.compile(r"\bPID_[A-Z0-9_]+\b", re.IGNORECASE)
AN_RE = re.compile(r"\bAN\d{2,3}\b", re.IGNORECASE)
MASK_RE = re.compile(r"\b(?:mask|mask version)\s*[:=]?\s*([0-9A-F]{4})h?\b", re.IGNORECASE)
VOLUME_RE = re.compile(r"\b(?:volume|vol\.?)\s*(\d{1,2})\b", re.IGNORECASE)
DOC_NUMBER_RE = re.compile(r"\b(\d{2}_\d{2}_\d{2})\b")
SECTION_RE = re.compile(r"\b(\d+(?:\.\d+){2,4})\b")

SPANISH_HINTS = {
    "dirección de grupo": "group address",
    "direccion de grupo": "group address",
    "tipo de datapoint": "datapoint type",
    "tipo de dato": "datapoint type",
    "certificación": "certification",
    "certificacion": "certification",
    "requisitos": "requirements",
    "procedimiento": "procedure",
    "seguridad": "security",
    "iluminación": "lighting",
    "iluminacion": "lighting",
    "actuador": "actuator",
    "máscara": "mask version",
    "mascara": "mask version",
    "propiedad": "property",
    "norma": "standard",
    "documento": "document",
    "versión": "version",
    "version": "version",
    "cambios": "changes",
    "diferencia": "difference",
    "cómo": "how",
    "como": "how",
    "qué": "what",
    "que": "what",
    "cuál": "which",
    "cual": "which",
    "pasos": "steps",
    "configurar": "configure",
    "instalar": "install",
}

TECH_HINTS = {
    "dpt": "datapoint type DPT",
    "datapoint type": "DPT data point type",
    "group address": "group address GA",
    "ga": "group address",
    "pid": "property identifier PID",
    "property": "property PID",
    "mask": "mask version",
    "tp1": "twisted pair TP1",
    "twisted pair": "TP1",
    "rf": "radio frequency RF",
    "pl": "powerline PL",
    "application note": "AN application note",
    "certification": "certification registration",
    "knx secure": "KNX Secure security",
}

COMPARISON_RE = re.compile(
    r"\b(compare|comparison|difference|different|versus|vs\.?|diferencia|comparar)\b",
    re.IGNORECASE,
)
PROCEDURE_RE = re.compile(
    r"\b(how|steps|procedure|process|install|configure|cómo|como|pasos|procedimiento)\b",
    re.IGNORECASE,
)
DEFINITION_RE = re.compile(
    r"\b(what is|what are|define|definition|qué es|que es|qué son|que son|definición)\b",
    re.IGNORECASE,
)
CHANGE_RE = re.compile(
    r"\b(changed|changes|new in|difference between versions|qué cambió|que cambio)\b",
    re.IGNORECASE,
)
TROUBLESHOOT_RE = re.compile(
    r"\b(error|problem|fail|failure|why|troubleshoot|fallo|problema)\b",
    re.IGNORECASE,
)


def normalize_entity(identifier: str) -> str:
    """Return a canonical identifier key used by the entity catalogue."""
    value = normalize_text(identifier)
    dpt = DPT_RE.fullmatch(value)
    if dpt:
        major, minor = dpt.group(1).split(".")
        return f"dpt:{int(major)}.{minor}"
    pid = PID_RE.fullmatch(value)
    if pid:
        return f"pid:{value.upper()}"
    note = AN_RE.fullmatch(value)
    if note:
        return f"an:{value.upper()}"
    mask = MASK_RE.fullmatch(value)
    if mask:
        return f"mask:{mask.group(1).upper()}"
    return value.lower()


def extract_entities(text: str) -> list[str]:
    """Extract KNX identifiers from free text in canonical form."""
    entities: list[str] = []
    for match in DPT_RE.finditer(text):
        entities.append(normalize_entity(match.group(1)))
    for match in PID_RE.finditer(text):
        entities.append(normalize_entity(match.group(0)))
    for match in AN_RE.finditer(text):
        entities.append(normalize_entity(match.group(0)))
    for match in MASK_RE.finditer(text):
        entities.append(normalize_entity(f"mask {match.group(1)}"))
    return unique_preserve_order(entities)


def extract_entities_from_table(
    rows: list[list[str]],
    document: DocumentInfo,
    chunk_id: str,
    section: str,
    page: int,
) -> list[EntityRecord]:
    """Extract DPT and PID rows from a table without relying on fixed columns."""
    records: list[EntityRecord] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        cells = [normalize_text(cell) for cell in row if normalize_text(cell)]
        if not cells:
            continue
        joined = " | ".join(cells)
        for cell in cells:
            dpt = re.fullmatch(r"\d{1,2}\.\d{3}", cell)
            if dpt:
                name = next(
                    (candidate for candidate in cells if candidate.startswith("DPT_")),
                    "",
                )
                entity_id = normalize_entity(cell)
                key = (entity_id, chunk_id)
                if key not in seen:
                    seen.add(key)
                    records.append(
                        EntityRecord(
                            entity_id=entity_id,
                            kind="dpt",
                            identifier=cell,
                            name=name,
                            chunk_id=chunk_id,
                            doc_id=document.doc_id,
                            section=section,
                            page=page,
                            text=joined,
                        )
                    )
            pid = PID_RE.fullmatch(cell)
            if pid:
                name = next(
                    (
                        candidate
                        for candidate in cells
                        if candidate != cell and not candidate.startswith("PID_")
                    ),
                    "",
                )
                entity_id = normalize_entity(cell)
                key = (entity_id, chunk_id)
                if key not in seen:
                    seen.add(key)
                    records.append(
                        EntityRecord(
                            entity_id=entity_id,
                            kind="pid",
                            identifier=cell.upper(),
                            name=name,
                            chunk_id=chunk_id,
                            doc_id=document.doc_id,
                            section=section,
                            page=page,
                            text=joined,
                        )
                    )
    return records


@dataclass(frozen=True)
class QueryPlan:
    original: str
    expanded: str
    query_type: str
    entities: list[str] = field(default_factory=list)
    filters: SearchFilters = field(default_factory=SearchFilters)


def classify_query(question: str) -> str:
    if COMPARISON_RE.search(question):
        return "comparison"
    if CHANGE_RE.search(question):
        return "change"
    # An explicit identifier is more specific than a generic "what is" phrasing.
    if extract_entities(question):
        return "identifier"
    if PROCEDURE_RE.search(question):
        return "procedure"
    if DEFINITION_RE.search(question):
        return "definition"
    if TROUBLESHOOT_RE.search(question):
        return "troubleshooting"
    return "general"


def expand_query(question: str, entities: list[str] | None = None) -> str:
    """Add bilingual and acronym expansions to improve lexical retrieval."""
    entities = entities if entities is not None else extract_entities(question)
    lower = question.lower()
    additions: list[str] = []
    for source, target in SPANISH_HINTS.items():
        if source in lower:
            additions.append(target)
    for source, target in TECH_HINTS.items():
        if source in lower:
            additions.append(target)
    for entity in entities:
        if entity.startswith("dpt:"):
            additions.append(f"DPT {entity[4:]} datapoint type")
        elif entity.startswith("pid:"):
            additions.append(f"{entity[4:]} property identifier")
        elif entity.startswith("an:"):
            additions.append(f"{entity[3:]} application note")
    if not additions:
        return question
    return question + "\n" + " ".join(unique_preserve_order(additions))


def _extract_filters(question: str) -> SearchFilters:
    volume_match = VOLUME_RE.search(question)
    doc_match = DOC_NUMBER_RE.search(question)
    return SearchFilters(
        volume_number=(volume_match.group(1).zfill(2) if volume_match else None),
        doc_number=doc_match.group(1) if doc_match else None,
    )


def build_query_plan(question: str) -> QueryPlan:
    entities = extract_entities(question)
    return QueryPlan(
        original=question,
        expanded=expand_query(question, entities),
        query_type=classify_query(question),
        entities=entities,
        filters=_extract_filters(question),
    )


class EntityCatalog:
    """Exact lookup over structured identifiers extracted from tables."""

    def __init__(self, records: list[EntityRecord] | None = None) -> None:
        self.records = records or []
        self.by_entity: dict[str, list[EntityRecord]] = {}
        for record in self.records:
            self.by_entity.setdefault(record.entity_id, []).append(record)

    @classmethod
    def load(cls, path: Path) -> EntityCatalog:
        if not path.exists():
            return cls()
        records: list[EntityRecord] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(EntityRecord.from_dict(json.loads(line)))
        return cls(records)

    def lookup(self, identifier: str) -> list[EntityRecord]:
        return self.by_entity.get(normalize_entity(identifier), [])

    def lookup_many(self, identifiers: list[str]) -> list[EntityRecord]:
        results: list[EntityRecord] = []
        seen: set[str] = set()
        for identifier in identifiers:
            for record in self.lookup(identifier):
                key = f"{record.entity_id}:{record.chunk_id}"
                if key not in seen:
                    seen.add(key)
                    results.append(record)
        return results
