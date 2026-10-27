"""Configuration for the MCP gateway and its upstreams."""

import sys
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables and an optional `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    gateway_host: str = "127.0.0.1"
    gateway_port: int = Field(default=8765, ge=1, le=65535)
    gateway_public_url: str = "http://127.0.0.1:8765/mcp"
    gateway_allowed_origins: str = "http://127.0.0.1:8765"
    gateway_auth_mode: Literal["none", "bearer"] = "none"
    gateway_token: str = ""
    gateway_allowlist: str = ""
    gateway_scopes_supported: str = "gateway.call"
    gateway_required_scope: str = ""
    gateway_granted_scopes: str = ""
    gateway_upstreams: str = "docs,research,ops"
    gateway_router_mode: Literal["static", "meta", "hybrid"] = "hybrid"
    gateway_top_k: int = Field(default=8, ge=1, le=25)
    gateway_approval_mode: Literal["auto", "always", "risk"] = "risk"
    gateway_approval_secret: str = ""
    gateway_approval_ttl_s: int = Field(default=300, ge=30, le=3600)
    gateway_db_path: str = "artifacts/gateway.db"
    gateway_max_output_bytes: int = Field(default=32768, ge=1024)
    gateway_request_timeout_s: float = Field(default=30.0, gt=0)
    gateway_upstream_timeout_s: float = Field(default=20.0, gt=0)
    gateway_max_retries: int = Field(default=2, ge=0, le=5)

    docs_mcp_url: str = "http://127.0.0.1:8766/mcp"
    ops_mcp_url: str = "http://127.0.0.1:8767/mcp"
    research_mcp_command: str = f"{sys.executable} -m src.upstreams.research.server"

    llm_provider: Literal["groq"] = "groq"
    llm_model: str = ""
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    groq_api_key: str = ""

    @property
    def upstream_names(self) -> list[str]:
        """Return the configured upstream names in declaration order."""
        return [name.strip() for name in self.gateway_upstreams.split(",") if name.strip()]

    @property
    def allowed_origins(self) -> list[str]:
        """Return the configured CORS/Origin allowlist."""
        return [
            origin.strip()
            for origin in self.gateway_allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def allowlist(self) -> set[str]:
        """Return the optional tool allowlist."""
        return {
            name.strip()
            for name in self.gateway_allowlist.split(",")
            if name.strip()
        }

    @property
    def scopes_supported(self) -> list[str]:
        """Return the scopes advertised by the protected-resource metadata."""
        return [
            scope.strip()
            for scope in self.gateway_scopes_supported.split(",")
            if scope.strip()
        ]

    @property
    def granted_scopes(self) -> set[str]:
        """Return the scopes granted by the lab bearer token."""
        return {
            scope.strip()
            for scope in self.gateway_granted_scopes.split(",")
            if scope.strip()
        }


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
