# Arquitectura de research-agents

> Este documento describe el sistema implementado, no una arquitectura ideal. Las
> decisiones que tienen un coste o una limitación se explican junto al diseño.
> Para los resultados de evaluación, consulta [`evaluation.md`](./evaluation.md).

## 1. Objetivo y alcance

`research-agents` recibe una pregunta abierta y produce un informe en Markdown con
claims, fuentes citables, una traza de ejecución y el consumo de recursos. El
sistema demuestra orquestación multiagente con LangGraph, pero también mantiene
baselines más simples para medir si esa coordinación aporta valor.

El repositorio contiene tres capas que reutilizan el mismo núcleo:

| Capa | Entrada | Uso |
| :--- | :--- | :--- |
| CLI | `python -m scripts.research` o `bin/research` | Investigación local y reanudación HITL |
| API/UI | FastAPI + SSE + HTML/JS | Demo de producto y traza en vivo |
| Evaluación | `python -m scripts.run_eval` | Comparación B0/B1/B2 con corpus congelado |

## 2. Vista de componentes

```text
                         ┌──────────────────────────────┐
                         │        Pregunta (brief)      │
                         └──────────────┬───────────────┘
                                        │
                         ┌──────────────▼───────────────┐
                         │          Supervisor          │
                         │  guardas de estado + ruta    │
                         └───┬───────┬───────┬───────┬──┘
                             │       │       │       │
                 ┌───────────▼─┐ ┌───▼────┐ ┌▼─────┐ ┌▼──────────┐
                 │   Planner   │ │Researcher│ │Analyst│ │  Critic   │
                 │ 1–4 subpreg.│ │ Send ×N │ │evidencia│ │ veredicto │
                 └───────┬─────┘ └───┬────┘ └┬──────┘ └┬──────────┘
                         │           │       │          │
                         │      ┌────▼────┐  │          │
                         │      │ Worker  │  │          │
                         │      │ ReAct   │  │          │
                         │      │ tools   │  │          │
                         │      └────┬────┘  │          │
                         │           │       │          │
                         └───────────┴───────┴──────────┘
                                        │
                              ┌─────────▼─────────┐
                              │ Approval (HITL)   │
                              │ interrupt()       │
                              └─────────┬─────────┘
                                        │ aprobado
                              ┌─────────▼─────────┐
                              │      Writer       │
                              │ informe + citas   │
                              └─────────┬─────────┘
                                        │
                                     END
```

Los nodos y las aristas se construyen en `src/graph.py`. El estado compartido
está en `src/state.py`, los contratos en `src/models.py` y el ensamblado de
dependencias en `src/services.py`.

## 3. Flujo de una ejecución B2

1. **Entrada.** `run_research()` crea el estado inicial con `run_id`, brief,
   `usage=0`, `notes=[]`, `sources={}` y `status="planning"`.
2. **Supervisor.** Aplica guardas deterministas sobre el estado y decide una ruta:
   planner si no hay plan; researcher si no hay notas y queda presupuesto;
   analyst si falta el análisis; critic si falta la crítica; writer si la crítica
   aprueba o ya no quedan rondas/presupuesto; finish si ya existe informe.
3. **Planner.** Produce un `ResearchPlan` de 1–4 subpreguntas. Si el LLM falla o
   se agota el presupuesto, usa `fallback_plan()` con la pregunta original.
4. **Fan-out.** El nodo `researcher` crea un `Send("researcher_worker", ...)` por
   subpregunta. No recorta la lista si hay más subpreguntas que workers; el
   paralelismo se limita con `max_concurrency`.
5. **Workers.** Cada worker ejecuta un subgrafo ReAct con
   `search_web`, `search_arxiv`, `search_wikipedia` y `fetch_page`. Al final
   devuelve un `ResearchOutput` con claims y fuentes; la salida estructurada no
   puede inventar URLs porque las fuentes se reconstruyen desde los resultados
   reales de las herramientas.
6. **Fan-in.** Los reducers del estado fusionan notas por `note_id`, fuentes por
   `source_id`, uso sumado, trazas y errores.
7. **Analyst.** Consolida la evidencia en una tabla `Analysis` y marca gaps. Si
   falla, hay un análisis determinista de respaldo.
8. **Critic.** Emite `approve` o `revise`. Además del LLM, una comprobación
   determinista exige que cada claim tenga al menos una cita válida. Si hay algo
   sin soporte, fuerza `revise`; no es una comprobación semántica de entailment.
9. **Revisión.** Si la crítica pide revisar y quedan rondas y presupuesto, el
   supervisor vuelve a researcher. Cada ronda vuelve a despachar todas las
   subpreguntas del plan.
10. **HITL.** Si `settings.hitl` está activo, antes del writer se llama a
    `interrupt()` y el run queda en `awaiting_approval`. La aprobación continúa;
    el rechazo termina sin informe.
11. **Writer.** Redacta el informe a partir del análisis, las notas compactadas,
    las fuentes y la crítica. El informe final añade claims, fuentes y usage. Si
    el LLM falla, se usa un borrador determinista con confianza baja.
12. **Fin.** El supervisor ve `report`, enruta a `finish` y el estado termina en
    `done`. El CLI/API devuelven el informe y la traza.

### Una precisión sobre el supervisor

`allowed_routes()` devuelve en la implementación actual **exactamente una** ruta
posible. Por tanto, la rama que consulta al LLM para elegir entre varias rutas no
se alcanza en producción; la ruta efectiva es determinista y barata. La rama LLM
está cubierta por tests con `allowed_routes` monkeypatcheado. Es una decisión
defendible para controlar coste y previsibilidad, pero conviene no presentar al
supervisor como un planificador autónomo que decide libremente.

## 4. Estado y concurrencia

`ResearchState` es un `TypedDict` que actúa como *blackboard* compartido:

| Campo | Reducer | Semántica |
| :--- | :--- | :--- |
| `notes` | `merge_notes` | Dict por `note_id`; la última versión gana |
| `sources` | `merge_sources` | `dict.update`; la última metadata gana |
| `usage` | `merge_usage` | Suma llamadas, tokens, búsquedas, latencia y modelos |
| `trace` | `operator.add` | Concatenación de eventos |
| `errors` | `operator.add` | Concatenación de errores |
| `plan`, `analysis`, `critique`, `report`, `route`, `hitl`, `round`, `status` | Sin reducer | Última escritura gana |

Consecuencias:

- El fan-in es sencillo y determinista.
- Una segunda ronda sobrescribe la nota de la misma subpregunta porque
  `note_id = stable_id("note", subquestion.question)`.
- Cada worker recibe una **copia** del `usage` al hacer `Send`. Su comprobación
  de presupuesto es `usage_inicial + su propio usage`, no la suma de los demás
  workers. Con concurrencia, el total puede superar el límite antes de que el
  siguiente nodo secuencial lo detecte. Es una limitación real del presupuesto
  distribuido.
- `recursion_limit` es 30 en `run_research()`, 50 en CLI/API y
  `max_steps * 4 + 10` en el subgrafo ReAct. Son topes independientes; con planes
  grandes el límite de 30 puede quedarse corto.

## 5. Contratos y roles

Todos los contratos de dominio usan Pydantic con `extra="forbid"`.

| Rol | Contrato | Responsabilidad |
| :--- | :--- | :--- |
| Supervisor | `Route` | Siguiente nodo y motivo |
| Planner | `ResearchPlan`, `SubQuestion` | Descomposición en 1–4 subpreguntas |
| Researcher | `ResearchAnswer` (finalización) → `ResearchOutput` | Evidencia, claims, fuentes y gaps |
| Analyst | `Analysis`, `EvidenceItem` | Tabla de evidencia y cobertura |
| Critic | `Critique` | Veredicto, claims no soportados y gaps |
| Writer | `ReportDraft` → `FinalReport` | Informe final con citas y usage |
| Juez | `JudgeOutput` | Score 0/2, hechos cubiertos y abstención |
| Evaluación | `EvaluationRecord` | Respuesta cruda, juicio, métricas y traza |

`ResearchAnswer` omite deliberadamente la metadata de fuentes. La metadata se
reconstruye con `sanitize_research_output()` y `collect_sources_from_messages()`
a partir de los `ToolMessage` reales. Esto evita que el modelo invente URLs, pero
no evita que el contenido de una fuente sea falso o malicioso.

## 6. Herramientas e investigación

### Backends live

| Herramienta | Implementación | Notas |
| :--- | :--- | :--- |
| `search_web` | Tavily, con fallback a DuckDuckGo | Caché SQLite y presupuesto mensual de Tavily |
| `search_arxiv` | API Atom de arXiv | Parseo XML y snippets limitados |
| `search_wikipedia` | MediaWiki API | Idioma configurable |
| `fetch_page` | `httpx` + `trafilatura` | Valida URL y redirecciones; extrae texto |

`SearchRouter` intenta el backend primario y, si falla o devuelve una lista
vacía, prueba el fallback. El agotamiento del presupuesto de Tavily es un
`SearchError`, así que también activa el fallback.

### Backends congelados

La evaluación usa `RESEARCH_SEARCH_BACKEND=frozen`. En ese modo:

- `FrozenSearchBackend` hace un ranking léxico determinista sobre 30 documentos
  de Wikipedia; no hay red.
- `FrozenPageFetcher` solo devuelve documentos del corpus y rechaza URLs que no
  estén en él.
- `search_arxiv` y `search_wikipedia` comparten el mismo backend frozen. No
  representan el comportamiento de las APIs live.

El corpus se valida con URL canónica, `source_id` derivado de la URL y SHA-256
antes de ejecutar modelos. La integridad se comprueba en el runner de evaluación;
el backend frozen por sí solo no vuelve a verificar los hashes.

### Caché y límites

- `SQLiteCache` guarda búsquedas y páginas con TTL. Un cache hit no consume el
  presupuesto de Tavily.
- `TavilyBudget` usa una tabla SQLite y `BEGIN IMMEDIATE` para reservar llamadas
  de forma atómica. Los reintentos de Tavily consumen una reserva por intento.
- `TokenRateLimiter` es una ventana deslizante compartida por proceso. Estima
  tokens y aplica esperas antes de cada llamada; no es un contador exacto.
- `BudgetGuard` corta por número de llamadas, tokens y rondas. Los nodos capturan
  `BudgetExceeded` y usan fallbacks deterministas para no dejar el run a medias.

## 7. Persistencia y HITL

| Persistencia | Ruta | Contenido |
| :--- | :--- | :--- |
| Caché | `artifacts/research.db` | Búsquedas y páginas con TTL |
| Presupuesto Tavily | `artifacts/research.db` | Llamadas por mes |
| Checkpointer | `artifacts/checkpoints.db` | Estado del grafo por `thread_id` |
| Trazas CLI | `artifacts/traces/*.json` | Informe, fuentes, usage, errores y eventos |
| Resultados eval | `eval/results/*/` | `records.jsonl`, resumen, SVG y metadatos |

El checkpointer `AsyncSqliteSaver` usa `JsonPlusSerializer` con una allowlist
explícita de tipos de la aplicación. El HITL se implementa con `interrupt()` en
`src/agents/approval.py`; la reanudación usa `Command(resume=...)` y el mismo
`thread_id`. Un rechazo no reinyecta el feedback como una nueva ronda.

En la API, el checkpointer conserva el estado, pero el registro de runs
(`RunManager.runs`) vive en memoria. Tras reiniciar el proceso, `GET` no conoce
runs antiguos; el CLI sí puede reanudar si se conserva el `thread_id`.

## 8. Capa de producto

- **FastAPI** (`app/main.py`): `POST /v1/research`, `GET /v1/research/{id}`,
  `GET /v1/research/{id}/events` (SSE), `POST /v1/research/{id}/approve` y
  `GET /health`.
- **SSE**: `RunManager` publica `status`, `node`, `trace`, `run_error` y `end`;
  conserva eventos en memoria para reproducirlos al reconectar.
- **UI** (`app/static/`): formulario, traza en vivo, informe, fuentes y botones
  de aprobación/rechazo. El Markdown se muestra como texto, no se interpreta como
  HTML.
- **CLI** (`bin/research`, `scripts/research.py`): subcomandos `research` y
  `resume`; comparte el mismo grafo y checkpointer que la API.
- **Docker**: imagen con usuario no root, healthcheck y volumen nombrado para
  SQLite. La demo no tiene autenticación y debe quedarse en local.

## 9. Evaluación

La evaluación sustituye la web por un corpus congelado para que B0, B1 y B2
reciban la misma evidencia y los resultados sean reproducibles.

| Sistema | Componentes |
| :--- | :--- |
| B0 | Un único researcher ReAct que responde directamente |
| B1 | Planner → researchers secuenciales → writer; sin supervisor, analyst ni critic |
| B2 | Grafo completo con supervisor, fan-out, analyst, critic y writer |

El runner es reanudable por `(question_id, system, repetition)`, escribe cada
registro con `fsync` y tolera una última línea parcial. El juez recibe una carga
ciega al nombre del sistema y al usage. Las métricas separan cobertura léxica,
precisión estricta de citas, validez, recall de fuentes, soporte estructural de
claims y abstención.

Puntos que no deben ocultarse:

- B1 es secuencial y B2 paralelo; la comparación mide la orquestación completa,
  no solo “más agentes”.
- El juez puede acabar usando el mismo proveedor que el sistema si Gemini falla.
- La cobertura factual es léxica; la precisión de citas penaliza fuentes
  adicionales válidas; `claim_support_rate` no mide entailment.
- El corpus es una foto de Wikipedia, no la web actual.

## 10. Mapa de archivos

```text
research-agents/
├── src/
│   ├── graph.py              # nodos y aristas LangGraph
│   ├── state.py              # estado y reducers
│   ├── models.py             # contratos Pydantic
│   ├── services.py           # wiring de LLM, tools, caché y presupuesto
│   ├── agents/               # supervisor, planner, researcher, analyst, critic, writer
│   ├── tools/                # live, frozen, fetch, arXiv, Wikipedia, DDG
│   ├── eval/                 # corpus, juez, métricas, runner, reporte
│   ├── checkpoint.py         # AsyncSqliteSaver y reanudación
│   └── llm.py                # cliente, rate limiter y fallback
├── app/                      # FastAPI, SSE y UI
├── scripts/                  # CLI, evaluación y spike
├── eval/                     # corpus congelado, preguntas y resultados
├── tests/                    # 151 tests sin llamadas reales
└── docs/                     # arquitectura, patrones, seguridad y evaluación
```

## 11. Límites de diseño

- La orquestación añade coste y latencia. En preguntas simples, B0 puede ser
  suficiente y más barato.
- El critic valida estructura de citas, no verdad semántica.
- Los fallbacks deterministas mantienen el run vivo, pero pueden producir un
  informe de baja calidad con estado `done`.
- El presupuesto concurrente no es estrictamente global.
- La API es una demo local sin auth, sin cuotas por usuario y con registro de
  runs en memoria.
- La evaluación completa requiere cuota y tiempo; los resultados parciales se
  etiquetan como tales.
