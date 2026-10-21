"""FastAPI entry point for the local KNX RAG assistant."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.schemas import (
    DocumentSummary,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    ReloadResponse,
)
from src.agent import KNXAgent
from src.answer import AnswerService
from src.config import Settings, get_settings
from src.embeddings import get_embedder
from src.entities import EntityCatalog
from src.index import QdrantIndex
from src.llm import OllamaClient
from src.manifest import load_manifest
from src.models import DocumentInfo
from src.rerank import get_reranker
from src.retrieve import ChunkStore, Retriever

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


def _build_agent(settings: Settings) -> tuple[KNXAgent, ChunkStore, list[DocumentInfo]]:
    store = ChunkStore.load(settings.chunks_path)
    documents = load_manifest(settings.manifest_path)
    if not store.chunks:
        raise RuntimeError(
            f"No hay chunks en {settings.chunks_path}. Ejecuta `python -m src.ingest`."
        )
    embedder = get_embedder(settings)
    index = QdrantIndex(
        settings.collection_name,
        url=settings.qdrant_url,
        path=str(settings.effective_qdrant_path) if not settings.qdrant_url else None,
        timeout=settings.qdrant_timeout,
    )
    retriever = Retriever(
        store,
        index,
        embedder,
        get_reranker(settings),
        rrf_k=settings.rrf_k,
        candidate_k=settings.candidate_k,
        rerank_k=settings.rerank_k,
        top_k=settings.top_k,
    )
    llm = OllamaClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        num_ctx=settings.ollama_num_ctx,
        num_predict=settings.ollama_num_predict,
        num_thread=settings.ollama_num_thread,
        timeout=settings.ollama_timeout,
    )
    answer_service = AnswerService(llm, max_context_tokens=settings.max_context_tokens)
    agent = KNXAgent(
        retriever,
        answer_service,
        EntityCatalog.load(settings.entities_path),
        top_k=settings.top_k,
        max_context_tokens=settings.max_context_tokens,
    )
    return agent, store, documents


def _load_resources(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    app.state.agent = None
    app.state.store = None
    app.state.documents = []
    app.state.ready = False
    app.state.ollama_available = False
    try:
        agent, store, documents = _build_agent(settings)
    except Exception as error:
        logger.warning("No se pudo cargar el índice: %s", error)
        app.state.load_error = str(error)
        return
    app.state.agent = agent
    app.state.store = store
    app.state.documents = documents
    app.state.ready = True
    app.state.load_error = None
    llm = getattr(agent.answer_service, "llm", None)
    app.state.ollama_available = bool(llm and llm.health())


def create_app(
    settings: Settings | None = None,
    *,
    agent: KNXAgent | None = None,
    store: ChunkStore | None = None,
    documents: list[DocumentInfo] | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if agent is not None:
            app.state.agent = agent
            app.state.store = store
            app.state.documents = documents or []
            app.state.ready = True
            app.state.load_error = None
            app.state.ollama_available = False
        else:
            _load_resources(app)
        yield

    app = FastAPI(
        title="KNX RAG Assistant",
        description="Asistente local con citas sobre el estándar KNX v3.0.0.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def require_ready() -> KNXAgent:
        if not getattr(app.state, "ready", False) or app.state.agent is None:
            detail = getattr(app.state, "load_error", None) or (
                "El índice no está cargado. Ejecuta la ingesta y vuelve a intentarlo."
            )
            raise HTTPException(status_code=503, detail=detail)
        return app.state.agent

    def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
        if settings.admin_api_key and x_admin_key != settings.admin_api_key:
            raise HTTPException(status_code=401, detail="Credencial de administración inválida.")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        ready = bool(getattr(app.state, "ready", False))
        return HealthResponse(
            status="ok" if ready else "degraded",
            chunks=len(app.state.store.chunks) if app.state.store else 0,
            collection=settings.collection_name,
            embedding_model=settings.embedding_model,
            reranker_model=settings.reranker_model if settings.use_reranker else None,
            llm_model=settings.ollama_model,
            ollama_available=bool(getattr(app.state, "ollama_available", False)),
            artifacts_ready=settings.chunks_path.exists(),
        )

    @app.post("/v1/query", response_model=QueryResponse)
    def query(
        request: QueryRequest,
        active_agent: KNXAgent = Depends(require_ready),  # noqa: B008
    ) -> QueryResponse:
        try:
            answer = active_agent.run(
                request.question,
                filters=request.filters.to_search_filters(),
                top_k=request.top_k,
            )
        except Exception as error:  # pragma: no cover - defensive API boundary
            logger.exception("Error procesando la consulta")
            raise HTTPException(status_code=500, detail=str(error)) from error
        return QueryResponse.from_agent_answer(answer)

    @app.get("/v1/documents", response_model=list[DocumentSummary])
    def list_documents(
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> list[DocumentSummary]:
        return [
            DocumentSummary.from_document(document)
            for document in app.state.documents[offset : offset + limit]
        ]

    @app.get("/v1/documents/{doc_id}", response_model=DocumentSummary)
    def document(doc_id: str) -> DocumentSummary:
        for item in app.state.documents:
            if item.doc_id == doc_id:
                return DocumentSummary.from_document(item)
        raise HTTPException(status_code=404, detail="Documento no encontrado.")

    @app.post(
        "/v1/admin/reload",
        response_model=ReloadResponse,
        dependencies=[Depends(require_admin_key)],
    )
    def reload() -> ReloadResponse:
        _load_resources(app)
        if not getattr(app.state, "ready", False):
            raise HTTPException(
                status_code=503,
                detail=getattr(app.state, "load_error", "No se pudo recargar el índice."),
            )
        return ReloadResponse(
            status="ok",
            chunks=len(app.state.store.chunks) if app.state.store else 0,
        )

    return app


app = create_app()
