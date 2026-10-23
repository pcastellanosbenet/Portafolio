# research-agents

Equipo de investigación multiagente construido con **LangGraph** y APIs compatibles
con OpenAI. Recibe una pregunta abierta, la descompone, busca evidencia en la web y
en fuentes académicas, verifica las citas y entrega un informe en Markdown con
trazabilidad de herramientas, tokens y latencia.

> **Estado:** Fase 3 de 6 completada (2026-10-23). El CLI, el grafo con
> herramientas reales, el HITL y la reanudación con checkpointer SQLite están
> cubiertos por tests. La evaluación sistemática (Fase 4) y la API FastAPI/SSE,
> la UI y Docker (Fase 5) todavía no están implementados.

## Qué demuestra

- Orquestación **supervisor → planner → researchers → analyst → critic → writer**
  con estado tipado y handoffs explícitos.
- Fan-out con `Send` y paralelismo acotado mediante `max_concurrency`; las
  subpreguntas no se descartan cuando hay más que workers.
- Investigación con **Tavily**, **arXiv**, **Wikipedia**, **DuckDuckGo** como
  fallback y descarga de páginas con extracción de texto.
- Caché SQLite con TTL, presupuesto mensual persistente de Tavily y límites de
  llamadas, tokens, pasos y rondas.
- Protección SSRF en la descarga de URLs, incluida la validación de redirecciones.
- Validador de citas: cada claim debe apuntar a fuentes recuperadas y las
  referencias del informe se normalizan antes de validarse. El critic añade una
  comprobación determinista de soporte estructural de cada claim.
- **HITL real:** `interrupt()` antes del writer, aprobación o rechazo y
  reanudación en otro proceso con el mismo `thread_id`.
- **Durabilidad:** checkpointer `AsyncSqliteSaver` con serialización JSON+ y una
  allowlist explícita de tipos de la aplicación.
- Trazas reproducibles sin claves ni datos privados. Cinco ejecuciones reales de
  la Fase 2 están en [`docs/examples/`](./docs/examples/) y una ejecución HITL
  reanudada está en [`docs/phase3/`](./docs/phase3/).

## Arquitectura

```text
Pregunta
   │
   ▼
supervisor ◄─────────────────────────────────────────────┐
   │                                                     │
   ├──► planner ──► researcher ──► researcher_worker ×N  │
   │                   (Send + max_concurrency)           │
   │                              │                       │
   │                              ▼                       │
   ├──► analyst ──────────────► notes/sources ────────────┤
   │                              │                       │
   ├──► critic ──────────────► gaps/veredicto ────────────┤
   │                              │                       │
   └──► approval (HITL) ─────► writer ──► informe + citas + traza
                                  │
                                  └──► fin (o rechazo sin informe)
```

El supervisor decide la siguiente ruta. El planner produce entre 1 y 4
subpreguntas. El researcher es un subgrafo ReAct con `ToolNode`: puede buscar,
leer una página y finalizar con un JSON estructurado. El analyst consolida la
evidencia; el critic comprueba cobertura y citas; el writer redacta sin introducir
hechos nuevos. Si el critic pide revisar y quedan rondas y presupuesto, el
supervisor vuelve al researcher; si no, pasa al writer. Con HITL activo, la ruta
al writer atraviesa el nodo `approval`.

## Resultados reales

Las cinco preguntas se ejecutaron con Groq `openai/gpt-oss-120b` como proveedor
principal y `openai/gpt-oss-20b` para tareas rápidas. El fallback de Gemini estaba
desactivado porque su cuota gratuita se había agotado.

| Pregunta | Confianza | Claims | Fuentes | Búsquedas | Llamadas | Tokens | Latencia | Errores |
| :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| IA agéntica y sus limitaciones | media | 4 | 15 | 3 | 13 | 33.827 | 838,9 s | 0 |
| Atención en transformers | alta | 4 | 17 | 4 | 12 | 33.222 | 597,2 s | 0 |
| Evaluación de sistemas RAG | media | 4 | 19 | 4 | 11 | 27.339 | 590,6 s | 1 |
| LoRA frente a fine-tuning completo | alta | 4 | 10 | 3 | 9 | 18.416 | 416,8 s | 0 |
| Métricas de clasificación de imágenes | media | 3 | 15 | 3 | 10 | 23.749 | 534,6 s | 0 |
| **Total** | | **19** | **76** | **17** | **55** | **136.553** | **2.978 s** | **1** |

### Run HITL real (Fase 3)

| Pregunta | Confianza | Claims | Fuentes | Búsquedas | Llamadas | Tokens | Latencia | Errores |
| :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| Transformer y sus usos en NLP | alta | 4 | 15 | 3 | 10 | 24.652 | 301,8 s | 0 |

Este run se ejecutó con 1 worker, 1 paso de herramienta y 1 ronda. Se pausó en
`approval`, el proceso terminó y se reanudó en un segundo proceso con
`--resume --thread-id phase3-hitl-20261023 --approve`. El writer terminó con
`fallback=False` y sin errores. La traza curada está en
[`docs/phase3/hitl-resume.json`](./docs/phase3/hitl-resume.json).

Una prueba anterior sí expuso un `413`: el writer solicitó 8.046 tokens frente a
un límite de 8.000 TPM y cayó al informe determinista. Después se recortaron las
notas a 300 caracteres y los snippets a 120 antes de llamar al writer; el run
HITL de la tabla es la validación limpia de ese cambio.

La latencia incluye las esperas del limitador de tokens por minuto; no es la
latencia pura de los proveedores. Los tokens son los reportados por las APIs.

**Nota sobre la traza de RAG:** el analista devolvió un JSON truncado
(`Unterminated string`) y el nodo usó el análisis determinista de respaldo. El
informe se completó con 4 claims, 19 fuentes y citas válidas; el error quedó
registrado en la traza. A partir de ese caso se aumentó
`LLM_MAX_OUTPUT_TOKENS` a 3.000 y se compactaron las fuentes y notas que reciben
el analyst, el critic y el writer. No se pudo repetir la ejecución para obtener
una traza limpia porque la cuota diaria de Groq se agotó durante la sesión.

### Consumo de cuotas observado

| Recurso | Límite observado | Uso en esta sesión |
| :--- | :--- | :--- |
| Groq `openai/gpt-oss-120b` | 8.000 TPM · 200.000 TPD | TPD agotado: 199.038 usados; 5.103 solicitados al final |
| Groq `openai/gpt-oss-20b` | Límites del free tier de Groq | 36 llamadas en las cinco trazas |
| Gemini `gemini-3.8-flash` | 20 peticiones/día | Agotado; fallback desactivado |
| Tavily | 1.000 llamadas/mes | 34 usadas; 966 restantes |

Las cifras son las que devolvieron las APIs el 2026-10-22. No se presentan como
una garantía de cuota futura. Las 17 búsquedas de la tabla incluyen Tavily,
Wikipedia y arXiv; no todas consumen Tavily.

El 2026-10-23 se verificó que Groq y Gemini volvieron a responder `200` con una
llamada mínima; Tavily seguía con 34 usos de 1.000, porque su límite es mensual.
El run HITL de la Fase 3 se ejecutó con esas cuotas restablecidas.

## Trazas de ejemplo

En [`docs/examples/`](./docs/examples/) hay cinco trazas curadas de la Fase 2 con:

- la pregunta y la configuración efectiva del run;
- el informe final, sus claims, fuentes, confianza y limitaciones;
- el uso agregado de tokens y latencia;
- los eventos del grafo (plan, dispatch, nodos y errores).

Para que el repositorio sea publicable, los snippets de las fuentes se recortaron
a 280 caracteres y se normalizaron las referencias `【src_…】`, `[[src_…]]` y
`[^src_…]` al formato `[src_…]`. Las métricas, URLs, claims y errores no se
alteraron. Consulta el índice en [`docs/examples/README.md`](./docs/examples/README.md).

La Fase 3 añade [`docs/phase3/hitl-resume.json`](./docs/phase3/hitl-resume.json),
una traza del run pausado y reanudado con aprobación humana. Incluye la decisión
de aprobación (`hitl`), el evento `hitl_decision`, la ruta del supervisor y el uso
por nodo. La explicación está en [`docs/phase3/README.md`](./docs/phase3/README.md).

## Cómo ejecutarlo

Requiere Python 3.12, [`uv`](https://docs.astral.sh/uv/) y claves de Groq, Gemini
y Tavily. Las claves se leen de `.env` y nunca se versionan.

```bash
cd research-agents
uv venv --python 3.12
uv pip install -r requirements-dev.txt
cp .env.example .env
# edita .env con tus claves
```

Ejecución con el fallback desactivado y límites conservadores para el free tier:

```bash
RESEARCH_MAX_ROUNDS=1 \
RESEARCH_MAX_TOOL_STEPS=1 \
RESEARCH_MAX_WORKERS=2 \
LLM_MAX_RETRIES=0 \
.venv/bin/python -m scripts.run_research \
  "¿Qué es la inteligencia artificial agéntica y cuáles son sus limitaciones actuales?" \
  --no-fallback
```

Opciones útiles:

```bash
.venv/bin/python -m scripts.run_research "..." --json
.venv/bin/python -m scripts.run_research "..." --no-save
.venv/bin/python -m scripts.run_research "..." --run-id demo-001
.venv/bin/python -m scripts.run_research "..." --language es
```

El CLI imprime el informe en Markdown y escribe una traza JSON en
`artifacts/traces/`, que está ignorado por Git. `--no-save` evita el archivo.
`--no-fallback` es útil cuando el proveedor secundario no tiene cuota.

## HITL y durabilidad

El checkpointer `AsyncSqliteSaver` guarda el estado en
`artifacts/checkpoints.db`. El `thread_id` identifica la ejecución y debe
conservarse para reanudarla. La serialización usa `JsonPlusSerializer` con una
allowlist de los modelos de la aplicación; no se aceptan tipos arbitrarios desde
la base de datos.

Run con aprobación humana:

```bash
RESEARCH_MAX_ROUNDS=1 RESEARCH_MAX_TOOL_STEPS=1 RESEARCH_MAX_WORKERS=1 \
LLM_MAX_RETRIES=0 \
.venv/bin/python -m scripts.run_research \
  "¿Qué es un transformer y para qué se usa en NLP?" \
  --hitl --no-fallback --run-id demo-hitl
```

El proceso se detiene antes del writer e imprime el `thread_id` y el payload de
aprobación. En otro proceso:

```bash
# Aprobar: continúa al writer y genera el informe.
.venv/bin/python -m scripts.run_research \
  --resume --thread-id demo-hitl --approve --no-fallback

# Rechazar: termina con status="failed" y sin informe.
.venv/bin/python -m scripts.run_research \
  --resume --thread-id demo-hitl --reject \
  --feedback "Faltan fuentes primarias." --no-fallback
```

Un rechazo no reinyecta el feedback como una nueva ronda: es una decisión humana
de no publicar el informe. Para reanudar un checkpoint que falló sin una decisión
HITL (por ejemplo, tras matar el proceso), usa el mismo `thread_id` sin
`--approve` ni `--reject`:

```bash
.venv/bin/python -m scripts.run_research --resume --thread-id demo-hitl
```

La aprobación, el rechazo y la reanudación tras un fallo simulado tienen tests
con `AsyncSqliteSaver` y con un checkpointer en memoria. Si el run se pausa, la
traza se guarda como `artifacts/traces/<run_id>.paused.json`; al reanudar se
escribe la traza final como `artifacts/traces/<run_id>.json`.

## Configuración

Todo se controla desde `.env`; los valores completos están en
[`.env.example`](./.env.example). Los principales son:

| Variable | Valor por defecto | Para qué sirve |
| :--- | :--- | :--- |
| `LLM_PROVIDER` / `LLM_MODEL` | `groq` / `openai/gpt-oss-120b` | Proveedor y modelo principal |
| `LLM_FAST_MODEL` | `openai/gpt-oss-20b` | Routing y tareas rápidas |
| `LLM_FALLBACK_PROVIDER` | `gemini` | Fallback opcional; vacío lo desactiva |
| `LLM_TPM_LIMIT` | `8000` | Limitador compartido de tokens/minuto; `0` lo desactiva |
| `LLM_MAX_OUTPUT_TOKENS` | `3000` | Tope de salida por llamada |
| `RESEARCH_MAX_LLM_CALLS` | `30` | Presupuesto duro de llamadas |
| `RESEARCH_MAX_TOKENS` | `60000` | Presupuesto duro de tokens |
| `RESEARCH_MAX_WORKERS` | `2` | Workers concurrentes; no descarta subpreguntas |
| `RESEARCH_MAX_TOOL_STEPS` | `2` | Pasos ReAct por subpregunta |
| `RESEARCH_MAX_ROUNDS` | `2` | Rondas de investigación |
| `RESEARCH_TAVILY_MONTHLY_BUDGET` | `1000` | Contador persistente de Tavily |
| `RESEARCH_DB_PATH` | `artifacts/research.db` | Caché y contador de presupuesto |
| `RESEARCH_CHECKPOINT_PATH` | `artifacts/checkpoints.db` | Checkpoints HITL y reanudación |

`RESEARCH_SEARCH_BACKEND=frozen` permite usar un corpus local; la demo y las
trazas de este README usan `live`.

## Herramientas y guardrails

- **Tavily** es el buscador principal; si falla o no devuelve resultados, se usa
  **DuckDuckGo**. **arXiv** y **Wikipedia** son herramientas independientes.
- `fetch_page` solo acepta HTTP/HTTPS, resuelve el host y rechaza direcciones
  privadas, loopback, link-local, reservadas o con credenciales. Las redirecciones
  se validan de nuevo.
- Las respuestas se cachean en SQLite con TTL. Un *cache hit* no consume el
  presupuesto de Tavily.
- El `TokenRateLimiter` es compartido por el proceso y estima la salida para
  respetar el TPM; el presupuesto del grafo corta llamadas y tokens.
- El researcher ejecuta la herramienta del último paso permitido y después
  finaliza, en lugar de dejar una tool call pendiente.
- Si Groq inventa una tool call al usar salida estructurada, el cliente reintenta
  con un JSON textual validado localmente (`text_json`). Es una defensa contra
  una limitación observada del proveedor, no una segunda interpretación de los
  datos.

## Tests y calidad

```bash
cd research-agents
.venv/bin/ruff check src tests scripts
.venv/bin/pytest -q
```

Estado actual: **103 tests pasan** y `ruff` no reporta errores. Los tests no hacen
llamadas reales a APIs: usan fakes, `respx` y fixtures. Pueden ejecutarse en CI
sin claves. Cubren, entre otros, el tope de rondas, la aprobación y el rechazo
HITL, la reanudación tras un fallo simulado, el checkpointer SQLite asíncrono,
el esquema de traza y la recuperación ante `429` y timeouts.

## Limitaciones

- **No hay evaluación sistemática todavía.** Las cinco preguntas de la Fase 2 y
  el run HITL de la Fase 3 demuestran que el flujo funciona, pero no constituyen
  un benchmark. Falta el corpus congelado, los baselines y la comparación
  multiagente frente a un agente único (Fase 4).
- **La calidad no está garantizada por el validador.** El validador comprueba que
  los IDs citados existan y que los claims tengan fuentes; la comprobación del
  critic es estructural (claim con citas válidas), no entailment semántico. Esa
  comprobación requiere revisión humana o un juez independiente.
- **Free tier.** Durante la Fase 2 Groq agotó su TPD y Gemini su cuota diaria. El
  2026-10-23 ambas volvieron a responder; para reproducir las trazas hay que
  respetar los límites o usar un plan de pago. Tavily queda lejos del límite,
  pero no es ilimitado.
- **Datos vivos.** Las URLs y snippets pueden cambiar. Las trazas son una foto del
  2026-10-22 y del 2026-10-23, no una garantía de disponibilidad futura.
- **Un error recuperado.** La traza de RAG conserva el `JSONDecodeError` del
  analista y su fallback determinista. Se documenta para no ocultar el fallo.
- **HITL solo por CLI.** El rechazo termina el run sin informe y no reinyecta el
  feedback al researcher. La API/UI para aprobar desde fuera del CLI es Fase 5.
- **Alcance pendiente.** API FastAPI/SSE, UI mínima, Docker y la evaluación
  sistemática están en fases posteriores. No se incluye MCP.
- **Solo CLI.** No hay autenticación, multiusuario ni límites por usuario; no es
  un servicio listo para exponer a Internet.

## Estructura

```text
research-agents/
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── docs/
│   ├── spike.md
│   ├── examples/          # 5 trazas reales curadas (Fase 2)
│   └── phase3/            # run HITL real reanudado (Fase 3)
├── scripts/
│   ├── run_research.py
│   └── spike_provider.py
├── src/
│   ├── agents/            # supervisor, planner, researcher, approval, analyst, critic, writer
│   ├── tools/             # Tavily, DDG, arXiv, Wikipedia, fetch, SSRF, router
│   ├── budget.py
│   ├── cache.py
│   ├── checkpoint.py
│   ├── citations.py
│   ├── config.py
│   ├── graph.py
│   ├── llm.py
│   ├── models.py
│   ├── services.py
│   └── tavily_budget.py
└── tests/
```

## Seguridad

- `.env` y `artifacts/` están en `.gitignore`.
- No se publican claves, pesos, datasets ni páginas completas.
- Las trazas de ejemplo no contienen claves ni rutas locales; los snippets se
  recortaron.
- Las búsquedas y descargas pasan por límites de tamaño, timeout y validación SSRF.
- Los checkpoints solo deserializan una allowlist de modelos de la aplicación.
- Este proyecto es una demostración técnica, no un servicio de producción. No debe
  desplegarse públicamente sin autenticación, rate limiting y revisión de seguridad.

## Licencia

MIT, igual que el resto del portafolio.
