"""Deterministic synthetic state for ops-mcp."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

NOW = "2026-10-26T12:00:00Z"


@dataclass
class Service:
    """Synthetic service state."""

    name: str
    status: str
    replicas: int
    version: str
    latency_p95_ms: int
    error_rate: float
    generation: int = 1
    note: str = ""


@dataclass
class Incident:
    """Synthetic incident record."""

    id: str
    title: str
    service: str
    severity: str
    status: str
    created_at: str
    notes: str = ""


@dataclass
class OpsState:
    """Mutable in-memory state, reset when the server starts."""

    services: dict[str, Service] = field(
        default_factory=lambda: {
            "api": Service("api", "degraded", 4, "2.8.1", 420, 0.031, note="timeouts"),
            "worker": Service("worker", "ok", 3, "1.14.0", 180, 0.004),
            "scheduler": Service("scheduler", "ok", 1, "0.9.3", 45, 0.001),
            "db": Service("db", "ok", 2, "16.4", 22, 0.0005, note="high connections"),
            "cache": Service("cache", "degraded", 2, "7.2.4", 9, 0.012, note="low hit rate"),
        }
    )
    incidents: list[Incident] = field(
        default_factory=lambda: [
            Incident(
                "INC-001",
                "Latencia elevada en api",
                "api",
                "sev1",
                "open",
                "2026-10-26T10:12:00Z",
                "p95 por encima de 400 ms",
            ),
            Incident(
                "INC-002",
                "Timeout al procesar la cola",
                "worker",
                "sev2",
                "acknowledged",
                "2026-10-26T09:40:00Z",
                "reintentos en curso",
            ),
            Incident(
                "INC-003",
                "Job retrasado",
                "scheduler",
                "sev3",
                "open",
                "2026-10-25T22:05:00Z",
            ),
            Incident(
                "INC-004",
                "Conexiones agotadas",
                "db",
                "sev1",
                "resolved",
                "2026-10-25T18:20:00Z",
                "pool ampliado",
            ),
            Incident(
                "INC-005",
                "Tasa de aciertos baja",
                "cache",
                "sev2",
                "open",
                "2026-10-26T08:15:00Z",
            ),
            Incident(
                "INC-006",
                "Despliegue fallido",
                "api",
                "sev3",
                "resolved",
                "2026-10-24T16:00:00Z",
                "rollback completado",
            ),
        ]
    )
    logs: dict[str, list[str]] = field(
        default_factory=lambda: {
            "api": [
                "2026-10-26T11:58:00Z request timeout after 5000ms path=/checkout",
                "2026-10-26T11:57:12Z upstream connection refused host=db",
                "2026-10-26T11:56:40Z latency p95=438ms route=/orders",
                "2026-10-26T11:55:03Z deploy version=2.8.1 status=completed",
                "2026-10-26T11:54:20Z circuit breaker open target=payments",
                "2026-10-26T11:52:11Z request timeout after 5000ms path=/search",
            ],
            "worker": [
                "2026-10-26T11:59:00Z queue depth=182",
                "2026-10-26T11:58:30Z job retry attempt=2 id=job-441",
                "2026-10-26T11:57:50Z connection refused host=redis",
                "2026-10-26T11:56:10Z task completed duration=3100ms",
                "2026-10-26T11:55:00Z deploy version=1.14.0 status=completed",
            ],
            "scheduler": [
                "2026-10-26T11:45:00Z job delayed 240s name=nightly-report",
                "2026-10-26T11:30:00Z job started name=cleanup",
                "2026-10-26T11:00:00Z job completed name=cleanup duration=12s",
            ],
            "db": [
                "2026-10-26T11:50:00Z connection pool exhausted active=100 max=100",
                "2026-10-26T11:49:30Z slow query duration=4200ms table=orders",
                "2026-10-26T11:48:00Z checkpoint completed",
                "2026-10-26T11:40:00Z connection refused from api",
            ],
            "cache": [
                "2026-10-26T11:59:30Z cache miss key=session:8812",
                "2026-10-26T11:59:00Z hit rate=0.61 threshold=0.85",
                "2026-10-26T11:58:00Z eviction count=420",
                "2026-10-26T11:57:00Z connection refused host=cache-2",
            ],
        }
    )
    deploys: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            "api": [
                {"version": "2.8.1", "status": "completed", "at": "2026-10-26T11:55:00Z"},
                {"version": "2.8.0", "status": "completed", "at": "2026-10-24T15:00:00Z"},
                {"version": "2.7.9", "status": "failed", "at": "2026-10-23T12:00:00Z"},
            ],
            "worker": [
                {"version": "1.14.0", "status": "completed", "at": "2026-10-26T11:55:00Z"},
                {"version": "1.13.8", "status": "completed", "at": "2026-10-22T10:00:00Z"},
            ],
            "scheduler": [
                {"version": "0.9.3", "status": "completed", "at": "2026-10-20T09:00:00Z"},
            ],
            "db": [
                {"version": "16.4", "status": "completed", "at": "2026-10-18T08:00:00Z"},
            ],
            "cache": [
                {"version": "7.2.4", "status": "completed", "at": "2026-10-21T14:00:00Z"},
            ],
        }
    )
    namespaces: dict[str, str] = field(
        default_factory=lambda: {
            "staging": "active",
            "demo": "active",
            "legacy": "archived",
        }
    )
    _incident_counter: int = 6

    def list_services(self) -> list[dict[str, Any]]:
        """Return every service."""
        return [asdict(service) for service in self.services.values()]

    def get_service(self, name: str) -> dict[str, Any]:
        """Return one service."""
        return asdict(self._service(name))

    def _service(self, name: str) -> Service:
        if name not in self.services:
            raise ValueError(f"unknown service: {name}")
        return self.services[name]

    def query_metrics(self, name: str, window_minutes: int = 15) -> dict[str, Any]:
        """Return a deterministic metric series for a service."""
        service = self._service(name)
        window = max(5, min(window_minutes, 60))
        base = max(5, service.latency_p95_ms // 3)
        points = []
        for index in range(window):
            latency = base + (index % 4) * 9 + (20 if service.status != "ok" else 0)
            error_rate = round(service.error_rate * (1 + (index % 3) * 0.15), 5)
            points.append(
                {
                    "minute": f"T-{window - index - 1}",
                    "latency_p95_ms": latency,
                    "error_rate": error_rate,
                }
            )
        return {"service": name, "window_minutes": window, "points": points}

    def list_incidents(self, status: str | None = None) -> list[dict[str, Any]]:
        """Return incidents, optionally filtered by status."""
        incidents = self.incidents
        if status is not None:
            incidents = [incident for incident in incidents if incident.status == status]
        return [asdict(incident) for incident in incidents]

    def get_incident(self, incident_id: str) -> dict[str, Any]:
        """Return one incident."""
        for incident in self.incidents:
            if incident.id == incident_id:
                return asdict(incident)
        raise ValueError(f"unknown incident: {incident_id}")

    def search_logs(self, name: str, query: str = "", limit: int = 10) -> dict[str, Any]:
        """Search synthetic logs for a service."""
        self._service(name)
        needle = query.lower().strip()
        matches = [
            line
            for line in self.logs.get(name, [])
            if not needle or needle in line.lower()
        ]
        return {
            "service": name,
            "query": query,
            "matches": matches[-max(1, min(limit, 20)) :],
        }

    def deploy_history(self, name: str, limit: int = 5) -> dict[str, Any]:
        """Return recent deploys for a service."""
        self._service(name)
        return {
            "service": name,
            "deploys": self.deploys.get(name, [])[: max(1, min(limit, 10))],
        }

    def create_incident(self, title: str, name: str, severity: str) -> dict[str, Any]:
        """Create a new incident and return it."""
        self._service(name)
        if severity not in {"sev1", "sev2", "sev3"}:
            raise ValueError(f"unknown severity: {severity}")
        self._incident_counter += 1
        incident = Incident(
            id=f"INC-{self._incident_counter:03d}",
            title=title,
            service=name,
            severity=severity,
            status="open",
            created_at=NOW,
            notes="created by ops-mcp",
        )
        self.incidents.append(incident)
        return asdict(incident)

    def update_incident(self, incident_id: str, status: str) -> dict[str, Any]:
        """Update an incident status."""
        if status not in {"open", "acknowledged", "resolved"}:
            raise ValueError(f"unknown incident status: {status}")
        for incident in self.incidents:
            if incident.id == incident_id:
                incident.status = status
                return asdict(incident)
        raise ValueError(f"unknown incident: {incident_id}")

    def ack_incident(self, incident_id: str) -> dict[str, Any]:
        """Acknowledge an incident."""
        return self.update_incident(incident_id, "acknowledged")

    def restart_service(self, name: str) -> dict[str, Any]:
        """Restart a service and bump its generation."""
        service = self._service(name)
        service.status = "restarting"
        service.generation += 1
        return {"service": name, "status": service.status, "generation": service.generation}

    def delete_namespace(self, namespace: str) -> dict[str, Any]:
        """Mark a namespace as deleted."""
        if namespace not in self.namespaces:
            raise ValueError(f"unknown namespace: {namespace}")
        if self.namespaces[namespace] == "deleted":
            raise ValueError(f"namespace already deleted: {namespace}")
        self.namespaces[namespace] = "deleted"
        return {"namespace": namespace, "status": "deleted"}
