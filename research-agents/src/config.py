"""Runtime configuration for the multi-agent research team."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["groq", "gemini"]
SearchBackend = Literal["live", "frozen"]
SearchPrimary = Literal["tavily", "duckduckgo", "frozen"]
SearchFallback = Literal["duckduckgo", "none"]
StructuredMethod = Literal["json_schema", "function_calling", "json_mode"]

PROVIDER_BASE_URLS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}


class Settings(BaseSettings):
    """Settings loaded from environment variables and ``.env``.

    The provider and model are intentionally top-level settings so that a new
    run can switch providers by editing a single block in ``.env``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    llm_provider: Provider = "groq"
    llm_model: str = ""
    llm_fast_model: str = ""
    llm_fallback_provider: Provider | None = None
    llm_fallback_model: str = ""
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_timeout_s: float = Field(default=90.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0, le=10)
    llm_structured_method: StructuredMethod = "function_calling"
    llm_tpm_limit: int = Field(default=8_000, ge=0)
    llm_tpm_window_s: float = Field(default=60.0, gt=0)
    llm_max_output_tokens: int = Field(default=3_000, ge=128)
    llm_tool_fallback: bool = False

    judge_provider: Provider | None = Field(
        default=None,
        validation_alias=AliasChoices("RESEARCH_JUDGE_PROVIDER", "JUDGE_PROVIDER"),
    )
    judge_model: str = Field(
        default="",
        validation_alias=AliasChoices("RESEARCH_JUDGE_MODEL", "JUDGE_MODEL"),
    )
    judge_max_output_tokens: int = Field(
        default=1_200,
        ge=128,
        validation_alias=AliasChoices(
            "RESEARCH_JUDGE_MAX_OUTPUT_TOKENS",
            "JUDGE_MAX_OUTPUT_TOKENS",
        ),
    )
    judge_max_retries: int = Field(
        default=1,
        ge=0,
        le=5,
        validation_alias=AliasChoices(
            "RESEARCH_JUDGE_MAX_RETRIES",
            "JUDGE_MAX_RETRIES",
        ),
    )

    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None

    search_backend: SearchBackend = Field(
        default="live",
        validation_alias=AliasChoices("RESEARCH_SEARCH_BACKEND", "SEARCH_BACKEND"),
    )
    search_primary: SearchPrimary = Field(
        default="tavily",
        validation_alias=AliasChoices("RESEARCH_SEARCH_PRIMARY", "SEARCH_PRIMARY"),
    )
    search_fallback: SearchFallback = Field(
        default="duckduckgo",
        validation_alias=AliasChoices("RESEARCH_SEARCH_FALLBACK", "SEARCH_FALLBACK"),
    )
    tavily_monthly_budget: int = Field(
        default=1000,
        ge=1,
        validation_alias=AliasChoices(
            "RESEARCH_TAVILY_MONTHLY_BUDGET",
            "TAVILY_MONTHLY_BUDGET",
        ),
    )
    tavily_search_depth: Literal["basic", "advanced"] = "basic"
    wikipedia_lang: str = "es"
    cache_ttl_s: int = Field(
        default=86_400,
        ge=60,
        validation_alias=AliasChoices("RESEARCH_CACHE_TTL_S", "CACHE_TTL_S"),
    )
    http_timeout_s: float = Field(
        default=20.0,
        gt=0,
        validation_alias=AliasChoices("RESEARCH_HTTP_TIMEOUT_S", "HTTP_TIMEOUT_S"),
    )
    http_max_bytes: int = Field(
        default=2_000_000,
        ge=10_000,
        validation_alias=AliasChoices("RESEARCH_HTTP_MAX_BYTES", "HTTP_MAX_BYTES"),
    )
    fetch_max_chars: int = Field(
        default=12_000,
        ge=1_000,
        validation_alias=AliasChoices("RESEARCH_FETCH_MAX_CHARS", "FETCH_MAX_CHARS"),
    )
    search_max_results: int = Field(
        default=5,
        ge=1,
        le=10,
        validation_alias=AliasChoices("RESEARCH_SEARCH_MAX_RESULTS", "SEARCH_MAX_RESULTS"),
    )
    search_max_retries: int = Field(
        default=1,
        ge=0,
        le=3,
        validation_alias=AliasChoices("RESEARCH_SEARCH_MAX_RETRIES", "SEARCH_MAX_RETRIES"),
    )
    frozen_corpus_path: Path = Field(
        default=Path("eval/frozen/corpus.json"),
        validation_alias=AliasChoices("RESEARCH_FROZEN_CORPUS_PATH", "FROZEN_CORPUS_PATH"),
    )
    db_path: Path = Field(
        default=Path("artifacts/research.db"),
        validation_alias=AliasChoices("RESEARCH_DB_PATH", "DB_PATH"),
    )
    checkpoint_path: Path = Field(
        default=Path("artifacts/checkpoints.db"),
        validation_alias=AliasChoices("RESEARCH_CHECKPOINT_PATH", "CHECKPOINT_PATH"),
    )
    max_llm_calls: int = Field(
        default=30,
        ge=1,
        validation_alias=AliasChoices("RESEARCH_MAX_LLM_CALLS", "MAX_LLM_CALLS"),
    )
    max_tokens: int = Field(
        default=60_000,
        ge=1_000,
        validation_alias=AliasChoices("RESEARCH_MAX_TOKENS", "MAX_TOKENS"),
    )
    max_rounds: int = Field(
        default=2,
        ge=1,
        le=5,
        validation_alias=AliasChoices("RESEARCH_MAX_ROUNDS", "MAX_ROUNDS"),
    )
    max_workers: int = Field(
        default=3,
        ge=1,
        le=5,
        validation_alias=AliasChoices("RESEARCH_MAX_WORKERS", "MAX_WORKERS"),
    )
    max_tool_steps: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias=AliasChoices("RESEARCH_MAX_TOOL_STEPS", "MAX_TOOL_STEPS"),
    )
    hitl: bool = Field(
        default=False,
        validation_alias=AliasChoices("RESEARCH_HITL", "HITL"),
    )

    @field_validator("llm_fallback_provider", "judge_provider", mode="before")
    @classmethod
    def _empty_provider_is_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @model_validator(mode="after")
    def _validate_model_names(self) -> Settings:
        if not self.llm_model.strip():
            raise ValueError(
                "LLM_MODEL is required. Set it in .env to a model supported by LLM_PROVIDER."
            )
        if self.llm_fallback_provider and not self.llm_fallback_model.strip():
            raise ValueError(
                "LLM_FALLBACK_MODEL is required when LLM_FALLBACK_PROVIDER is set."
            )
        if (
            self.judge_provider
            and self.judge_provider != self.llm_provider
            and not self.judge_model.strip()
        ):
            raise ValueError(
                "JUDGE_MODEL is required when JUDGE_PROVIDER differs from LLM_PROVIDER."
            )
        return self

    @property
    def fast_model(self) -> str:
        """Return the configured fast model or fall back to the main model."""
        return self.llm_fast_model.strip() or self.llm_model

    @property
    def judge_target(self) -> tuple[Provider, str]:
        """Return the provider and model used by the independent judge."""
        provider = self.judge_provider or self.llm_provider
        model = self.judge_model.strip() or self.fast_model
        return provider, model

    def has_api_key_for(self, provider: Provider) -> bool:
        key = self.groq_api_key if provider == "groq" else self.gemini_api_key
        return key is not None and bool(key.get_secret_value().strip())

    def api_key_for(self, provider: Provider) -> SecretStr:
        key = self.groq_api_key if provider == "groq" else self.gemini_api_key
        if key is None or not key.get_secret_value().strip():
            env_name = "GROQ_API_KEY" if provider == "groq" else "GEMINI_API_KEY"
            raise ValueError(
                f"{env_name} is not set. Add it to .env before using provider '{provider}'."
            )
        return key

    def base_url_for(self, provider: Provider) -> str:
        return PROVIDER_BASE_URLS[provider]

    @property
    def primary_api_key(self) -> SecretStr:
        return self.api_key_for(self.llm_provider)

    @property
    def fallback_api_key(self) -> SecretStr | None:
        if self.llm_fallback_provider is None:
            return None
        return self.api_key_for(self.llm_fallback_provider)

    def ensure_runtime_dirs(self) -> None:
        """Create local runtime directories without touching tracked files."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
