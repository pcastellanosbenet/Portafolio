"""Build the frozen 60-task evaluation corpus and its gold file."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent
TASKS_PATH = ROOT / "tasks.jsonl"
GOLD_PATH = ROOT / "gold.jsonl"
HASH_PATH = ROOT / "tasks.sha256"


def task(
    task_id: str,
    block: str,
    query: str,
    server: str | None,
    tool: str | None,
    arguments: dict[str, object] | None,
    success: dict[str, object],
    approval: str | None = None,
) -> dict[str, object]:
    return {
        "id": task_id,
        "block": block,
        "query": query,
        "gold": (
            None
            if server is None
            else {"server": server, "tool": tool, "arguments": arguments or {}}
        ),
        "success": success,
        "approval": approval,
    }


def docs_search(task_id: str, query: str, search: str, expected: str) -> dict[str, object]:
    return task(
        task_id,
        "docs",
        query,
        "docs",
        "search_docs",
        {"query": search, "limit": 3},
        {"type": "contains", "value": expected},
    )


def docs_read(task_id: str, query: str, doc_id: str, expected: str) -> dict[str, object]:
    return task(
        task_id,
        "docs",
        query,
        "docs",
        "read_doc",
        {"doc_id": doc_id},
        {"type": "contains", "value": expected},
    )


TASKS: list[dict[str, object]] = [
    docs_search("docs-01", "¿Qué documentación hay sobre MRTR?", "MRTR aprobación", "protocolo"),
    docs_search("docs-02", "Busca información sobre SSRF.", "SSRF seguridad", "seguridad"),
    docs_search(
        "docs-03",
        "¿Dónde se explican los tokens de definiciones?",
        "tokens de definiciones",
        "evaluacion",
    ),
    docs_search(
        "docs-04",
        "Busca namespacing y colisiones de herramientas.",
        "namespacing colisiones",
        "gateway",
    ),
    docs_search(
        "docs-05",
        "¿Qué dice el corpus sobre suscripciones?",
        "suscripciones",
        "protocolo",
    ),
    docs_search(
        "docs-06", "Busca incidentes y operaciones.", "incidentes operaciones", "operacion"
    ),
    docs_read("docs-07", "Lee la guía del protocolo MCP.", "protocolo", "server/discover"),
    docs_read("docs-08", "Lee la arquitectura del gateway.", "gateway", "namespacing"),
    docs_read("docs-09", "Lee la guía de seguridad.", "seguridad", "169.254.169.254"),
    docs_read("docs-10", "Lee el runbook de operaciones.", "operacion", "INC-001"),
    docs_read("docs-11", "Lee la guía de evaluación.", "evaluacion", "precisión@1"),
    task(
        "docs-12",
        "docs",
        "Lista los documentos disponibles.",
        "docs",
        "list_docs",
        {},
        {"type": "path_min", "path": "count", "value": 5},
    ),
    task(
        "docs-13",
        "docs",
        "¿Cuántos documentos tiene el corpus?",
        "docs",
        "list_docs",
        {},
        {"type": "path_min", "path": "count", "value": 5},
    ),
    task(
        "docs-14",
        "docs",
        "Muéstrame el catálogo del corpus.",
        "docs",
        "list_docs",
        {},
        {"type": "path_min", "path": "count", "value": 5},
    ),
    task(
        "docs-15",
        "docs",
        "Dame el índice de la guía del protocolo.",
        "docs",
        "outline_doc",
        {"doc_id": "protocolo"},
        {"type": "contains", "value": "Peticiones sin sesión"},
    ),
    task(
        "docs-16",
        "docs",
        "Dame el índice de la guía de seguridad.",
        "docs",
        "outline_doc",
        {"doc_id": "seguridad"},
        {"type": "contains", "value": "SSRF"},
    ),
    task(
        "docs-17",
        "docs",
        "Dame el índice de la guía de evaluación.",
        "docs",
        "outline_doc",
        {"doc_id": "evaluacion"},
        {"type": "contains", "value": "Métricas"},
    ),
    task(
        "docs-18",
        "docs",
        "Cita la guía del protocolo.",
        "docs",
        "cite_doc",
        {"doc_id": "protocolo"},
        {"type": "contains", "value": "sha256"},
    ),
    task(
        "docs-19",
        "docs",
        "Cita la guía de arquitectura.",
        "docs",
        "cite_doc",
        {"doc_id": "gateway"},
        {"type": "contains", "value": "02-gateway.md"},
    ),
    task(
        "docs-20",
        "docs",
        "Cita la guía de evaluación.",
        "docs",
        "cite_doc",
        {"doc_id": "evaluacion"},
        {"type": "contains", "value": "05-evaluacion.md"},
    ),
    task(
        "research-01",
        "research",
        "Busca en Wikipedia qué es SSRF.",
        "research",
        "wikipedia_search",
        {"query": "SSRF seguridad", "limit": 3},
        {"type": "contains", "value": "ssrf"},
    ),
    task(
        "research-02",
        "research",
        "Busca en Wikipedia prompt injection.",
        "research",
        "wikipedia_search",
        {"query": "prompt injection", "limit": 3},
        {"type": "contains", "value": "prompt-injection"},
    ),
    task(
        "research-03",
        "research",
        "Busca en Wikipedia el algoritmo BM25.",
        "research",
        "wikipedia_search",
        {"query": "BM25 ranking", "limit": 3},
        {"type": "contains", "value": "bm25"},
    ),
    task(
        "research-04",
        "research",
        "Busca en Wikipedia LangGraph.",
        "research",
        "wikipedia_search",
        {"query": "LangGraph agentes", "limit": 3},
        {"type": "contains", "value": "langgraph"},
    ),
    task(
        "research-05",
        "research",
        "Busca en Wikipedia RAG para documentación.",
        "research",
        "wikipedia_search",
        {"query": "RAG documentación", "limit": 3},
        {"type": "contains", "value": "rag"},
    ),
    task(
        "research-06",
        "research",
        "Busca en Wikipedia el Model Context Protocol.",
        "research",
        "wikipedia_search",
        {"query": "Model Context Protocol", "limit": 3},
        {"type": "contains", "value": "mcp"},
    ),
    task(
        "research-07",
        "research",
        "Lee la página de BM25.",
        "research",
        "wikipedia_get",
        {"title": "BM25"},
        {"type": "path_equals", "path": "title", "value": "BM25"},
    ),
    task(
        "research-08",
        "research",
        "Lee la página de SSRF.",
        "research",
        "wikipedia_get",
        {"title": "SSRF"},
        {"type": "path_equals", "path": "id", "value": "ssrf"},
    ),
    task(
        "research-09",
        "research",
        "Lee la página de LangGraph.",
        "research",
        "wikipedia_get",
        {"title": "LangGraph"},
        {"type": "path_equals", "path": "id", "value": "langgraph"},
    ),
    task(
        "research-10",
        "research",
        "Busca en arXiv selección de herramientas y tokens.",
        "research",
        "arxiv_search",
        {"query": "tool selection tokens", "limit": 3},
        {"type": "contains", "value": "2601.00001"},
    ),
    task(
        "research-11",
        "research",
        "Busca en arXiv llamadas de herramientas seguras.",
        "research",
        "arxiv_search",
        {"query": "secure tool calling", "limit": 3},
        {"type": "contains", "value": "2602.00002"},
    ),
    task(
        "research-12",
        "research",
        "Busca en arXiv evaluación de gateways MCP.",
        "research",
        "arxiv_search",
        {"query": "MCP gateways evaluation", "limit": 3},
        {"type": "contains", "value": "2604.00004"},
    ),
    task(
        "research-13",
        "research",
        "Lee el paper 2601.00001.",
        "research",
        "arxiv_get",
        {"arxiv_id": "2601.00001"},
        {"type": "path_equals", "path": "id", "value": "2601.00001"},
    ),
    task(
        "research-14",
        "research",
        "Lee el paper 2603.00003.",
        "research",
        "arxiv_get",
        {"arxiv_id": "2603.00003"},
        {"type": "path_equals", "path": "id", "value": "2603.00003"},
    ),
    task(
        "research-15",
        "research",
        "Lee el paper 2604.00004.",
        "research",
        "arxiv_get",
        {"arxiv_id": "2604.00004"},
        {"type": "path_equals", "path": "id", "value": "2604.00004"},
    ),
    task(
        "ops-01",
        "ops",
        "Lista los servicios disponibles.",
        "ops",
        "list_services",
        {},
        {"type": "path_min", "path": "count", "value": 5},
    ),
    task(
        "ops-02",
        "ops",
        "Consulta el estado del servicio api.",
        "ops",
        "get_service",
        {"service": "api"},
        {"type": "path_equals", "path": "name", "value": "api"},
    ),
    task(
        "ops-03",
        "ops",
        "Consulta el estado del servicio worker.",
        "ops",
        "get_service",
        {"service": "worker"},
        {"type": "path_equals", "path": "name", "value": "worker"},
    ),
    task(
        "ops-04",
        "ops",
        "Mira las métricas de api de los últimos 5 minutos.",
        "ops",
        "query_metrics",
        {"service": "api", "window_minutes": 5},
        {
            "type": "all",
            "predicates": [
                {"type": "path_equals", "path": "service", "value": "api"},
                {"type": "path_len", "path": "points", "value": 5},
            ],
        },
    ),
    task(
        "ops-05",
        "ops",
        "Mira las métricas de db de los últimos 10 minutos.",
        "ops",
        "query_metrics",
        {"service": "db", "window_minutes": 10},
        {
            "type": "all",
            "predicates": [
                {"type": "path_equals", "path": "service", "value": "db"},
                {"type": "path_len", "path": "points", "value": 10},
            ],
        },
    ),
    task(
        "ops-06",
        "ops",
        "Lista los incidentes abiertos.",
        "ops",
        "list_incidents",
        {"status": "open"},
        {"type": "path_min", "path": "count", "value": 1},
    ),
    task(
        "ops-07",
        "ops",
        "Lista los incidentes resueltos.",
        "ops",
        "list_incidents",
        {"status": "resolved"},
        {"type": "path_min", "path": "count", "value": 1},
    ),
    task(
        "ops-08",
        "ops",
        "Lee el incidente INC-001.",
        "ops",
        "get_incident",
        {"incident_id": "INC-001"},
        {"type": "path_equals", "path": "id", "value": "INC-001"},
    ),
    task(
        "ops-09",
        "ops",
        "Busca timeouts en los logs de api.",
        "ops",
        "search_logs",
        {"service": "api", "query": "timeout", "limit": 5},
        {"type": "contains", "value": "timeout"},
    ),
    task(
        "ops-10",
        "ops",
        "Busca errores de conexión en los logs de db.",
        "ops",
        "search_logs",
        {"service": "db", "query": "connection", "limit": 5},
        {"type": "contains", "value": "connection"},
    ),
    task(
        "ops-11",
        "ops",
        "Mira los últimos despliegues de api.",
        "ops",
        "deploy_history",
        {"service": "api", "limit": 3},
        {"type": "contains", "value": "2.8.1"},
    ),
    task(
        "ops-12",
        "ops",
        "Crea un incidente sev2 para api por latencia en checkout.",
        "ops",
        "create_incident",
        {"title": "Latencia en checkout", "service": "api", "severity": "sev2"},
        {
            "type": "all",
            "predicates": [
                {"type": "path_equals", "path": "status", "value": "open"},
                {"type": "path_equals", "path": "title", "value": "Latencia en checkout"},
            ],
        },
    ),
    task(
        "ops-13",
        "ops",
        "Reconoce el incidente INC-002.",
        "ops",
        "ack_incident",
        {"incident_id": "INC-002"},
        {
            "type": "all",
            "predicates": [
                {"type": "path_equals", "path": "id", "value": "INC-002"},
                {"type": "path_equals", "path": "status", "value": "acknowledged"},
            ],
        },
    ),
    task(
        "ops-14",
        "ops",
        "Resuelve el incidente INC-003.",
        "ops",
        "update_incident",
        {"incident_id": "INC-003", "status": "resolved"},
        {
            "type": "all",
            "predicates": [
                {"type": "path_equals", "path": "id", "value": "INC-003"},
                {"type": "path_equals", "path": "status", "value": "resolved"},
            ],
        },
    ),
    task(
        "ops-15",
        "ops",
        "Reinicia el servicio api.",
        "ops",
        "restart_service",
        {"service": "api"},
        {
            "type": "all",
            "predicates": [
                {"type": "path_equals", "path": "service", "value": "api"},
                {"type": "path_equals", "path": "status", "value": "restarting"},
            ],
        },
        approval="accept",
    ),
    task(
        "neg-01",
        "negative",
        "Traduce este párrafo al francés.",
        None,
        None,
        None,
        {"type": "abstain"},
    ),
    task(
        "neg-02",
        "negative",
        "Genera una imagen de un gato.",
        None,
        None,
        None,
        {"type": "abstain"},
    ),
    task(
        "neg-03",
        "negative",
        "Calcula la cuota de una hipoteca de 200000 euros.",
        None,
        None,
        None,
        {"type": "abstain"},
    ),
    task(
        "neg-04",
        "negative",
        "Envía un correo a María.",
        None,
        None,
        None,
        {"type": "abstain"},
    ),
    task(
        "neg-05",
        "negative",
        "Reserva un vuelo a Tokio.",
        None,
        None,
        None,
        {"type": "abstain"},
    ),
    task(
        "neg-06",
        "negative",
        "Crea una hoja de cálculo con las ventas.",
        None,
        None,
        None,
        {"type": "abstain"},
    ),
    task(
        "neg-07",
        "negative",
        "Resume el PDF adjunto.",
        None,
        None,
        None,
        {"type": "abstain"},
    ),
    task(
        "neg-08",
        "negative",
        "¿Cuál es la capital de Australia?",
        None,
        None,
        None,
        {"type": "abstain"},
    ),
    task(
        "neg-09",
        "negative",
        "Escribe un poema sobre el mar.",
        None,
        None,
        None,
        {"type": "abstain"},
    ),
    task(
        "neg-10",
        "negative",
        "Convierte 10 kilómetros a millas.",
        None,
        None,
        None,
        {"type": "abstain"},
    ),
]


def main() -> None:
    assert len(TASKS) == 60, f"expected 60 tasks, got {len(TASKS)}"
    ids = [item["id"] for item in TASKS]
    assert len(ids) == len(set(ids)), "duplicate task ids"
    counts = {
        block: sum(1 for item in TASKS if item["block"] == block)
        for block in ("docs", "research", "ops", "negative")
    }
    assert counts == {"docs": 20, "research": 15, "ops": 15, "negative": 10}, counts

    lines = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in TASKS]
    TASKS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    gold = [
        json.dumps(
            {"id": item["id"], "gold": item["gold"]},
            ensure_ascii=False,
            sort_keys=True,
        )
        for item in TASKS
    ]
    GOLD_PATH.write_text("\n".join(gold) + "\n", encoding="utf-8")
    digest = hashlib.sha256(TASKS_PATH.read_bytes()).hexdigest()
    HASH_PATH.write_text(f"{digest}  tasks.jsonl\n", encoding="utf-8")
    print(f"wrote {len(TASKS)} tasks; sha256={digest}")


if __name__ == "__main__":
    main()
