# Conformidad con MCP `2026-07-28`

> **Última revisión:** 2026-10-26.
> **SDK:** `mcp==2.3.0`, `mcp-types==2.3.0`.
> **Alcance:** gateway y servidor de spike. Las filas marcadas como *Parcial* o
> *Pendiente* no se presentan como conformidad completa.

## Cómo se ejecuta

```bash
cd mcp-gateway
.venv/bin/pytest tests/conformance -q
.venv/bin/pytest -q
```

La suite HTTP arranca Uvicorn en un puerto efímero, sin red externa ni claves.

## Matriz

| # | Requisito | Estado | Evidencia |
| ---: | :--- | :--- | :--- |
| 1 | `server/discover` devuelve versiones, capacidades e identidad | Verde | `test_server_discover` |
| 2 | Cada petición lleva `_meta` con versión y capacidades del cliente | Verde | El cliente del SDK lo envía; las peticiones de conformidad lo incluyen y el servidor rechaza versiones no soportadas |
| 3 | No se emite ni se exige `Mcp-Session-Id` | Verde | `test_modern_requests_do_not_create_sessions` |
| 4 | `MCP-Protocol-Version` validado contra el cuerpo | Verde | `test_unsupported_version_is_rejected`, `test_header_mismatch_is_rejected` |
| 5 | `Mcp-Method` y `Mcp-Name` validados; `-32020` si no coinciden | Verde | `test_header_mismatch_is_rejected` |
| 6 | Versión no soportada devuelve `-32022` | Verde | `test_unsupported_version_is_rejected` |
| 7 | Método desconocido devuelve `404` + `-32601` | Verde | `test_unknown_method_returns_method_not_found` |
| 8 | `GET` y `DELETE` sobre el endpoint MCP devuelven `405` | Verde | `test_get_and_delete_are_rejected` |
| 9 | `Accept` negocia JSON y `text/event-stream` | Parcial | El SDK acepta ambos; no hay un test dedicado a un `Accept` inválido |
| 10 | Notificaciones de progreso en el stream de la petición | Verde | `test_progress_events_reach_the_client`, spike HTTP |
| 11 | Cerrar el stream cancela el trabajo en el upstream | Verde | `test_cancellation_propagates_to_the_upstream`, spike HTTP |
| 12 | `subscriptions/listen` confirma y entrega `tools/list_changed` | Parcial | Verificado en el spike; el gateway aún no publica cambios de catálogo |
| 13 | `tools/list` incluye `ttlMs` y `cacheScope` | Verde | `test_tools_list_is_deterministic_and_cacheable` |
| 14 | `tools/list` es determinista y cacheable | Verde | `test_tools_list_is_deterministic_and_cacheable` |
| 15 | MRTR: aprobación con `InputRequiredResult`, reintento y `request_state` | Verde | `test_destructive_tool_runs_after_mrtr_approval`, `test_destructive_tool_is_denied_when_user_declines`; token HMAC con TTL, binding a definición y argumentos |
| 16 | `Origin` inválido devuelve `403` | Verde | `test_invalid_origin_is_rejected` |
| 17 | Compatibilidad legacy documentada y probada | Parcial | Observada en el spike; falta un test con `Client(..., mode="legacy")` |

## Resultado actual

- **83 tests** en total, todos en verde.
- **10 tests** de conformidad HTTP.
- **1 test** de integración con los tres upstreams reales: `docs-mcp` y `ops-mcp` por
  HTTP, `research-mcp` por stdio.
- **7 tests** de router (`static`, `meta`, `hybrid`) y **6 tests** de evaluación
  (predicados, unwrapping, corpus congelado).
- `ruff check src tests scripts eval` limpio.
- El gateway arranca con los tres upstreams, descubre **22 herramientas** y responde por
  Streamable HTTP y por stdio.
- `docker compose up --build -d` levanta los tres servicios; `/health` confirma
  `docs` 5, `research` 5 y `ops` 12 herramientas.
- Smoke determinista de cinco tareas: **5/5** correctas, con traza en
  `docs/examples/smoke.json`.
- MRTR probado con el cliente moderno: aprobación, rechazo, `requestState` firmado y
  auditoría `approval_pending` / `approval_denied` / `ok`.
- A/B/C reales con `openai/gpt-oss-120b`: estática 58,33% de éxito, meta 50,00% e
  híbrida 63,33%; los detalles están en `docs/evaluation.md`.
- Suite de seguridad: 14/14 ataques bloqueados, 20/20 peticiones benignas permitidas y
  0 falsos positivos; informe en `security/results/2026-10-26-suite.json`.

## Comportamiento legacy observado

El SDK sirve a la vez clientes de 2025 y de 2026. Si una petición no lleva
`MCP-Protocol-Version`, o lleva `2025-11-25`, el servidor entra por la ruta legacy y
responde `400 Missing session ID` hasta que el cliente hace `initialize`.

Consecuencias:

- Las comprobaciones de `2026-07-28` deben enviar la cabecera de versión.
- `GET`/`DELETE` solo devuelven `405` cuando la petición se enruta por la era moderna;
  sin cabecera caen en la ruta legacy y devuelven `400`.
- Esto es comportamiento del SDK, no del gateway, y está documentado en
  `docs/spike.md`.

## Pendiente para las siguientes fases

1. `subscriptions/listen` emitido por el gateway al refrescar el catálogo (Fase 2/4).
2. Test explícito de negociación de `Accept` y de `Client(mode="legacy")`.
3. Re-aprobación automática cuando cambia el hash de una definición (Fase 4).
4. Ampliar la matriz de conformidad a los tres upstreams reales y al modo bearer (Fase 4).
