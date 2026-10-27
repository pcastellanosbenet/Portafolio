# Decisiones

Registro breve de las decisiones que condicionan el diseño. Las métricas y los límites
están en `docs/evaluation.md` y `docs/security.md`.

## D1 — Proyecto `mcp-gateway`

Quinto proyecto del portafolio. El objetivo es demostrar ingeniería de protocolo MCP,
evaluación y seguridad, no construir un producto multitenant.

## D2 — MCP `2026-07-28` con SDK 2.x

Se usa `mcp==2.3.0` y el `Server` de bajo nivel para despacho dinámico. El `Client` del
SDK se usa para los upstreams. La decisión se validó en la Fase 0 con stdio, HTTP,
progreso, MRTR, `subscriptions/listen`, cancelación y errores `-32020`/`-32022`.

## D3 — Gateway servidor + cliente

Un único endpoint para el host; el gateway mantiene conexiones con los upstreams. Esto
permite namespacing, política y auditoría centralizadas.

## D4 — Tres upstreams autocontenidos

`docs-mcp` (HTTP), `research-mcp` (stdio) y `ops-mcp` (HTTP). No dependen en runtime de
`rag-assistant` ni de `research-agents`. Los datos son propios o sintéticos.

## D5 — Sin authorization server OAuth

El gateway es un resource server de laboratorio. Se implementa bearer estático, PRM y
documentación del modelo OAuth 2.1, pero no un AS, JWT, introspección ni rotación. Es
preferible declarar la limitación a simular seguridad completa.

## D6 — Namespacing y hash

`servidor__tool` evita shadowing; el hash de la definición permite invalidar aprobaciones
cuando cambia una tool. La cuarentena de metadatos sospechosos es heurística y se
documenta como tal.

## D7 — Router léxico

BM25 es el baseline: barato, determinista y sin GPU. Se añade una expansión bilingüe
explícita porque las consultas son en español y las descripciones en inglés. No se
presenta como un router semántico.

## D8 — Evaluación determinista

60 tareas, `gold` explícito, predicados sobre la salida y ningún juez LLM. La validez de
argumentos es conformidad con el esquema JSON; el éxito es el predicado. Los resultados
crudos se versionan.

## D9 — Tres configuraciones

- Estática: todas las tools.
- Meta: solo `find_tools` + `invoke_tool`.
- Híbrida: fijas + top-k + meta como fallback.

Se comparan con el mismo modelo, prompt, temperatura y fixtures.

## D10 — Groq free tier y caché

El modelo real es `openai/gpt-oss-120b`. El TPD observado es 200.000 tokens; el runner es
reanudable, cachea por hash y hace lotes. Si la cuota impide completar robustez/ablations,
se publica la parte medida y se declara.

## D11 — MRTR ahora, no después

La aprobación humana era una tarea de Fase 4, pero el CLI de Fase 2 necesitaba resolverla.
Se adelantó el `InputRequiredResult` con token HMAC, TTL y binding. El estado se firma con
payload + 32 bytes de firma; no se usa un separador textual porque la firma es binaria.

## D12 — Docker local, sin endpoint público

`compose.yaml` levanta docs, ops y gateway; research se lanza por stdio desde el gateway.
No hay despliegue público permanente.

## D13 — Fail closed, pero observable

Una tool en cuarentena o un upstream caído no tumba el gateway. `/health` informa del
estado y de las tools cuarentenadas; los errores de herramienta se devuelven con
`isError=true` para que el modelo pueda reaccionar.

## D14 — Sin secretos en Git

Las claves se cargan del entorno. La caché de evaluación y los artefactos están en
`.gitignore`; los errores se redactan antes de la auditoría.
