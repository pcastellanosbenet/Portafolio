"""Application settings, loaded from environment variables and ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Environment variables without the ``RAG_`` prefix are accepted where they
    are conventional (``KNX_CORPUS_DIR``, ``OLLAMA_*`` and ``QDRANT_URL``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RAG_",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    corpus_dir: Path = Field(
        default=Path("../RAG-Agent/The KNX Standard v3.0.0"),
        validation_alias=AliasChoices("KNX_CORPUS_DIR", "RAG_CORPUS_DIR"),
    )
    artifacts_dir: Path = Field(default=Path("artifacts"))
    collection_name: str = "knx_v3_0_0"
    manifest_name: str = "manifest.jsonl"
    chunks_name: str = "chunks.jsonl"
    entities_name: str = "entities.jsonl"
    index_meta_name: str = "index_meta.json"

    embedding_backend: str = "transformers"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dimension: int = 384
    embedding_batch_size: int = 16
    embedding_max_length: int = 512

    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    use_reranker: bool = True
    reranker_batch_size: int = 8

    qdrant_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("QDRANT_URL", "RAG_QDRANT_URL"),
    )
    qdrant_path: Path = Field(
        default=Path("artifacts/qdrant"),
        validation_alias=AliasChoices("QDRANT_PATH", "RAG_QDRANT_PATH"),
    )
    qdrant_timeout: int = 60

    chunk_max_words: int = 500
    chunk_overlap_words: int = 80
    chunk_min_words: int = 40

    candidate_k: int = 30
    rerank_k: int = 20
    top_k: int = 8
    max_context_tokens: int = 3000
    rrf_k: int = 60

    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "RAG_OLLAMA_BASE_URL"),
    )
    ollama_model: str = Field(
        default="qwen2.5:1.5b-instruct-q4_K_M",
        validation_alias=AliasChoices("OLLAMA_MODEL", "RAG_OLLAMA_MODEL"),
    )
    ollama_num_ctx: int = Field(
        default=4096,
        validation_alias=AliasChoices("OLLAMA_NUM_CTX", "RAG_OLLAMA_NUM_CTX"),
    )
    ollama_num_predict: int = Field(
        default=300,
        validation_alias=AliasChoices("OLLAMA_NUM_PREDICT", "RAG_OLLAMA_NUM_PREDICT"),
    )
    ollama_num_thread: int = Field(
        default=2,
        validation_alias=AliasChoices("OLLAMA_NUM_THREAD", "RAG_OLLAMA_NUM_THREAD"),
    )
    ollama_timeout: int = 300

    admin_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("RAG_ADMIN_API_KEY", "ADMIN_API_KEY"),
    )
    log_level: str = "INFO"

    @property
    def manifest_path(self) -> Path:
        return self.artifacts_dir / self.manifest_name

    @property
    def chunks_path(self) -> Path:
        return self.artifacts_dir / self.chunks_name

    @property
    def entities_path(self) -> Path:
        return self.artifacts_dir / self.entities_name

    @property
    def index_meta_path(self) -> Path:
        return self.artifacts_dir / self.index_meta_name

    @property
    def effective_qdrant_path(self) -> Path:
        """Keep Qdrant inside the selected artifacts directory.

        ``QDRANT_PATH`` still wins when it is set explicitly.  The default is
        scoped to ``artifacts_dir`` so that commands such as
        ``--artifacts artifacts-demo`` cannot silently write to the real index
        stored in ``artifacts/qdrant``.
        """
        default_path = Path("artifacts/qdrant")
        explicitly_set = "qdrant_path" in self.model_fields_set
        if (
            not explicitly_set
            and self.qdrant_path == default_path
            and self.artifacts_dir != Path("artifacts")
        ):
            return self.artifacts_dir / "qdrant"
        return self.qdrant_path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
