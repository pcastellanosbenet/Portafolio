# API, UI y despliegue local (Fase 5)

> **Estado (2026-10-24):** implementado y verificado con una ejecución real a
> través de la API. La demo expone el grafo por HTTP/SSE, permite aprobar o
> rechazar el HITL desde la UI y ofrece CLI y Docker. Sigue siendo una demo
> local: no tiene autenticación ni persistencia del registro de runs en la API.

## Qué incluye

- App FastAPI con ciclo de vida propio (`lifespan`) y checkpointer SQLite
  compartido.
- `POST /v1/research`, `GET /v1/research/{id}`, SSE en
  `/v1/research/{id}/events`, aprobación HITL en
  `/v1/research/{id}/approve` y `GET /health`.
- UI mínima en `/` para lanzar una pregunta, ver la traza en vivo, aprobar el
  HITL y leer el informe con sus fuentes.
- CLI unificada `research` y `resume` en `bin/research`.
- `Dockerfile`, `.dockerignore` y `docker-compose.yml` con volumen para SQLite
  y `env_file`.
- Rate limit básico por IP, CORS solo para orígenes locales y errores públicos
  redactados.

## Arranque local

```bash
cd research-agents
uv venv --python 3.12
uv pip install -r requirements-dev.txt
cp .env.example .env
# edita .env con GROQ_API_KEY y, si aplica, TAVILY_API_KEY
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Abre `http://127.0.0.1:8000/`. La documentación OpenAPI está en
`http://127.0.0.1:8000/docs`.

## API

| Método | Ruta | Uso |
| :--- | :--- | :--- |
| `GET` | `/health` | Estado del checkpointer, proveedor, modelo y runs activos |
| `POST` | `/v1/research` | Crea un run y devuelve `202` con sus URLs |
| `GET` | `/v1/research/{id}` | Estado, informe, usage, errores y traza |
| `GET` | `/v1/research/{id}/events` | Stream SSE con los eventos del run |
| `POST` | `/v1/research/{id}/approve` | Aprueba o rechaza un run en HITL |

Crear una ejecución:

```bash
curl -sS http://127.0.0.1:8000/v1/research \
  -H 'content-type: application/json' \
  -d '{"question":"¿Qué es un transformer y para qué se usa en NLP?","language":"es"}'
```

La respuesta incluye `run_id`, `thread_id`, `status_url` y `events_url`. El
`thread_id` coincide con el `run_id` y es el que usa el checkpointer.

Consultar el estado:

```bash
curl -sS http://127.0.0.1:8000/v1/research/<run_id>
```

Escuchar el stream:

```bash
curl -N http://127.0.0.1:8000/v1/research/<run_id>/events
```

Cada bloque SSE tiene la forma:

```text
data: {"type":"trace","run_id":"...","node":"planner","event":"plan_created","data":{...}}
```

Tipos de evento:

| `type` | Contenido |
| :--- | :--- |
| `status` | `status` del run y `graph_status` del grafo |
| `node` | Nodo que acaba de ejecutarse |
| `trace` | Evento de traza con `node`, `event`, `data` y `timestamp` |
| `run_error` | Error público, sin claves ni trazas internas |
| `end` | Fin de la ejecución o pausa para aprobación |

El stream conserva los eventos en memoria y los reproduce al reconectar. Si el
run termina, cierra la conexión; si queda en `awaiting_approval`, la mantiene
abierta para recibir la decisión.

## HITL desde la API y la UI

Pide HITL en la creación:

```bash
curl -sS http://127.0.0.1:8000/v1/research \
  -H 'content-type: application/json' \
  -d '{"question":"¿Qué es un transformer?","hitl":true}'
```

El run se detiene antes del writer y `GET /v1/research/{id}` devuelve
`status="awaiting_approval"` y un objeto `interrupt` con la pregunta, el resumen
del análisis, las notas y las fuentes. Para continuar:

```bash
curl -sS http://127.0.0.1:8000/v1/research/<run_id>/approve \
  -H 'content-type: application/json' \
  -d '{"approved":true,"feedback":"Adelante."}'
```

Para rechazar:

```bash
curl -sS http://127.0.0.1:8000/v1/research/<run_id>/approve \
  -H 'content-type: application/json' \
  -d '{"approved":false,"feedback":"Faltan fuentes primarias."}'
```

La aprobación continúa al writer; el rechazo termina con `status="rejected"` y
sin informe. La UI hace estas dos llamadas desde los botones de revisión. El
endpoint de aprobación devuelve `409` si el run no está esperando decisión.

## CLI

`bin/research` es el lanzador local; dentro de Docker se usa directamente
`python -m scripts.research`. El CLI reutiliza `scripts/run_research.py`, así que
las opciones y el comportamiento del checkpointer son los mismos.

```bash
# Nueva investigación con HITL
./bin/research research "¿Qué es un transformer?" --hitl --no-fallback

# Aprobar desde otro proceso
./bin/research resume --thread-id <thread_id> --approve --no-fallback

# Rechazar
./bin/research resume --thread-id <thread_id> --reject \
  --feedback "Faltan fuentes primarias." --no-fallback
```

También se puede invocar sin el launcher:

```bash
.venv/bin/python -m scripts.research research "..." --hitl
.venv/bin/python -m scripts.research resume --thread-id ... --approve
```

## Docker

```bash
cd research-agents
cp .env.example .env
# edita .env; no lo añadas a Git
docker compose up --build
```

La API queda en `http://127.0.0.1:8000`, y el volumen nombrado `research-data`
se monta en `/app/artifacts` para conservar `research.db` y `checkpoints.db`.
Se usa un volumen nombrado para que el usuario no root del contenedor pueda
escribir sin depender del UID del host. El contenedor no copia `.env`: lo recibe
en tiempo de ejecución mediante `env_file`. El usuario del contenedor no es root
y el healthcheck consulta `/health`.

La imagen `research-agents:phase5` se construyó y se arrancó el 2026-10-24. El
contenedor respondió `/health` con `status=ok`, `checkpointer=sqlite` y la UI en
`/`. También se probó un volumen nombrado: `research.db` y `checkpoints.db`
quedaron propiedad de `appuser`, así que el usuario no root puede escribir. No se
ejecutó una llamada real desde dentro del contenedor para no duplicar el consumo
de la prueba E2E.

## Prueba E2E real

El 2026-10-24 se lanzó una pregunta a través de la API real, con Groq como
proveedor y búsqueda web en vivo:

| Campo | Valor |
| :--- | :--- |
| Run | `api-live-20261024` |
| Pregunta | ¿Qué es un transformer y para qué se usa en NLP? |
| Estado | `completed` / `graph_status=done` |
| Duración | 308,8 s (incluye el limitador de TPM) |
| Llamadas | 10 |
| Tokens | 12.172 de entrada + 7.793 de salida = 19.965 |
| Búsquedas | 4 |
| Informe | 4 claims, 19 fuentes, confianza `low` |
| Traza | 23 eventos |
| Errores | 2 avisos de presupuesto agotado; critic y writer usaron fallback determinista |

El run consumió exactamente el límite configurado para la prueba
(`max_llm_calls=10`, `max_tokens=30.000`, una ronda, un worker y un paso de
herramienta). Por eso el critic y el writer no pudieron hacer su llamada final y
el informe salió con confianza baja: la API y el stream funcionaron, pero ese
resultado **no representa la calidad del sistema sin límites tan ajustados**.
La traza completa está en
[`api-live-20261024.json`](./api-live-20261024.json).

## Tests

```bash
.venv/bin/ruff check src tests scripts app
.venv/bin/pytest -q
```

Los tests de API usan un grafo falso y también cubren un grafo LangGraph real con
`MemorySaver` para verificar la pausa HITL y la reanudación. No hacen llamadas
reales a proveedores. La suite completa pasa con **149 tests**.

## Seguridad y límites

- Las claves se leen de `.env` y nunca se devuelven en respuestas ni se escriben
  en logs de la app.
- `/health` solo declara si una clave está configurada (`true`/`false`), nunca su
  valor.
- Los errores públicos se truncan y se redactan con los secretos configurados y
  patrones de claves.
- El rate limit es de 30 peticiones por minuto e IP, en memoria.
- CORS solo permite `localhost`/`127.0.0.1` en los puertos de la demo.
- **No hay autenticación.** No expongas esta API a Internet sin añadir auth,
  límites por usuario y HTTPS.
- El registro de runs vive en memoria: el checkpointer conserva el estado del
  grafo para reanudar por CLI, pero tras reiniciar la API `GET` no conoce los
  runs anteriores. Para producción haría falta cargar el registro desde el
  checkpointer o una tabla de runs.
- Se debe usar **un worker** de uvicorn: varios procesos tendrían registros y
  streams separados.
- El SSE mantiene los eventos en memoria; no está pensado para clientes que
  reconectan después de un reinicio.
