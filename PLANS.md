# PLANS.md — `research-agents`

> **Estado:** Fase 3 completada (crítica determinista, HITL, checkpointer SQLite y reanudación real); Fase 4 pendiente.
> **Fecha:** 2026-10-23.
> **Ubicación:** raíz del repositorio.

## Convención de progreso

- `[ ]` tarea pendiente.
- `[x]` tarea completada y verificada.
- No marcar una tarea hasta que su test, comando o revisión haya pasado.
- Si una tarea queda bloqueada, dejarla en `[ ]` y anotar el motivo en el registro de progreso.
- Los pasos están ordenados; una fase no se cierra hasta cumplir su criterio de salida.

---

## 1. Decisiones cerradas

| ID | Decisión |
| :--- | :--- |
| D1 | El proyecto se llama `research-agents/` y será el cuarto proyecto del portafolio. |
| D2 | Se usarán **Groq** y **Gemini** con claves de ambos. El proveedor y el modelo se seleccionan por `.env`. |
| D3 | La búsqueda web usará **Tavily**, **arXiv** y **Wikipedia**, con **DuckDuckGo** como fallback. |
| D4 | Alcance: CLI + API FastAPI/SSE + UI mínima + Docker. **Sin MCP en esta iteración.** |
| D5 | Python 3.12 con `uv`, igual que el resto del repositorio. |
| D6 | Sin GPU, sin fine-tuning y sin vector DB en el MVP. |
| D7 | Supervisor implementado a medida con LangGraph; `langgraph-supervisor` solo se estudia como comparación documental. |
| D8 | La evaluación usa un corpus congelado con licencia compatible; la demo usa búsqueda web en vivo. |
| D9 | El CI no hace llamadas reales a APIs ni necesita claves. |
| D10 | Código y comentarios en inglés; documentación y README en español. |

### Configuración prevista

`.env.example` incluirá, como mínimo:

```dotenv
# Proveedor principal: groq | gemini
LLM_PROVIDER=groq
LLM_MODEL=<modelo-principal-verificado-en-el-spike>
LLM_FAST_MODEL=<modelo-rapido-verificado-en-el-spike>

# Fallback opcional
LLM_FALLBACK_PROVIDER=gemini
LLM_FALLBACK_MODEL=<modelo-de-fallback-verificado-en-el-spike>

# Claves (nunca se versionan)
GROQ_API_KEY=
GEMINI_API_KEY=
TAVILY_API_KEY=

# Búsqueda: live | frozen
RESEARCH_SEARCH_BACKEND=live

# Persistencia y presupuesto
RESEARCH_DB_PATH=artifacts/research.db
RESEARCH_MAX_LLM_CALLS=30
RESEARCH_MAX_TOKENS=60000
RESEARCH_MAX_ROUNDS=2
RESEARCH_MAX_WORKERS=3
RESEARCH_HITL=false
```

Los identificadores exactos de modelo y los límites vigentes se verificarán en la fase 0 y se documentarán con fecha. No se fijarán cifras de cuota sin comprobarlas.

---

## 2. Objetivo e hipótesis

Construir un equipo de investigación multiagente que reciba una pregunta abierta y entregue un informe con evidencia, citas verificables, limitaciones, traza y consumo medido.

**Hipótesis de ingeniería:**

> Un supervisor con workers especializados, paralelismo acotado y un crítico mejora la cobertura y la verificabilidad en preguntas multi-hop frente a un agente único, a cambio de más tokens y latencia. El proyecto mide ese trade-off y delimita cuándo el multiagente no compensa.

El objetivo no es demostrar que el multiagente siempre gana, sino **medir cuándo aporta valor y a qué coste**.

---

## 3. Alcance del MVP

### Roles

- **Supervisor:** decide el siguiente paso, controla presupuesto y termina. No redacta el informe.
- **Planner:** genera brief, subpreguntas y estrategia de fuentes.
- **Researcher:** subgrafo ReAct por subpregunta; busca, lee y devuelve notas con fuentes.
- **Analyst:** deduplica fuentes, construye tabla de evidencia y detecta huecos.
- **Critic:** verifica soporte de claims, validez de citas y cobertura; devuelve gaps.
- **Writer:** redacta el informe final con citas y limitaciones; no añade hechos nuevos.

### Flujo

```text
Pregunta
   │
   ▼
intake / brief ──► supervisor ◄─────────────────────┐
                     │                               │
        ┌────────────┼────────────┐                  │
        ▼            ▼            ▼                  │
     planner     researcher×N   analyst              │
        │         (Send)          │                  │
        └──────────► notes ◄──────┘                  │
                       │                             │
                       ▼                             │
                    critic ─── gaps / claims ────────┘
                       │ ok
                       ▼
                    writer ──► informe + citas + traza
```

### Salida

```json
{
  "question": "...",
  "answer_markdown": "...",
  "claims": [{"text": "...", "sources": ["..."]}],
  "sources": [{"url": "...", "title": "...", "accessed_at": "..."}],
  "confidence": "high | medium | low",
  "limitations": ["..."],
  "trace_id": "...",
  "usage": {"llm_calls": 18, "tokens": 24310, "latency_s": 74.2}
}
```

### Fuera de alcance

- MCP.
- Fine-tuning.
- GPU.
- Vector DB.
- Despliegue público multi-tenant.
- Autonomía sin límites de presupuesto.
- Un agente distinto por cada microtarea.

---

## 4. Arquitectura y patrones

| Patrón | Implementación | Qué demuestra |
| :--- | :--- | :--- |
| Supervisor / orchestrator-worker | Nodo supervisor con salida estructurada y `Command` | Routing, terminación y control |
| Subgrafos jerárquicos | Researcher como subgrafo con estado propio | Separación de responsabilidades |
| ReAct con herramientas | `ToolNode` + arista condicional | Uso de tools y límites |
| Fan-out / fan-in | `Send` + reducers | Paralelismo acotado y merge |
| Reflection / crítica | Critic con veredicto, gaps y claims sin soporte | Iteración basada en evidencia |
| Handoff explícito | `Command(goto=..., update=...)` | Transferencia de control auditable |
| Blackboard | `ResearchState` tipado con reducers | Memoria compartida controlada |
| Durable execution | Checkpointer SQLite + `thread_id` | Reanudación tras fallo |
| Human-in-the-loop | `interrupt()` antes de publicar o ampliar presupuesto | Aprobación humana |
| Guardrails | Presupuesto, `recursion_limit`, validador de citas | Seguridad operativa |
| Ports & adapters | `SearchBackend`, `LLMBackend` | Live / frozen / fake intercambiables |
| Observabilidad | Trace JSONL + LangSmith opcional | Depuración y auditoría |
| Evaluación | Baselines y ablations | Rigor, no solo demo |

### Reglas de diseño

- El LLM propone; el código impone límites.
- Estado tipado con artefactos Pydantic, no una bolsa de mensajes.
- El crítico debe devolver gaps accionables, no una opinión genérica.
- La misma interfaz de búsqueda se usa en live y frozen.
- Cada run registra proveedor, modelo, versión, prompts, tokens y latencia.
- Los ciclos y el paralelismo tienen topes duros en Python.

### Anti-patrones que se evitarán

- Supervisor con un prompt gigante que lo decide todo.
- Todos los agentes comparten todo el contexto.
- Paralelismo sin control.
- Ciclos infinitos.
- Evaluar solo con una demo visual.
- Depender de un único proveedor.

---

## 5. Stack

| Capa | Tecnología | Motivo |
| :--- | :--- | :--- |
| Runtime | Python 3.12 + `uv` | Convención del repositorio |
| Orquestación | LangGraph 1.2.x | Grafo explícito, `Command`, `Send`, checkpointing, `interrupt`, streaming |
| LLM | Groq y Gemini vía `langchain-openai` | Un cliente compatible con OpenAI; menor lock-in |
| Salidas estructuradas | Pydantic + `with_structured_output` | Routing y artefactos validables |
| Herramientas | Tavily, arXiv, Wikipedia, `trafilatura`, `ddgs` | Búsqueda web, papers y extracción |
| Persistencia | SQLite + `aiosqlite`; trazas JSONL | Checkpoints, caché y runs reanudables |
| API | FastAPI + SSE + HTML estático | Demo con traza en vivo |
| Tests | pytest, pytest-asyncio, `respx`, fake chat model | CI sin claves |
| Ops | Docker, `ruff`, GitHub Actions | Mismo estándar que los otros proyectos |
| Observabilidad | Trace local; LangSmith free tier opcional | Depuración sin dependencia obligatoria |

Versiones observadas al planificar: LangGraph 1.2.16, LangChain 1.4.7, `langgraph-checkpoint-sqlite` 3.1.2, `langchain-openai` 1.7.2. Se fijarán al crear el proyecto y se validarán en Python 3.12.

---

## 6. Estructura objetivo

```text
research-agents/
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── src/
│   ├── config.py
│   ├── models.py
│   ├── state.py
│   ├── graph.py
│   ├── supervisor.py
│   ├── budget.py
│   ├── trace.py
│   ├── cache.py
│   ├── llm.py
│   ├── citations.py
│   ├── cli.py
│   ├── agents/
│   │   ├── planner.py
│   │   ├── researcher.py
│   │   ├── analyst.py
│   │   ├── critic.py
│   │   └── writer.py
│   ├── prompts/
│   └── tools/
│       ├── base.py
│       ├── tavily.py
│       ├── ddg.py
│       ├── arxiv.py
│       ├── wikipedia.py
│       ├── fetch.py
│       ├── extract.py
│       ├── frozen.py
│       └── registry.py
├── app/
│   ├── main.py
│   ├── schemas.py
│   └── static/index.html
├── eval/
│   ├── questions.jsonl
│   ├── rubric.md
│   ├── fixtures/
│   └── results/
├── tests/
├── docs/
│   ├── architecture.md
│   ├── patterns.md
│   ├── evaluation.md
│   ├── security.md
│   └── spike.md
└── scripts/
    ├── run_eval.py
    └── record_fixtures.py
```

---

## 7. Límites y presupuesto

Valores iniciales, ajustables tras el spike:

| Límite | Valor inicial |
| :--- | ---: |
| Subpreguntas por brief | 3 |
| Rondas de investigación | 2 |
| Workers en paralelo | 3 |
| Llamadas a tools por researcher | 3 |
| Llamadas LLM por informe | 30 |
| Tokens por informe | 60 000 |
| Timeout por run | Configurable |
| Reintentos por llamada | Backoff exponencial con jitter |

Los límites se aplican en código, no solo en el prompt. Si se alcanza el presupuesto, el sistema debe cerrar con un informe parcial y una limitación explícita, no fallar en silencio.

**Límites observados el 2026-10-22 (free tier):** Groq `openai/gpt-oss-120b`
8.000 TPM y 200.000 TPD; Gemini `gemini-3.8-flash` 20 peticiones/día; Tavily
1.000 llamadas/mes. El TPD de Groq se agotó con 5 preguntas amplias, por lo que
la Fase 4 debe usar corpus congelado, caché y presupuestos por lote. No se fijan
estas cifras como permanentes.

---

## 8. Evaluación

### Diseño

- 15–20 preguntas en cuatro categorías: factual multi-fuente, comparación, multi-hop y sin respuesta suficiente.
- Corpus congelado con abstracts de arXiv y artículos de Wikipedia, con atribución, URL, licencia y SHA-256.
- Todos los sistemas comparados usan la misma evidencia.
- La demo en vivo usa búsqueda web real; la evaluación usa `FrozenCorpusSearch`.

### Sistemas

| Sistema | Descripción |
| :--- | :--- |
| B0 | Agente único ReAct con las mismas tools y presupuesto |
| B1 | Pipeline fijo: planner → researchers → writer, sin supervisor ni crítico |
| B2 | Equipo completo: supervisor + paralelismo + crítico + validador |

Ablations previstas: sin crítico, sin paralelismo, sin validador de citas.

### Métricas

| Métrica | Definición |
| :--- | :--- |
| Éxito de tarea | Rúbrica 0/1/2 sobre la respuesta final |
| Cobertura factual | Hechos de referencia cubiertos / total |
| Precisión de citas | Citas válidas y relevantes / citas emitidas |
| Recall de fuentes | Fuentes esperadas citadas / total |
| Soporte de claims | Afirmaciones con evidencia verificable / total |
| Abstención | Corrección en preguntas sin evidencia suficiente |
| Eficiencia | Llamadas LLM, tokens, latencia p50/p95, reintentos |
| Robustez | Éxito y varianza en 3 ejecuciones de un subconjunto |

### Rigor

- Juez LLM con rúbrica explícita y temperatura 0.
- Si es posible, juez de un proveedor distinto al evaluado.
- Revisión humana del 20% de las respuestas y reporte de coincidencia.
- Resultados negativos publicados.
- Nada de métricas inventadas: el README solo se completa con resultados reales.

---

## 9. Enfoque de portafolio

El README debe contar una historia de ingeniería, no de framework:

1. Problema y hipótesis.
2. Diseño del equipo y por qué cada rol existe.
3. Evaluación contra baselines.
4. Trade-off calidad / tokens / latencia.
5. Fallos, limitaciones y cuándo NO usar multiagente.
6. Cómo ejecutarlo y cómo cambiar de proveedor.

Artefactos visuales:

- Tabla B0/B1/B2 con calidad y eficiencia.
- Gráfico calidad vs. tokens/latencia.
- Taxonomía de fallos.
- Trace de ejemplo con decisiones del supervisor.
- Informe real con citas.
- Demo GIF o vídeo corto.

Bullet de CV previsto:

> Diseñé y evalué un equipo de investigación multiagente con LangGraph (supervisor, handoffs, paralelismo y checkpointing) sobre APIs gratuitas, comparándolo con un agente único en tareas multi-hop y midiendo calidad de citas, latencia y consumo.

---

## 10. Plan atómico de implementación

### Fase 0 — Spike de viabilidad

**Objetivo:** validar proveedores, modelos, claves y límites antes de construir el sistema completo.

- [x] Crear el directorio `research-agents/`.
- [x] Crear el entorno virtual con `uv venv --python 3.12`.
- [x] Crear `requirements.txt` con las dependencias de runtime.
- [x] Crear `requirements-dev.txt` con pytest, pytest-asyncio, respx y ruff.
- [x] Crear `.env.example` con el esquema de proveedor, modelos, claves y presupuesto.
- [x] Crear `.env` local con las claves reales, sin versionarlo.
- [x] Implementar `src/config.py` con `pydantic-settings` y validación de variables.
- [x] Implementar `src/llm.py` con el adaptador Groq/Gemini basado en `ChatOpenAI`.
- [x] Implementar el fallback de proveedor y el manejo inicial de 429/5xx.
- [x] Crear `scripts/spike_provider.py` para probar salida estructurada y uso de tokens.
- [x] Ejecutar la prueba de salida estructurada con Groq.
- [x] Ejecutar la prueba de salida estructurada con Gemini.
- [x] Ejecutar 5 tareas representativas con cada proveedor.
- [x] Registrar latencia, tokens, errores 429 y calidad observada.
- [x] Documentar los límites vigentes y los IDs de modelo en `docs/spike.md` con fecha.
- [x] Decidir proveedor principal, fallback y modelos rápido/principal.
- [x] Revisar el gate: 5/5 tareas completadas sin errores no recuperables y salida estructurada válida en al menos 4/5.
- [x] Si el gate no se cumple, ajustar proveedor, modelo o alcance antes de continuar.

**Resultado del spike:** Groq `openai/gpt-oss-120b` 5/5 y ~0,97 s de latencia media;
Gemini `gemini-3.8-flash` 4/5 por un 503 transitorio. Groq queda como principal y
Gemini como fallback. Tavily se reserva para la Fase 2 con un presupuesto de 1.000
llamadas mensuales.

**Criterio de salida:** decisión documentada y `.env` funcionando con ambos proveedores.

### Fase 1 — Núcleo del grafo

**Objetivo:** tener un grafo completo ejecutable con LLM falso y tests deterministas.

- [x] Definir los modelos de dominio en `src/models.py`.
- [x] Definir `ResearchState` con reducers en `src/state.py`.
- [x] Implementar `BudgetState` y las funciones de control en `src/budget.py`.
- [x] Crear los prompts versionados de supervisor, planner, researcher, analyst, critic y writer.
- [x] Finalizar el adaptador LLM con selección por `.env`, validación de clave y extracción de usage.
- [x] Implementar el fallback de salida estructurada (`json_schema` → `function_calling` → `json_mode`).
- [x] Implementar el registro de trazas en `src/trace.py`.
- [x] Implementar el nodo supervisor con esquema de ruta y topes duros.
- [x] Implementar el nodo planner.
- [x] Implementar el nodo researcher secuencial y el protocolo de backend.
- [x] Implementar el nodo analyst.
- [x] Implementar el nodo critic con verificación determinista de citas.
- [x] Implementar el nodo writer y el informe de respaldo.
- [x] Ensamblar el grafo en `src/graph.py` con `START`, `END` y aristas condicionales.
- [x] Crear un fake LLM con respuestas guionizadas en `tests/fakes.py`.
- [x] Crear tests de modelos y validación Pydantic.
- [x] Crear tests de reducers del estado.
- [x] Crear tests del presupuesto y de los topes.
- [x] Crear test del esquema de routing del supervisor.
- [x] Crear test del camino feliz del grafo.
- [x] Crear test del ciclo critic → researcher.
- [x] Crear test de presupuesto agotado.
- [x] Crear test de pregunta sin evidencia suficiente.
- [x] Ejecutar `ruff check src tests`.
- [x] Ejecutar `pytest -q` y dejar todo en verde.

**Criterio de salida:** el grafo compila, corre de extremo a extremo con LLM falso y los caminos críticos están cubiertos.

### Fase 2 — Herramientas, caché y paralelismo

**Objetivo:** pasar de un grafo simulado a investigación real con fuentes.

- [x] Definir `SearchBackend`, `SearchResult` y `FetchedPage` en `src/tools/base.py`.
- [x] Implementar el subgrafo researcher con `ToolNode` y límite de pasos.
- [x] Implementar el backend de Tavily.
- [x] Implementar el backend de DuckDuckGo como fallback.
- [x] Implementar el backend de arXiv.
- [x] Implementar el backend de Wikipedia.
- [x] Implementar la descarga de páginas con validación de URL y protección SSRF.
- [x] Implementar la extracción de contenido con `trafilatura`.
- [x] Implementar la caché SQLite con TTL y claves canónicas.
- [x] Añadir `RESEARCH_TAVILY_MONTHLY_BUDGET=1000` a la configuración.
- [x] Implementar un contador persistente de llamadas mensuales a Tavily.
- [x] Rechazar búsquedas con un error explícito al agotar el presupuesto mensual.
- [x] Implementar la canonicalización y deduplicación de fuentes.
- [x] Implementar el registro de tools y la selección por configuración.
- [x] Implementar el fan-out con `Send` para las subpreguntas.
- [x] Implementar los reducers definitivos de notas y fuentes.
- [x] Implementar el validador de citas en `src/citations.py`.
- [x] Crear tests de Tavily con `respx`.
- [x] Crear tests de DuckDuckGo.
- [x] Crear tests de arXiv.
- [x] Crear tests de Wikipedia.
- [x] Crear tests de validación de URL y SSRF.
- [x] Crear tests de caché: hit, miss y expiración.
- [x] Crear tests de deduplicación y canonicalización.
- [x] Crear tests del validador de citas.
- [x] Crear un test de integración del grafo con tools falsas.
- [x] Ejecutar 5 preguntas reales con el proveedor principal.
- [x] Revisar las trazas y corregir prompts o límites.
- [x] Guardar las trazas de ejemplo en `docs/examples/` sin datos sensibles.

**Criterio de salida:** 5 preguntas reales completadas sin intervención manual, con fuentes y citas válidas.

**Resultado:** 5/5 preguntas completadas con Groq. Las trazas curadas están en
`research-agents/docs/examples/`; las cinco tienen fuentes y citas válidas. Una
traza (RAG) conserva un `JSONDecodeError` del analista recuperado por el fallback
determinista. `ruff` limpio y 93 tests en verde. El TPD de Groq (200.000) se agotó
al intentar repetir esa pregunta; no se pudieron hacer más runs reales.


### Fase 3 — Crítica, HITL y durabilidad

**Objetivo:** hacer el sistema robusto ante fallos y controlable por una persona.

- [x] Definir el esquema final de `Critique`.
- [x] Implementar la política de máximo 2 rondas de investigación.
- [x] Implementar el routing de gaps del critic al researcher.
- [x] Implementar la comprobación de soporte de claims.
- [x] Implementar `interrupt()` antes del writer cuando HITL esté activo.
- [x] Implementar el camino de reanudación tras aprobación.
- [x] Implementar el camino de reanudación tras rechazo.
- [x] Configurar el checkpointer SQLite asíncrono.
- [x] Implementar el ciclo de vida de `thread_id`.
- [x] Ampliar la traza con nodo, modelo, tokens, latencia, tools y errores.
- [x] Implementar las condiciones de terminación por presupuesto, rondas y `recursion_limit`.
- [x] Crear test de aprobación HITL.
- [x] Crear test de rechazo HITL.
- [x] Crear test de reanudación tras fallo simulado.
- [x] Crear test del tope de rondas.
- [x] Crear test del esquema de traza.
- [x] Simular 429 y timeout y verificar la recuperación.
- [x] Ejecutar un run real, interrumpirlo y reanudarlo con el mismo `thread_id`.
- [x] Documentar el procedimiento de resume.

**Criterio de salida:** un run interrumpido se reanuda sin perder estado y los ciclos quedan acotados.

**Resultado:** Fase 3 cerrada el 2026-10-23. `Critique` incorpora
`supported_claim_ids`; el critic aplica una comprobación determinista de citas y
el supervisor envía los gaps al researcher solo si quedan rondas y presupuesto.
El HITL usa `interrupt()` en el nodo `approval`; la aprobación continúa al writer
y el rechazo termina con `status="failed"` sin informe. El checkpointer
`AsyncSqliteSaver` serializa con una allowlist de modelos y el CLI conserva el
`thread_id` para reanudar en otro proceso. `ruff` limpio y 103 tests en verde.

Run real HITL `phase3-hitl-20261023`: 10 llamadas, 24.652 tokens, 3 búsquedas y
301,8 s; el writer terminó con `fallback=False` y sin errores. La traza curada
está en `research-agents/docs/phase3/hitl-resume.json`. Un intento anterior
expuso un `413` del writer (8.046 tokens frente a 8.000 TPM); se recortaron notas
y snippets y el run posterior validó el arreglo. El fallo de proceso se cubre con
un `KeyboardInterrupt` simulado y reanudación desde el checkpoint.

### Fase 4 — Evaluación

**Objetivo:** medir el sistema contra baselines y producir resultados reales.

- [ ] Definir el esquema de preguntas de evaluación.
- [ ] Seleccionar 15–20 preguntas en las cuatro categorías.
- [ ] Verificar la licencia de las fuentes elegidas.
- [ ] Congelar el corpus de evaluación con URL, fecha, licencia y SHA-256.
- [ ] Implementar `FrozenCorpusSearch`.
- [ ] Implementar el runner de evaluación reanudable.
- [ ] Implementar la rúbrica del juez.
- [ ] Implementar el parser y la validación de la salida del juez.
- [ ] Implementar la métrica de éxito de tarea.
- [ ] Implementar la métrica de cobertura factual.
- [ ] Implementar las métricas de citas.
- [ ] Implementar la métrica de soporte de claims.
- [ ] Implementar la métrica de abstención.
- [ ] Implementar las métricas de eficiencia.
- [ ] Implementar el baseline B0 de agente único.
- [ ] Implementar el baseline B1 de pipeline fijo.
- [ ] Implementar el sistema B2 completo.
- [ ] Implementar los flags de ablación.
- [ ] Ejecutar un smoke eval de 2 preguntas.
- [ ] Ejecutar la evaluación completa B0/B1/B2 por lotes.
- [ ] Ejecutar 3 repeticiones sobre el subconjunto de robustez.
- [ ] Revisar manualmente el 20% de las respuestas.
- [ ] Construir la taxonomía de fallos.
- [ ] Guardar los resultados crudos en `eval/results/`.
- [ ] Generar la tabla resumen y el gráfico calidad vs. coste.
- [ ] Escribir `docs/evaluation.md` con metodología, resultados y limitaciones.

**Criterio de salida:** resultados reales y reproducibles para B0/B1/B2, con fallos analizados y sin métricas inventadas.

### Fase 5 — Producto

**Objetivo:** ofrecer una demo usable por CLI, API y UI.

- [ ] Crear la app FastAPI y el ciclo de vida de recursos.
- [ ] Definir los esquemas de request/response.
- [ ] Implementar `POST /v1/research`.
- [ ] Implementar `GET /v1/research/{id}`.
- [ ] Implementar `GET /v1/research/{id}/events` con SSE.
- [ ] Implementar `POST /v1/research/{id}/approve` para HITL.
- [ ] Implementar `GET /health` con estado de proveedor, modelo y checkpointer.
- [ ] Crear la UI mínima de pregunta, traza y resultado.
- [ ] Implementar el comando CLI `research`.
- [ ] Implementar el comando CLI `resume`.
- [ ] Crear el `Dockerfile`.
- [ ] Crear `.dockerignore`.
- [ ] Crear `docker-compose.yml` con volumen para SQLite y `env_file`.
- [ ] Crear tests de API con un grafo falso.
- [ ] Ejecutar una prueba E2E real con proveedor en vivo.
- [ ] Verificar SSE, HITL y resume desde la API.
- [ ] Revisar que las claves no aparezcan en logs ni respuestas.
- [ ] Añadir rate limit básico y CORS local.
- [ ] Documentar los comandos de ejecución.

**Criterio de salida:** un comando levanta la demo y una pregunta real produce informe, citas, traza y usage.

### Fase 6 — Documentación, CI y cierre

**Objetivo:** dejar el proyecto publicable y reproducible.

- [ ] Crear el `README.md` con problema, hipótesis y arquitectura.
- [ ] Añadir la tabla de resultados reales al README.
- [ ] Añadir las limitaciones y los casos en que NO conviene multiagente.
- [ ] Añadir el diagrama de arquitectura.
- [ ] Escribir `docs/architecture.md`.
- [ ] Escribir `docs/patterns.md` con el mapa patrón → código → trade-off.
- [ ] Revisar `docs/evaluation.md`.
- [ ] Escribir `docs/security.md` sobre prompt injection, secretos y copyright.
- [ ] Revisar `docs/spike.md` y fechar los límites medidos.
- [ ] Revisar `.env.example` y sus comentarios.
- [ ] Añadir el job `research-agents` al CI.
- [ ] Verificar que el CI no necesita claves ni red externa.
- [ ] Añadir la fila del cuarto proyecto al `README.md` raíz.
- [ ] Actualizar el texto “los tres proyectos” a cuatro.
- [ ] Actualizar `AGENTS.md` con el estado real.
- [ ] Actualizar `.gitignore` para artefactos, `.env` y fixtures pesados.
- [ ] Ejecutar `ruff check` y `pytest` en local.
- [ ] Hacer una prueba de clonado limpio en `/tmp`.
- [ ] Ejecutar la demo de fixtures en el clon limpio.
- [ ] Revisar `git status` y confirmar que no hay secretos ni artefactos.
- [ ] Verificar que los comandos del README funcionan tal como están escritos.
- [ ] Hacer commits en español, en imperativo.
- [ ] Revisar que no queden placeholders ni métricas sin respaldo.
- [ ] Confirmar que no se hará `push --force` sin autorización.

**Criterio de salida:** CI verde, README reproducible, demo funcional y repositorio limpio.

---

## 11. Definition of Done

- [ ] Un comando instala dependencias y ejecuta los tests sin claves.
- [ ] Un comando ejecuta la evaluación con claves y reproduce la tabla del README.
- [ ] Un comando levanta la demo local.
- [ ] El README explica problema, datos, arquitectura, resultados y limitaciones.
- [ ] Los resultados incluyen B0/B1/B2 y al menos una ablación.
- [ ] Hay análisis de fallos y una sección de “cuándo no usar multiagente”.
- [ ] El CI está en verde sin llamadas reales.
- [ ] No hay secretos, corpus completos ni artefactos pesados en Git.
- [ ] El proyecto se puede clonar y ejecutar en un entorno limpio.
- [ ] La documentación está en español y el código en inglés.

---

## 12. Riesgos y mitigaciones

| Riesgo | Mitigación |
| :--- | :--- |
| 429 / TPM bajo | Backoff, fallback, menos workers, contextos resumidos y caché |
| No determinismo | Temperatura 0, 3 runs en subconjunto, trazas y varianza reportada |
| Web volátil | Corpus congelado para evaluación; demo live separada |
| Calidad irregular del modelo | Model tiering, critic, fallback y preguntas acotadas |
| Scope creep | MVP con 5 roles y 15–20 preguntas; extras fuera |
| Prompt injection desde webs | Contenido no confiable, delimitadores, allowlist y tests con fixtures maliciosos |
| Demo pública con clave | Clave en servidor, rate limit y modo fixture; nunca exponerla |
| Copyright | URLs y extractos cortos; no versionar páginas completas |
| Evaluación subjetiva | Rúbrica, juez de otro proveedor y revisión humana del 20% |

---

## 13. Registro de progreso

| Fecha | Fase | Nota |
| :--- | :--- | :--- |
| 2026-10-22 | Plan | Decisiones D1–D10 cerradas; pendiente de implementación. |
| 2026-10-22 | Fase 0 | Estructura, venv, dependencias, configuración, adaptador LLM y script de spike listos. `ruff` limpio y 11 tests en verde. |
| 2026-10-22 | Fase 0 | Spike ejecutado: Groq `openai/gpt-oss-120b` 5/5 (~0,97 s); Gemini `gemini-3.8-flash` 4/5 por un 503 transitorio. Groq principal, Gemini fallback. Tavily: presupuesto de 1.000 llamadas/mes. |
| 2026-10-22 | Fase 1 | Núcleo del grafo completo con modelos, estado, presupuesto, prompts, supervisor, planner, researcher secuencial, analyst, critic, writer y trazas. `ruff` limpio y 38 tests en verde. Backend con `ToolNode` trasladado a Fase 2. |
| 2026-10-22 | Fase 2 | Tavily, DuckDuckGo, arXiv, Wikipedia, fetch con SSRF, caché SQLite, presupuesto mensual, router, `ToolNode`, fan-out con `Send`, `max_concurrency`, validador de citas y trazas. `ruff` limpio y 93 tests en verde. |
| 2026-10-22 | Fase 2 | Cinco preguntas reales con Groq: 55 llamadas, 136.553 tokens, 17 búsquedas y 2.978 s acumulados. Trazas curadas en `research-agents/docs/examples/`. Una traza de RAG conserva un error de analista recuperado. |
| 2026-10-22 | Fase 2 | Límites observados: Groq 8.000 TPM y 200.000 TPD (agotado); Gemini 20 peticiones/día (agotado); Tavily 34/1.000. Se compactaron entradas y se subió la salida a 3.000 tokens. |
| 2026-10-23 | Fase 3 | `Critique.supported_claim_ids`, soporte determinista de claims, máximo de rondas, routing de gaps al researcher, nodo `approval` con `interrupt()`, checkpointer `AsyncSqliteSaver` con allowlist y CLI `--resume`. `ruff` limpio y 103 tests. |
| 2026-10-23 | Fase 3 | Cuotas verificadas: Groq y Gemini respondieron 200; Tavily 34/1.000 (límite mensual). Run HITL real `phase3-hitl-20261023`: 10 llamadas, 24.652 tokens, 3 búsquedas, 301,8 s; writer sin fallback y sin errores. Traza en `docs/phase3/`. |
| 2026-10-23 | Fase 3 | Un resume anterior expuso `413` del writer (8.046/8.000 TPM). Se recortaron notas a 300 caracteres y snippets a 120; el run HITL posterior validó el writer real. |
|  |  |  |

---

## 14. Próximo paso

Continuar con la **Fase 4 — Evaluación**. Las cuotas de Groq y Gemini se
restablecieron el 2026-10-23, pero la evaluación debe usar el corpus congelado y
no depender de búsqueda web en vivo. El siguiente trabajo es definir el conjunto
de 15–20 preguntas, congelar las fuentes con licencia y SHA-256, implementar
`FrozenCorpusSearch` y el runner reanudable. La API/UI/Docker quedan para la
Fase 5, después de tener métricas reales.
