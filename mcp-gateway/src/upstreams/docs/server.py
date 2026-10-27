"""docs-mcp: a small HTTP MCP server over a bundled technical corpus."""

from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.upstreams.docs.corpus import DocsCorpus

READ_ONLY = ToolAnnotations(readOnlyHint=True)
corpus = DocsCorpus()

mcp = MCPServer(
    name="docs-mcp",
    title="Docs MCP",
    version="0.1.0",
    instructions="Search and read the bundled technical documentation corpus.",
)


@mcp.tool(annotations=READ_ONLY)
def search_docs(query: str, limit: int = 5) -> dict[str, Any]:
    """Search the documentation corpus with BM25 and return snippets."""
    return {"query": query, "results": corpus.search(query, limit)}


@mcp.tool(annotations=READ_ONLY)
def read_doc(doc_id: str) -> dict[str, Any]:
    """Read one document by id."""
    try:
        document = corpus.read(doc_id)
    except KeyError as exc:
        raise ToolError(str(exc.args[0])) from exc
    return {
        "doc_id": document.id,
        "title": document.title,
        "tags": document.tags,
        "content": document.content,
        "sha256": document.sha256,
    }


@mcp.tool(annotations=READ_ONLY)
def list_docs() -> dict[str, Any]:
    """List every document available in the corpus."""
    documents = corpus.list_documents()
    return {"count": len(documents), "documents": documents}


@mcp.tool(annotations=READ_ONLY)
def outline_doc(doc_id: str) -> dict[str, Any]:
    """Return the heading outline of one document."""
    try:
        outline = corpus.outline(doc_id)
    except KeyError as exc:
        raise ToolError(str(exc.args[0])) from exc
    return {"doc_id": doc_id, "outline": outline}


@mcp.tool(annotations=READ_ONLY)
def cite_doc(doc_id: str) -> dict[str, Any]:
    """Return a stable citation and content hash for one document."""
    try:
        return corpus.cite(doc_id)
    except KeyError as exc:
        raise ToolError(str(exc.args[0])) from exc


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Expose a small health check for Docker Compose."""
    return JSONResponse({"status": "ok", "documents": len(corpus.documents)})


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCP_PORT", "8766")),
    )
