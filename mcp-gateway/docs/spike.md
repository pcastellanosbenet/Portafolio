# Spike de protocolo — Fase 0

> **Fecha:** 2026-10-26.
> **Estado:** gate cumplido con una salvedad documentada (host GUI no verificado).
> **Objetivo:** validar SDK, revisión del protocolo, transportes, MRTR, suscripciones,
> cancelación y tool calling antes de construir el gateway.

## Entorno verificado

| Elemento | Versión |
| :--- | :--- |
| Python | 3.12.15 |
| SDK MCP | `mcp==2.3.0` |
| Tipos MCP | `mcp-types==2.3.0` |
| Revisión del protocolo | `2026-07-28` |
| Starlette / Uvicorn | 1.10.0 / 0.54.0 |
| Inspector | 2.12.0 |
| Modelo | Groq `openai/gpt-oss-120b` |
| Node (solo para el Inspector) | 24.22.1 en `/tmp/opencode/node` |

El SDK v2 es la línea estable y `pip install mcp` instala 2.x. La revisión
`2026-07-28` elimina el handshake y las sesiones, introduce `server/discover`, los
metadatos por petición, MRTR y `subscriptions/listen`.

## Qué se verificó

Servidor de spike: `scripts/spike_server.py`. Cliente: `scripts/spike_client.py`.

| Comprobación | Resultado |
| :--- | :--- |
| `server/discover` por HTTP | 200; `supportedVersions=["2026-07-28"]`; capacidades, `ttlMs` y `cacheScope` |
| `tools/list` por HTTP | 200; orden estable; `cacheScope: public` |
| `tools/call` con `Mcp-Method` y `Mcp-Name` | 200; `structuredContent.result = 15` |
| Cabecera `Mcp-Name` incorrecta | 400 + `-32020` (`HeaderMismatch`) |
| Versión futura no soportada | 400 + `-32022` con `supported` y `requested` |
| `GET`/`DELETE` con versión moderna | 405 con `Allow: POST` |
| `Origin` no permitido | 403 |
| Tools, resources y prompts | Correctos en memoria, stdio y HTTP |
| Progreso | 4 eventos `notifications/progress` por llamada |
| MRTR (`Resolve` + elicitación) | Aprobación recibida y aplicada |
| `subscriptions/listen` | `honored.tools_list_changed=true`; evento `ToolsListChanged` |
| Cambio dinámico del catálogo | 5 → 6 herramientas tras `refresh_tools` |
| Cancelación | El cierre/timeout del cliente ejecutó el `finally` del handler |
| Inspector CLI | `tools/list` y `tools/call add(11,31) → 42` |
| Cliente SDK como host | Protocolo `2026-07-28` en los tres transportes |

### Evidencia HTTP representativa

`server/discover` devolvió:

```json
{
  "supportedVersions": ["2026-07-28"],
  "capabilities": {
    "prompts": {"listChanged": true},
    "resources": {"listChanged": true, "subscribe": true},
    "tools": {"listChanged": true}
  },
  "ttlMs": 0,
  "cacheScope": "private",
  "resultType": "complete"
}
```

`tools/call` con `Mcp-Name` incorrecta devolvió:

```json
{"error": {"code": -32020, "message": "mcp-name header does not match the request body's 'name' parameter"}}
```

### Comportamiento legacy observado

El SDK sirve simultáneamente clientes de 2025 y de 2026. Si la petición no lleva
`MCP-Protocol-Version` o lleva una versión con handshake (`2025-11-25`), el servidor
entra por la ruta legacy y responde `400 Missing session ID` hasta que el cliente hace
`initialize`. Esto es intencionado y no es un fallo del gateway.

Consecuencia para la matriz de conformidad: las comprobaciones de `2026-07-28`
deben enviar la cabecera de versión. `GET`/`DELETE` solo devuelven 405 cuando la
petición se enruta por la era moderna; sin cabecera caen en la ruta legacy.

## Tool calling

Diez tareas de selección con cinco herramientas, temperatura 0:

| Métrica | Resultado |
| :--- | ---: |
| Selecciones correctas | 10/10 |
| Precisión | 100% |
| Latencia media | 520,6 ms |
| Tokens de prompt | 2.573 |
| Tokens de completion | 710 |
| Tokens totales | 3.283 |

Resultados crudos: `artifacts/spike/llm_tool_calling.json` (ignorado por Git).

**Salvedad:** cinco herramientas y peticiones inequívocas no demuestran nada sobre el
enrutado con 25 herramientas y consultas ambiguas. Esa es la hipótesis de la Fase 3, no
un resultado de esta fase.

## Lo que no se pudo verificar

- **Host GUI (Claude Desktop o VS Code):** no hay sesión gráfica y `code --add-mcp`
  modificaría la configuración del usuario. Se verificó con el Inspector y con el
  `Client` del SDK, que ejercitan el mismo protocolo. Queda como comprobación manual
  documentada en el README.
- **Inspector en modo web:** solo se usó el modo CLI; el modo web requiere navegador.

Ninguna de las dos afecta al diseño del gateway.

## Decisiones que salen del spike

1. Usar `mcp==2.3.0` y la API de alto nivel (`MCPServer`, `Client`, `Resolve`).
2. No implementar JSON-RPC ni el transporte a mano.
3. Mantener el soporte legacy del SDK y probar la era moderna enviando la cabecera.
4. Usar `openai/gpt-oss-120b` en Groq para los runs reales de evaluación.
5. Implementar el gateway como servidor moderno y documentar el fallback legacy.
6. El router se evaluará con 25 herramientas; el resultado de este spike no se reutiliza
   como métrica del README.

## Gate

- Transportes stdio y HTTP: **OK**.
- MRTR, suscripciones y cancelación: **OK**.
- Inspector: **OK** (CLI).
- Tool calling: **10/10** (gate ≥ 8/10).
- Host GUI: **pendiente manual**, sin impacto en el diseño.

**Decisión:** continuar con la Fase 1.
