# Fase 2 — Upstreams reales y host CLI

> **Fecha:** 2026-10-26.
> **Alcance:** tres servidores MCP reales, host CLI, aprobaciones MRTR, demo Docker y
> cinco tareas deterministas. Los resultados de esta página se obtuvieron ejecutando el
> código; no hay métricas estimadas.

## Upstreams

| Servidor | Transporte | Herramientas | Datos | Puerto local |
| :--- | :--- | ---: | :--- | ---: |
| `docs-mcp` | Streamable HTTP | 5 | Corpus técnico propio de 5 documentos | 8766 |
| `research-mcp` | stdio | 5 | Fixtures sintéticas; Wikipedia/arXiv en modo `live` | — |
| `ops-mcp` | Streamable HTTP | 12 | Estado sintético determinista | 8767 |

El gateway descubre **22 herramientas** y las expone con el prefijo `servidor__tool`.

### `docs-mcp`

- Corpus propio en `src/upstreams/docs/corpus/`: protocolo MCP, arquitectura del gateway,
  seguridad, operaciones y evaluación. La licencia es la del repositorio.
- Búsqueda BM25 con tokenización sin acentos y snippets por párrafo.
- Herramientas: `search_docs`, `read_doc`, `list_docs`, `outline_doc`, `cite_doc`.
- `cite_doc` devuelve el SHA-256 del contenido para poder verificar una cita.

### `research-mcp`

- Herramientas: `wikipedia_search`, `wikipedia_get`, `arxiv_search`, `arxiv_get`,
  `fetch_url`.
- Por defecto usa `RESEARCH_MODE=fixtures`: resultados sintéticos, offline y
  deterministas. `RESEARCH_MODE=live` activa los clientes reales de Wikipedia y arXiv.
- `fetch_url` solo acepta `http`/`https`, resuelve el hostname, bloquea direcciones no
  públicas (`loopback`, privadas, link-local, multicast, reservadas), valida cada
  redirección, limita la respuesta a 1 MB y recorta el texto devuelto.
- Límite declarado: entre la validación DNS y la petición HTTP existe una ventana teórica
  de DNS rebinding; una versión de producción debería fijar la IP resuelta en el
  transporte.

### `ops-mcp`

- Estado en memoria: 5 servicios, 6 incidentes, logs, despliegues y namespaces.
- 12 herramientas: 7 de lectura, 3 de escritura y 2 destructivas
  (`restart_service`, `delete_namespace`).
- Las anotaciones MCP (`readOnlyHint`, `destructiveHint`) alimentan el motor de política
  del gateway. El estado vuelve a su valor inicial al reiniciar el servidor.

## Host CLI

```bash
cd mcp-gateway
.venv/bin/python -m src.host tools
.venv/bin/python -m src.host search "seguridad SSRF"
.venv/bin/python -m src.host call docs__search_docs \
  --query "MRTR" --arg 'query=MRTR aprobación' --arg limit=2
.venv/bin/python -m src.host --db artifacts/gateway.db trace --limit 10
.venv/bin/python -m src.host health
```

`call` acepta valores JSON (`limit=2`, `status=null`, `flags={"a":1}`) y cae a texto
cuando no son JSON. La salida muestra el `trace_id`, que también se persiste en SQLite.

### Aprobaciones

Las herramientas destructivas devuelven `InputRequiredResult` con una elicitación. El
cliente SDK recoge la respuesta y reintenta con `inputResponses` y `requestState`; el
gateway verifica un token HMAC con TTL, la herramienta, el hash de su definición y el hash
de los argumentos.

```bash
# Rechazo explícito, sin prompt interactivo
.venv/bin/python -m src.host call ops__restart_service --arg service=api --reject

# Aprobación explícita
.venv/bin/python -m src.host call ops__restart_service --arg service=api --approve
```

Sin `--approve`/`--reject`, el CLI pregunta por terminal. Si no hay TTY, rechaza por
defecto. Cada intento queda auditado como `approval_pending`, `approval_denied` u `ok`.
El secreto de aprobación se genera por proceso si no se configura
`GATEWAY_APPROVAL_SECRET`; para varias réplicas hay que fijarlo.

## Docker Compose

```bash
docker compose up --build -d
curl http://127.0.0.1:8765/health
docker compose logs -f gateway
docker compose down
```

Resultado medido tras `docker compose up --build -d`:

```json
{
  "status": "ok",
  "protocol_version": "2026-07-28",
  "upstreams": {
    "docs": {"connected": true, "tools": 5, "error": null},
    "research": {"connected": true, "tools": 5, "error": null},
    "ops": {"connected": true, "tools": 12, "error": null}
  },
  "tools": 22
}
```

## Tareas de extremo a extremo

`scripts/smoke_e2e.py` ejecuta cinco tareas con predicados deterministas, sin juez LLM:

| Tarea | Herramienta | Predicado |
| :--- | :--- | :--- |
| `docs-mrtr` | `docs__search_docs` | Devuelve el documento `protocolo` |
| `docs-security` | `docs__read_doc` | Contiene `SSRF` y un SHA-256 de 64 caracteres |
| `ops-open-incidents` | `ops__list_incidents` | Todos los incidentes están `open` |
| `ops-api-metrics` | `ops__query_metrics` | Devuelve 5 puntos con latencia |
| `research-ssrf` | `research__wikipedia_search` | El primer resultado es `ssrf` |

```bash
.venv/bin/python scripts/smoke_e2e.py --output docs/examples/smoke.json
```

Resultado medido: **5/5 tareas correctas**. La traza sanitizada está en
`docs/examples/smoke.json`; no contiene claves ni datos privados.

## Pruebas y lint

```bash
.venv/bin/ruff check src tests scripts
.venv/bin/pytest -q
```

Resultado medido:

- **83 tests** en verde.
- **10 tests** de conformidad HTTP.
- **1 test** de integración que arranca `docs-mcp` y `ops-mcp` por HTTP y `research-mcp`
  por stdio, y llama a una herramienta de cada upstream a través del gateway.
- **7 tests** de router y **6 tests** de evaluación.
- `ruff` limpio.

## Pendiente y límites

- El host gráfico (Claude Desktop o VS Code) no se ha verificado: no hay sesión gráfica y
  modificar la configuración del usuario queda fuera del alcance de esta fase.
- Las URLs de las fixtures usan `example.org`; no son enlaces reales.
- El modo `live` de investigación no se usa en la demo determinista.
- La demo es local; no hay endpoint público permanente.
- La re-aprobación automática cuando cambia el hash de una definición y la suite de 14
  ataques pertenecen a la Fase 4.
