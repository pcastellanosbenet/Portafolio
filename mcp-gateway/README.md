# MCP Gateway

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-2026--07--28-6B4FBB?style=for-the-badge)](https://modelcontextprotocol.io/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

Gateway MCP que agrega tres servidores, enruta herramientas con divulgación progresiva,
aplica política de seguridad, resuelve aprobaciones humanas y mide el trade-off entre
precisión, coste de contexto y latencia.

El proyecto implementa la revisión **MCP `2026-07-28`** con `mcp==2.3.0` y Python 3.12.
No es una demo visual: incluye 60 tareas de evaluación, 14 ataques, 20 peticiones
benignas, tests de conformidad y resultados crudos versionados.

## El problema

Un host MCP con 22 herramientas paga dos costes: tokens de definiciones en cada prompt y
riesgo de que el modelo elija una herramienta peligrosa o equivocada. Exponer todo el
catálogo es simple, pero no escala; esconderlo detrás de meta-herramientas ahorra
definiciones, pero añade rondas y puede empeorar la selección.

**Hipótesis:** la divulgación híbrida (top-k por consulta + herramientas fijas + fallback
`find_tools`) reduce el coste de contexto manteniendo o mejorando la precisión de
selección. La respuesta no se asume: se mide.

## Arquitectura

```text
Pregunta
   │
   ▼
host CLI ── MCP 2026-07-28 ──► gateway (servidor MCP)
                                  │
                 ┌────────────────┼─────────────────┐
                 ▼                ▼                 ▼
              catálogo          router           política
           namespacing      static/meta/hybrid   allowlist/riesgo
           hash + cuarentena       │             MRTR + bearer
                 └────────────────┼─────────────────┘
                                  ▼
                               ejecutor
                    timeout · reintentos · límite de salida
                         auditoría SQLite · trace_id
                                  │
             ┌────────────────────┼─────────────────────┐
             ▼                    ▼                     ▼
       docs-mcp (HTTP)     research-mcp (stdio)     ops-mcp (HTTP)
       5 herramientas      5 herramientas          12 herramientas
```

- **`docs-mcp`**: corpus técnico propio de 5 documentos y búsqueda BM25.
- **`research-mcp`**: Wikipedia/arXiv con fixtures deterministas y `fetch_url` con
  protección SSRF; por defecto funciona offline.
- **`ops-mcp`**: 12 herramientas sobre estado sintético, incluidas dos destructivas.
- **Gateway**: namespacing `servidor__tool`, catálogo con hash, router, política,
  aprobaciones MRTR, auditoría y redacción de secretos.
- **Host CLI**: lista, busca, invoca con argumentos JSON, aprueba/rechaza y lee trazas.

## Resultados medidos

### Evaluación A/B/C

Modelo `openai/gpt-oss-120b` (Groq), temperatura 0, 60 tareas congeladas
(SHA-256 `f08f4ba65c96bc102238b961c25df4c42b5574f37ab75a356607ed2b783eda67`).
Sin juez LLM.

| Configuración | Herramientas iniciales | Éxito | Selección@1 | Args válidos | Abstención | Tokens defs | Prompt tokens | Tokens totales | p50 | p95 |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A. Estática | 22 | 58,33% | 58,00% | 100,00% | 90,00% | 2.493,0 | 983,32 | 1.111,2 | 3.175,5 ms | 10.259,5 ms |
| B. Meta-tools | 2 | 50,00% | 46,00% | 96,00% | 100,00% | 557,0 | 942,47 | 1.180,9 | 6.339,9 ms | 12.695,6 ms |
| C. Híbrida | 3 fijas + top-8 + 2 meta | 63,33% | 62,00% | 100,00% | 90,00% | 958,9 | 606,22 | 737,4 | 3.996,9 ms | 7.064,9 ms |

- Híbrida reduce **61,5%** los tokens de definiciones, **38,4%** los tokens de prompt y
  **33,7%** los tokens totales medios frente a estática. El éxito sube 5,0 puntos
  porcentuales; con 60 tareas, no se presenta como una diferencia significativa.
- Meta reduce **77,7%** las definiciones, pero **no** reduce los tokens totales: necesita
  más rondas y su éxito cae 8,3 puntos. Es un resultado negativo útil, no un fallo oculto.
- Operaciones es el mejor bloque para híbrida (93,33%); documentación es el peor (30%).
  El modelo confunde `read_doc`/`outline_doc`/`cite_doc` con `search_docs`/`list_docs`.
- La abstención en negativas es 90% en estática/híbrida y 100% en meta. El único falso
  positivo repetido es “Resume el PDF adjunto”, que llama a `docs__list_docs`.
- Robustez: 3 repeticiones de 20 tareas sin caché dieron **55,00%** de éxito las tres
  veces; la latencia sí varió y los aciertos concretos también.
- Ablación `k`: con 20 tareas, `k=5` y `k=12` dieron 55,00% y `k=8` 50,00%. Los tokens de
  definiciones crecieron de 893,3 (`k=5`) a 1.020,0 (`k=12`). No hay tendencia monótona
  de precisión; `k=5` es la opción más barata de esta muestra.

Detalle, fallos y límites: [`docs/evaluation.md`](./docs/evaluation.md). Resultados
crudos: [`eval/results/`](./eval/results/).

### Seguridad

| Suite | Resultado |
| :--- | :--- |
| Ataques bloqueados | **14/14** |
| Peticiones benignas permitidas | **20/20** |
| Falsos positivos | **0** |

Cubre tool poisoning, shadowing, SSRF (loopback, metadata, `file://`), path traversal,
inyección de argumentos, acciones destructivas sin aprobación, rechazo, manipulación de
`requestState`, replay, bearer ausente y `Origin` inválido. Informe:
[`security/results/2026-10-26-suite.json`](./security/results/2026-10-26-suite.json).

### Conformidad y calidad

- **83 tests** en verde, incluidos 10 de conformidad HTTP, integración HTTP+stdio con los
  tres upstreams, router, evaluación y seguridad.
- `ruff check src tests scripts eval security` limpio.
- `docker compose up --build -d` levanta los tres servicios y `/health` confirma 22
  herramientas.
- Smoke determinista de 5 tareas: **5/5**, traza en
  [`docs/examples/smoke.json`](./docs/examples/smoke.json).
- MRTR probado con el cliente moderno: aprobación, rechazo, token HMAC con TTL y binding
  a definición/argumentos.

## Cómo ejecutarlo

Requisitos: Python 3.12 y `uv`; Docker es opcional.

```bash
cd mcp-gateway
uv venv --python 3.12
uv pip install -r requirements-dev.txt
```

### Demo con Docker Compose

```bash
docker compose up --build -d
curl http://127.0.0.1:8765/health
docker compose logs -f gateway
docker compose down
```

### CLI

```bash
# Catálogo completo
.venv/bin/python -m src.host tools

# Selección híbrida para una consulta
.venv/bin/python -m src.host tools --query "Reinicia el servicio api"

# Invocación con argumentos JSON
.venv/bin/python -m src.host call docs__search_docs \
  --query "MRTR" --arg 'query=MRTR aprobación' --arg limit=2

# Traza de auditoría
.venv/bin/python -m src.host --db artifacts/gateway.db trace --limit 10
```

Las herramientas destructivas piden aprobación por terminal. En automatización:

```bash
.venv/bin/python -m src.host call ops__restart_service --query "Reinicia api" --arg service=api --reject
.venv/bin/python -m src.host call ops__restart_service --query "Reinicia api" --arg service=api --approve
```

### Evaluación

```bash
# Valida el corpus congelado sin red
.venv/bin/python -m eval.validate_tasks

# Pipeline con modelo oráculo, sin claves
.venv/bin/python -m eval.run_eval --config hybrid --model fake --limit 60 \
  --output /tmp/eval-fake.jsonl

# Run real (la clave se carga desde el entorno; no se versiona)
export GROQ_API_KEY=...
.venv/bin/python -m eval.run_eval --config hybrid --model groq \
  --llm-model openai/gpt-oss-120b --limit 60 \
  --output eval/results/2026-10-26-hybrid-groq.jsonl
```

El runner es reanudable y escribe cada tarea en JSONL. Si Groq devuelve `429`, reintenta
con `Retry-After`; si se agota el cupo, sale con código 2 y se puede continuar después.

### Suite de seguridad

```bash
.venv/bin/python -m security.run_suite \
  --output security/results/2026-10-26-suite.json
```

## Estructura

```text
mcp-gateway/
├── src/
│   ├── gateway/        # catálogo, router, política, ejecutor, auditoría, auth
│   ├── host/           # CLI y cliente Groq
│   └── upstreams/      # docs-mcp, research-mcp, ops-mcp
├── eval/               # 60 tareas, runner, validación y resultados crudos
├── security/           # 14 ataques, 20 benignas, runner y informe
├── tests/              # conformidad, integración, router, evaluación y seguridad
├── docs/               # evaluación, seguridad, protocolo, arquitectura
├── Dockerfile
└── compose.yaml
```

## Conformidad MCP

La matriz requisito → test está en [`docs/protocol.md`](./docs/protocol.md):
`server/discover`, `_meta` por petición, ausencia de sesión, `MCP-Protocol-Version`,
`Mcp-Method`/`Mcp-Name`, `-32020`, `-32022`, `405`, `403`, cache hints, progreso,
cancelación y MRTR. Las filas parciales se marcan como tales.

## Limitaciones

- La evaluación es una muestra de 60 tareas; las diferencias de 5 puntos no son
  significativas por sí solas.
- El router es léxico (BM25 + expansión bilingüe explícita), no semántico.
- La robustez y las ablaciones usan 20 tareas; sirven para detectar inestabilidad y
  coste, no para estimar intervalos de confianza estrechos.
- `fetch_url` valida el DNS antes de la petición; queda la ventana teórica de DNS
  rebinding. Producción debería fijar la IP en el transporte.
- El modo bearer es un resource server de laboratorio con token estático; no hay
  authorization server OAuth 2.1, JWT, introspección ni rotación. Los scopes se anuncian
  en el PRM y se pueden exigir de forma estática, pero no se derivan de un token real.
- La cuarentena de tool poisoning es heurística; puede tener falsos positivos y no cubre
  todas las variantes semánticas.
- La demo es local; no hay endpoint público permanente.

## Licencia

MIT. El corpus, las fixtures y las 60 tareas son propios y no requieren datos privados.
