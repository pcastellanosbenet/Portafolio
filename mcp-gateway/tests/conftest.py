"""Shared test fixtures."""

from __future__ import annotations

import pytest

from src.config import Settings
from src.gateway.audit import AuditLog
from src.gateway.policy import PolicyEngine
from src.gateway.server import Gateway
from tests.fakes import FakeUpstream


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gateway_db_path=":memory:",
        gateway_max_retries=1,
        gateway_upstream_timeout_s=1.0,
        gateway_max_output_bytes=2048,
        gateway_approval_mode="auto",
        gateway_router_mode="static",
    )


@pytest.fixture
async def gateway(settings: Settings):
    upstream = FakeUpstream("docs")
    instance = Gateway(
        settings,
        {"docs": upstream},
        audit=AuditLog(":memory:"),
        policy=PolicyEngine("auto"),
    )
    await instance.start()
    yield instance, upstream
    await instance.stop()
