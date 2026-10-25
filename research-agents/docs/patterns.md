# Patrones de diseño y trade-offs

> Mapa entre los patrones que aparecen en el código, su implementación concreta y
> el coste de haberlos elegido. No es un catálogo teórico: cada fila apunta a
> código que existe y a una limitación observada.

## Resumen

| Patrón | Dónde vive | Qué aporta | Coste o límite |
| :--- | :--- | :--- | :--- |
| Supervisor / routing por estado | `src/agents/supervisor.py` | Ruta explícita, barata y predecible | La rama LLM no se alcanza con las guardas actuales; el routing real es determinista |
| Fan-out / fan-in con `Send` | `src/agents/researcher.py`, `src/state.py` | Paralelismo real y ninguna subpregunta descartada | El presupuesto de cada worker usa un snapshot; la suma concurrente puede superar el límite |
| Blackboard tipado | `src/state.py`, `src/models.py` | Estado único, inspeccionable y con reducers | Acoplamiento implícito y last-write-wins en campos escalares |
| Contratos estructurados | `src/models.py`, `src/eval/models.py` | Salidas validadas, `extra="forbid"` | Los modelos gratuitos fallan a veces al emitir el schema; hay que mantener fallbacks |
| Adapter / Strategy | `src/llm.py`, `src/tools/base.py`, backends de búsqueda | Cambiar proveedor o buscador sin tocar los nodos | Cada adaptador tiene semántica distinta |
| Composite / fallback router | `SearchRouter` en `src/tools/registry.py` | Un fallo de Tavily no bloquea la investigación | El fallback cambia la calidad y el tipo de fuentes; los reintentos consumen Tavily |
| Fallback determinista por nodo | `fallback_plan`, `fallback_analysis`, `fallback_critique`, `fallback_draft` | El run siempre produce un informe | Puede enmascarar errores y dejar `done` con confianza baja |
| Dependency injection | `AgentServices`, `build_services`, `create_app(...)` | Tests con fakes y sustitución de backends | Wiring manual; la variante HITL comparte clientes mutables |
| Repository / cache | `src/cache.py`, `src/tavily_budget.py` | Persistencia local y ahorro de cuota | No hay repositorio de runs; la caché no se purga salvo por TTL |
| Budget guard / cuota | `src/budget.py`, `src/llm.py`, `src/tavily_budget.py` | Evita runs infinitos y agotar cuotas | No es un circuit breaker clásico; el presupuesto paralelo no es atómico |
| HITL con `interrupt()` | `src/agents/approval.py`, API y CLI | Pausa real y reanudación en otro proceso | El feedback no se reinyecta; el cliente puede desactivar HITL en la API |
| Resumability | `AsyncSqliteSaver`, `EvaluationRunner` | Recupera runs y lotes interrumpidos | Depende de `thread_id`/`run_id`; el registro API no sobrevive al reinicio |
| Observabilidad por traza | `src/trace.py`, SSE, `artifacts/traces/` | Auditoría de nodos, modelos, tokens, latencia y errores | Sin OpenTelemetry ni LangSmith; la traza SSE vive en memoria |
| Arnés de evaluación | `src/eval/` | Comparación reproducible con corpus congelado | Corpus pequeño, juez no independiente en la práctica y métricas léxicas |
| Defensa en profundidad | SSRF, allowlist, redacción, Docker no root | Reduce superficie de ataque | Quedan DNS rebinding, falta de auth y límites de descarga |

## 1. Supervisor y routing por estado

**Código:** `src/agents/supervisor.py`, `build_graph()` en `src/graph.py`.

El supervisor no es un nodo que “piensa” libremente. `allowed_routes()` aplica
guardas sobre el estado y devuelve las rutas válidas; el nodo elige la primera y
solo consultaría al LLM si hubiera más de una. En la implementación actual
siempre hay una sola ruta posible, así que el flujo es determinista.

**Por qué:** evita una llamada LLM por transición, hace el run reproducible y
facilita tests. **Coste:** el sistema es menos autónomo de lo que sugiere la
palabra “supervisor”. Si en el futuro se quiere routing semántico, hay que
cambiar las guardas y añadir un test que cubra la decisión real, no solo la rama
monkeypatcheada.

## 2. Fan-out / fan-in con `Send`

**Código:** `src/agents/researcher.py`, reducers en `src/state.py`.

El planner produce hasta cuatro subpreguntas. El nodo `researcher` emite un
`Send` por cada una y LangGraph ejecuta los workers con `max_concurrency`. El
fan-in lo hacen los reducers: notas por `note_id`, fuentes por `source_id`, usage
sumado, trazas y errores concatenados.

**Por qué:** no se descarta trabajo cuando hay más subpreguntas que workers y el
paralelismo reduce la latencia. **Coste:** cada worker recibe un snapshot del
usage; su presupuesto no incluye el gasto de los demás. Además, cada ronda
re-despacha todas las subpreguntas y las notas se sobrescriben por `note_id`
estable. Es simple, pero puede multiplicar llamadas y tokens.

## 3. Blackboard tipado

**Código:** `ResearchState` en `src/state.py`.

Todos los nodos leen y escriben un estado compartido con campos tipados. Los
campos acumulativos tienen reducer; los escalares son last-write-wins.

**Por qué:** el estado es fácil de inspeccionar, serializar y reanudar con el
checkpointer. **Coste:** el acoplamiento entre nodos es implícito y no hay
historial por campo salvo la traza. Un nodo que olvide limpiar `analysis` o
`critique` puede dejar un estado incoherente.

## 4. Contratos estructurados

**Código:** `src/models.py`, `src/eval/models.py`, `parse_research_answer()`.

Los roles devuelven modelos Pydantic con `extra="forbid"`. `ResearchAnswer`
excluye las fuentes para que el modelo no invente URLs; las fuentes se
reconstruyen desde los `ToolMessage`. El juez también tiene un contrato validado
localmente y se reintenta una vez si viola la rúbrica.

**Por qué:** reduce errores de formato y alucinaciones de citas. **Coste:** los
modelos gratuitos no siempre respetan `json_schema`; el cliente prueba
`function_calling`, `json_mode` y un fallback de JSON textual. Esa cadena añade
complejidad y llamadas.

## 5. Adapter y Strategy

**Código:** `LLMClient` en `src/llm.py`; `SearchBackend` en
`src/tools/base.py`; backends Tavily, DuckDuckGo, Wikipedia, arXiv y frozen.

Los nodos dependen de protocolos (`StructuredLLM`, `ResearcherBackend`,
`SearchBackend`), no de SDKs concretos. `build_services()` decide qué implementación
inyectar.

**Por qué:** los tests usan fakes y se puede cambiar de proveedor sin tocar el
grafo. **Coste:** los adaptadores no son equivalentes. Frozen es determinista y
offline; Tavily y DDG devuelven resultados distintos; Gemini puede no soportar
herramientas. Un fallback silencioso puede cambiar la calidad sin que el usuario
lo note.

## 6. Composite y fallback router

**Código:** `SearchRouter` en `src/tools/registry.py`.

El router intenta el backend primario; si lanza `SearchError` o devuelve una
lista vacía, prueba el fallback. El agotamiento de Tavily es un `SearchError`, así
que también cae al fallback.

**Por qué:** una cuota agotada o un fallo de red no bloquean la investigación.
**Coste:** el fallback puede devolver evidencia peor y no queda claro en el
informe qué backend se usó en cada búsqueda; la traza sí lo registra, pero el
usuario debe leerla.

## 7. Fallback determinista por nodo

**Código:** `fallback_plan()`, `fallback_analysis()`, `fallback_critique()`,
`fallback_draft()` y los `except BudgetExceeded` de cada nodo.

Si el LLM falla o se agota el presupuesto, el nodo produce una versión
determinista con la evidencia disponible. El run termina con informe y
`confidence="low"` o limitaciones.

**Por qué:** el producto no se queda sin respuesta y la demo es robusta ante
cuotas. **Coste:** puede enmascarar errores. Un estado `done` o `completed` no
garantiza calidad; por eso la evaluación usa el juez y la revisión humana, no el
status.

## 8. Dependency injection

**Código:** `AgentServices` en `src/agents/base.py`, `build_services()` en
`src/services.py`, `create_app(settings=..., graph=..., manager=...)`.

Las dependencias se pasan explícitamente. Los tests inyectan un `FakeLLM`, un
`StubResearcher` y grafos falsos; la API permite inyectar un manager o un grafo.

**Por qué:** tests rápidos y sin red. **Coste:** el wiring es manual y la API
construye dos grafos (normal y HITL) que comparten clientes mutables; un cambio de
estado en un cliente puede afectar a ambos.

## 9. Repository y cache

**Código:** `SQLiteCache` en `src/cache.py`; `TavilyBudget` en
`src/tavily_budget.py`.

La caché guarda búsquedas y páginas con TTL; el presupuesto de Tavily usa una
tabla con periodo mensual y `BEGIN IMMEDIATE`.

**Por qué:** menos llamadas reales y cuota controlada. **Coste:** no hay una
abstracción de repositorio para runs o informes; la caché no se purga
automáticamente y no se invalida por versión de esquema. `clear_expired()` existe,
pero no se llama de forma programada.

## 10. Budget guard y cuota

**Código:** `BudgetGuard` en `src/budget.py`; `TokenRateLimiter` en `src/llm.py`;
`TavilyBudget`.

Hay límites de llamadas, tokens, rondas, pasos de herramienta y búsquedas. El
rate limiter espera antes de llamar para respetar el TPM.

**Por qué:** evita runs infinitos y protege el free tier. **Coste:** no es un
circuit breaker clásico (no hay estado “abierto” por tasa de errores), los
reintentos no siempre se contabilizan y el presupuesto de workers paralelos no es
global. Los límites ajustados producen informes de baja confianza, como muestra
la prueba E2E de la Fase 5.

## 11. Human-in-the-loop con `interrupt()`

**Código:** `src/agents/approval.py`, `RunManager.approve()`, `scripts/research.py`.

Antes del writer, el grafo llama a `interrupt()` con un payload de revisión. La
API y el CLI reanudan con `Command(resume={"approved": ..., "feedback": ...})`.

**Por qué:** una persona puede bloquear un informe antes de que se redacte.
**Coste:** el feedback no se reinyecta; un rechazo termina sin informe. El
cliente de la API puede enviar `"hitl": false` y evitar la pausa aunque el
servidor la tenga configurada. No hay autenticación de revisor.

## 12. Resumability

**Código:** `src/checkpoint.py`; `EvaluationRunner` en `src/eval/runner.py`.

El checkpointer guarda el estado por `thread_id` con `AsyncSqliteSaver` y una
allowlist de tipos. La evaluación guarda un JSONL por ejecución y reanuda por
`(pregunta, sistema, repetición)`.

**Por qué:** un corte de proceso o de cuota no pierde el trabajo anterior.
**Coste:** depende de IDs estables. El registro de runs de la API es en memoria;
tras reiniciar, `GET` no encuentra runs antiguos. Reutilizar un `run_id` tras un
reinicio puede colisionar con un checkpoint previo porque el manager no consulta
el checkpointer antes de crear el run.

## 13. Observabilidad por traza

**Código:** `src/trace.py`, `RunManager._publish_trace()`, SSE y
`artifacts/traces/`.

Cada nodo emite eventos con nodo, tipo, datos, modelo, tokens y latencia. La API
redacta secretos antes de publicar; el CLI guarda la traza completa en un archivo
ignorado por Git.

**Por qué:** permite auditar qué pasó y depurar fallos de proveedor. **Coste:** no
hay OpenTelemetry ni LangSmith; la traza SSE vive en memoria y no tiene cota. La
redacción solo se aplica en la API, no en el CLI ni en los registros de
evaluación.

## 14. Arnés de evaluación

**Código:** `src/eval/`.

El corpus congelado elimina la variabilidad de la web. El runner compara B0, B1 y
B2 con las mismas herramientas y límites, y genera resumen y SVG.

**Por qué:** sin un corpus fijo no se pueden comparar sistemas de forma honesta.
**Coste:** el corpus es pequeño y una foto de Wikipedia; la cobertura es léxica;
la precisión de citas es estricta; el juez no es independiente en la práctica; y
B1 es secuencial mientras B2 es paralelo. Los resultados parciales deben
etiquetarse como tales.

## 15. Defensa en profundidad

**Código:** `src/tools/urls.py`, `src/tools/fetch.py`, `src/citations.py`,
`src/checkpoint.py`, `app/manager.py`, `Dockerfile`.

Hay validación de URLs y redirecciones, allowlist de herramientas, allowlist de
tipos en el checkpointer, redacción de errores en la API y usuario no root en
Docker.

**Por qué:** reduce SSRF, deserialización arbitraria y fuga de claves. **Coste:**
quedan DNS rebinding, descarga completa antes de truncar, falta de autenticación
y rate limit solo en memoria. Los detalles están en [`security.md`](./security.md).

## ¿Cuándo no usar el equipo completo?

El grafo B2 no es la respuesta por defecto. Los resultados de la evaluación y la
propia arquitectura sugieren estos casos:

- **Preguntas simples y autocontenidas:** B0 puede responder con una o dos
  llamadas y mucho menos coste. B1/B2 añaden planner, analyst, critic y writer.
- **Presupuesto muy ajustado o free tier:** el fan-out y las rondas pueden agotar
  la cuota. Un pipeline fijo o una sola llamada es más predecible.
- **Latencia crítica:** B2 incluye varias llamadas secuenciales y esperas del
  rate limiter; B0 es mucho más rápido.
- **Necesidad de reproducibilidad estricta:** los modelos generativos añaden
  variabilidad. El corpus congelado y temperatura 0 ayudan, pero no la eliminan.
- **Cuando no hay verificación semántica:** el critic solo comprueba estructura
  de citas. Si la respuesta exige verdad factual, hace falta revisión humana o un
  verificador específico.
- **Cuando el coste de un error es alto:** HITL puede ayudar, pero no garantiza
  calidad y no reinyecta feedback. Para dominios regulados se necesita un proceso
  de validación más fuerte.

La comparación honesta es: usar B0/B1 cuando basten y reservar B2 para preguntas
que realmente se beneficien de descomposición, evidencia múltiple y crítica.
