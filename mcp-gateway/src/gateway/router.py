"""Tool routing for static, meta-tool and hybrid disclosure modes."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from mcp.types import Tool

from src.models import ToolDescriptor

MODE_STATIC = "static"
MODE_META = "meta"
MODE_HYBRID = "hybrid"
QUERY_META_KEY = "io.mcp-gateway/query"
FIND_TOOLS_NAME = "find_tools"
INVOKE_TOOL_NAME = "invoke_tool"
FIXED_TOOL_NAMES = frozenset(
    {"docs__list_docs", "ops__list_services", "research__wikipedia_search"}
)

TOKEN_RE = re.compile(r"[a-z0-9áéíóúüñ]+", re.IGNORECASE)
STOPWORDS = {
    "a",
    "al",
    "and",
    "como",
    "con",
    "de",
    "del",
    "el",
    "en",
    "for",
    "la",
    "las",
    "los",
    "of",
    "o",
    "para",
    "por",
    "que",
    "se",
    "the",
    "to",
    "un",
    "una",
    "y",
}

# Small, explicit bilingual expansion for the Spanish evaluation queries.
# It is a lexical baseline aid, not a translation model.
SYNONYMS = {
    "actualiza": ["update"],
    "actualizar": ["update"],
    "articulo": ["arxiv", "paper"],
    "articulos": ["arxiv", "paper"],
    "busca": ["search"],
    "buscar": ["search"],
    "cita": ["cite"],
    "citar": ["cite"],
    "consulta": ["get", "query"],
    "consultar": ["get", "query"],
    "crea": ["create"],
    "crear": ["create"],
    "despliegue": ["deploy"],
    "despliegues": ["deploy"],
    "documentacion": ["documentation", "docs"],
    "documento": ["document", "doc"],
    "documentos": ["document", "docs"],
    "estado": ["status"],
    "guia": ["document", "doc"],
    "historial": ["history"],
    "incidente": ["incident"],
    "incidentes": ["incident"],
    "indice": ["outline"],
    "informacion": ["information"],
    "lee": ["read", "get"],
    "leer": ["read", "get"],
    "lista": ["list"],
    "listar": ["list"],
    "logs": ["logs"],
    "metricas": ["metrics"],
    "muestra": ["list", "get"],
    "pagina": ["page"],
    "paper": ["arxiv"],
    "reconoce": ["ack", "acknowledge"],
    "reconocer": ["ack", "acknowledge"],
    "registros": ["logs"],
    "reinicia": ["restart"],
    "reiniciar": ["restart"],
    "resuelve": ["update", "resolve"],
    "resolver": ["update", "resolve"],
    "servicio": ["service"],
    "servicios": ["service"],
    "wiki": ["wikipedia"],
}
TOOL_HINTS = {
    "search_docs": "buscar search documentacion documents documentation",
    "read_doc": "leer read documento document doc",
    "list_docs": "listar list documentos documents docs",
    "outline_doc": "indice outline documento document",
    "cite_doc": "cita cite documento document",
    "wikipedia_search": "buscar search wikipedia wiki",
    "wikipedia_get": "leer read pagina page wikipedia",
    "arxiv_search": "buscar search arxiv paper articulo",
    "arxiv_get": "leer read arxiv paper articulo",
    "fetch_url": "descargar fetch url",
    "list_services": "listar list servicios services",
    "get_service": "consultar get servicio service estado status",
    "query_metrics": "metricas metrics latencia latency",
    "list_incidents": "listar list incidentes incidents",
    "get_incident": "leer get incidente incident",
    "search_logs": "buscar search logs registros",
    "deploy_history": "despliegues deploys historial history",
    "create_incident": "crear create incidente incident",
    "update_incident": "actualizar update incidente incident estado status",
    "ack_incident": "reconocer ack acknowledge incidente incident",
    "restart_service": "reiniciar restart servicio service",
    "delete_namespace": "borrar delete namespace",
}

FIND_TOOLS = Tool(
    name=FIND_TOOLS_NAME,
    description=(
        "Search the gateway catalog with BM25 and return the best matching tool "
        "definitions. Use this when the needed tool is not in the current list."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language task or keyword."},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 25,
                "default": 8,
            },
        },
        "required": ["query"],
    },
)
INVOKE_TOOL = Tool(
    name=INVOKE_TOOL_NAME,
    description=(
        "Invoke one upstream tool by server and tool name after finding it. "
        "Arguments must match the tool's input schema."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "server": {
                "type": "string",
                "description": "Upstream short name, for example docs, research or ops.",
            },
            "tool": {
                "type": "string",
                "description": "Tool name without the server__ prefix.",
            },
            "arguments": {
                "type": "object",
                "description": "Arguments for the upstream tool.",
                "default": {},
            },
        },
        "required": ["server", "tool"],
    },
)
META_TOOLS = [FIND_TOOLS, INVOKE_TOOL]


def tokenize(text: str) -> list[str]:
    """Tokenize names and descriptions with a small bilingual expansion."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    base = [
        token
        for token in TOKEN_RE.findall(normalized)
        if len(token) > 1 and token not in STOPWORDS
    ]
    expanded: list[str] = []
    for token in base:
        expanded.append(token)
        expanded.extend(SYNONYMS.get(token, []))
    return expanded


def tool_input_text(descriptor: ToolDescriptor) -> str:
    """Build the text indexed for one tool, including parameter names."""
    schema = descriptor.tool.input_schema or {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    parameter_names = " ".join(properties) if isinstance(properties, dict) else ""
    hints = TOOL_HINTS.get(descriptor.original_name, "")
    return (
        f"{descriptor.name} {descriptor.original_name} "
        f"{descriptor.tool.description or ''} {parameter_names} {hints}"
    )


@dataclass(frozen=True)
class RouteDecision:
    """Tools exposed for one listing and the scores behind a hybrid choice."""

    mode: str
    tools: list[Tool]
    descriptors: list[ToolDescriptor]
    query: str | None
    scores: dict[str, float]
    fallback: bool = False


class ToolRouter:
    """Select tool definitions with a deterministic BM25 baseline."""

    def __init__(self, mode: str = MODE_HYBRID, top_k: int = 8) -> None:
        if mode not in {MODE_STATIC, MODE_META, MODE_HYBRID}:
            raise ValueError(f"unknown router mode: {mode}")
        self.mode = mode
        self.top_k = max(1, min(top_k, 25))

    def rank(
        self, query: str, descriptors: list[ToolDescriptor], limit: int | None = None
    ) -> tuple[list[ToolDescriptor], dict[str, float]]:
        """Return the best lexical matches and their BM25 scores."""
        tokens = tokenize(query)
        if not tokens or not descriptors:
            return [], {}
        from rank_bm25 import BM25Okapi

        corpus = [tokenize(tool_input_text(descriptor)) for descriptor in descriptors]
        scores = BM25Okapi(corpus).get_scores(tokens)
        ranked = sorted(
            zip(descriptors, scores, strict=True),
            key=lambda item: (-float(item[1]), item[0].name),
        )
        selected = [
            descriptor for descriptor, score in ranked[: max(1, min(limit or self.top_k, 25))]
            if score > 0
        ]
        score_map = {
            descriptor.name: round(float(score), 4)
            for descriptor, score in ranked
            if score > 0
        }
        return selected, score_map

    def route(
        self,
        query: str | None,
        descriptors: list[ToolDescriptor],
    ) -> RouteDecision:
        """Return the tool set for one listing request."""
        if self.mode == MODE_STATIC:
            return RouteDecision(
                mode=self.mode,
                tools=[descriptor.tool for descriptor in descriptors],
                descriptors=list(descriptors),
                query=query,
                scores={},
            )
        if self.mode == MODE_META:
            return RouteDecision(
                mode=self.mode,
                tools=list(META_TOOLS),
                descriptors=[],
                query=query,
                scores={},
            )

        ranked: list[ToolDescriptor] = []
        scores: dict[str, float] = {}
        if query:
            ranked, scores = self.rank(query, descriptors, self.top_k)
        fixed = [d for d in descriptors if d.name in FIXED_TOOL_NAMES]
        selected: list[ToolDescriptor] = []
        seen: set[str] = set()
        for descriptor in [*fixed, *ranked]:
            if descriptor.name not in seen:
                seen.add(descriptor.name)
                selected.append(descriptor)
        tools = [descriptor.tool for descriptor in selected] + list(META_TOOLS)
        return RouteDecision(
            mode=self.mode,
            tools=tools,
            descriptors=selected,
            query=query,
            scores=scores,
            fallback=bool(query and not ranked),
        )


def count_tool_tokens(tools: list[Tool]) -> int:
    """Count tokens in serialized tool definitions with a documented tokenizer.

    The fallback keeps offline CI working when the tokenizer data is not cached.
    """
    import tiktoken

    payload = json.dumps(
        [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools],
        ensure_ascii=False,
    )
    try:
        encoding = tiktoken.get_encoding("o200k_base")
    except Exception:  # noqa: BLE001 - tokenizer download is optional for offline CI
        return max(1, len(payload) // 4)
    return len(encoding.encode(payload))


def find_tools_payload(
    router: ToolRouter,
    query: str,
    descriptors: list[ToolDescriptor],
    limit: int = 8,
) -> dict[str, Any]:
    """Build the structured payload returned by the `find_tools` meta-tool."""
    matches, scores = router.rank(query, descriptors, limit)
    tools = [
        {
            "name": descriptor.name,
            "description": descriptor.tool.description,
            "input_schema": descriptor.tool.input_schema,
            "score": scores.get(descriptor.name, 0.0),
        }
        for descriptor in matches
    ]
    return {
        "query": query,
        "tools": tools,
        "tool_tokens": count_tool_tokens(
            [descriptor.tool for descriptor in matches]
        ),
    }
