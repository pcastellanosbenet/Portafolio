# Arquitectura

> **Protocolo:** MCP `2026-07-28` · **SDK:** `mcp==2.3.0` · **Runtime:** Python 3.12.

## Vista de componentes

```text
                       ┌──────────────────────────────┐
                       │ host CLI / evaluación         │
                       │ Client MCP + approvals        │
                       └──────────────┬───────────────┘
                                      │ Streamable HTTP o stdio
                       ┌──────────────▼───────────────┐
                       │ gateway                       │
                       │                               │
  ┌────────────────────┤ Catalog ── Router ── Policy   │
  │                    │    │          │         │     │
  │                    │ Executor ── Audit ── Auth     │
  │                    └──────┬───────────┬───────────┘
  │                           │           │
  │                    HTTP   │           │ stdio
  ▼                           ▼           ▼
docs-mcp                ops-mcp      research-mcp
5 tools                 12 tools     5 tools
```

El gateway es **servidor** para el host y **cliente** para los upstreams. El catálogo es
la única fuente de nombres; el router decide qué definiciones se exponen; la política
decide si una llamada se permite o requiere aprobación; el ejecutor valida, aplica
timeout/reintentos, limita la salida y audita.

## Flujo de una llamada

1. El cliente descubre herramientas con `tools/list`. En modo híbrido puede enviar
   `_meta["io.mcp-gateway/query"]` para recibir una selección dependiente de la tarea.
2. El modelo elige una herramienta y argumentos.
3. El gateway resuelve el descriptor namespaced (`servidor__tool`).
4. `PolicyEngine` aplica allowlist, scope y riesgo.
5. Si la tool es destructiva, se devuelve `InputRequiredResult`; el cliente resuelve la
   elicitación y reintenta con `inputResponses` + `requestState`.
6. `ToolExecutor` valida el esquema JSON, llama al upstream, reintenta errores de
   transporte, trunca salidas grandes y registra el resultado.
7. La respuesta incluye `_meta.trace_id`; la auditoría guarda estado, latencia, hashes y
   error redactado.

## Modos de router

| Modo | `tools/list` | Uso |
| :--- | :--- | :--- |
| `static` | Las 22 tools | Baseline de máxima exposición |
| `meta` | `find_tools`, `invoke_tool` | Mínimo coste de definiciones, más rondas |
| `hybrid` | 3 fijas + top-k (BM25) + 2 meta | Trade-off medido |

El router híbrido indexa nombres, descripciones, parámetros y un pequeño mapa bilingüe
explícito. No es un modelo semántico: es un baseline reproducible que no necesita GPU ni
red. Si no hay coincidencias, devuelve las fijas y las meta-herramientas como fallback.

Las herramientas fijas son `docs__list_docs`, `ops__list_services` y
`research__wikipedia_search`: cubren los tres upstreams y permiten una entrada barata
incluso cuando la consulta no tiene términos indexables.

## Catálogo y namespacing

- Nombre canónico `servidor__tool`, máximo 64 caracteres `[A-Za-z0-9_-]`.
- El hash SHA-256 de la definición expuesta se guarda en el descriptor.
- Un cambio de definición invalida el `requestState` de una aprobación anterior.
- Las tools con metadatos sospechosos se ponen en cuarentena; el upstream sigue
  conectado pero la tool no se expone.
- Un fallo de un upstream no elimina las tools de los demás; `/health` marca `degraded`.

## Transportes

- **Streamable HTTP** para gateway, docs-mcp y ops-mcp.
- **stdio** para research-mcp, lanzado como subproceso por el gateway.
- El cierre de upstreams es LIFO porque los clientes MCP anidan cancel scopes de anyio.
- Las pruebas de conformidad envían `MCP-Protocol-Version: 2026-07-28`; sin esa cabecera
  el SDK entra en la era legacy y exige sesión.

## Seguridad

- Bearer estático de laboratorio y PRM en `/.well-known/oauth-protected-resource`.
- Allowlist y scopes configurables; scopes estáticos, no derivados de un JWT.
- MRTR con HMAC-SHA256, TTL y binding a herramienta, definición y argumentos.
- Redacción de secretos en la auditoría.
- SSRF con validación de esquema, DNS y redirecciones en research-mcp.

## Evaluación

El runner levanta docs/ops por HTTP y research por stdio, conecta el gateway en memoria y
usa el mismo modelo/prompt en las tres configuraciones. La corrección es determinista:
selección, esquema JSON y predicado de salida. Los tokens de definiciones se miden con
`tiktoken`; los tokens de proveedor se toman de `usage`. No se mezclan.

## Decisiones y límites

Ver [`decisions.md`](./decisions.md) para el registro de decisiones y
[`evaluation.md`](./evaluation.md) / [`security.md`](./security.md) para los resultados.
