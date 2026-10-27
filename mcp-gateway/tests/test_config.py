"""Tests for environment-backed settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_upstream_names_and_origins_are_parsed() -> None:
    settings = Settings(
        gateway_upstreams="docs, research ,ops",
        gateway_allowed_origins="http://a, http://b",
    )
    assert settings.upstream_names == ["docs", "research", "ops"]
    assert settings.allowed_origins == ["http://a", "http://b"]


def test_invalid_approval_mode_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(gateway_approval_mode="sometimes")


def test_defaults_match_the_plan() -> None:
    settings = Settings()
    assert settings.gateway_router_mode == "hybrid"
    assert settings.gateway_top_k == 8
    assert settings.gateway_max_retries == 2
    assert settings.allowlist == set()
    assert settings.granted_scopes == set()


def test_allowlist_and_scopes_are_parsed() -> None:
    settings = Settings(
        gateway_allowlist="docs__search_docs, ops__list_services",
        gateway_scopes_supported="gateway.call, gateway.admin",
        gateway_granted_scopes="gateway.call",
    )
    assert settings.allowlist == {"docs__search_docs", "ops__list_services"}
    assert settings.scopes_supported == ["gateway.call", "gateway.admin"]
    assert settings.granted_scopes == {"gateway.call"}
