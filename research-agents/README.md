# research-agents

Equipo de investigación multiagente construido con **LangGraph** y APIs compatibles
con OpenAI. Recibe una pregunta abierta, la descompone, busca evidencia en la web y
en fuentes académicas, verifica las citas y entrega un informe en Markdown con
trazabilidad de herramientas, tokens y latencia.

> **Estado:** Fase 2 de 6 completada (2026-10-22). El CLI y el grafo con
> herramientas reales funcionan y están cubiertos por tests. La API FastAPI/SSE, la
> UI y Docker corresponden a la Fase 5 y todavía no están implementados.

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
  referencias del informe se normalizan antes de validarse.
- Trazas reproducibles sin claves ni datos privados. Cinco ejecuciones reales
  están en [`docs/examples/`](./docs/examples/).

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
   └──► writer ──────────────► informe + citas + traza ───┘
```

El supervisor decide la siguiente ruta. El planner produce entre 1 y 4
subpreguntas. El researcher es un subgrafo ReAct con `ToolNode`: puede buscar,
leer una página y finalizar con un JSON estructurado. El analyst consolida la
evidencia; el critic comprueba cobertura y citas; el writer redacta sin introducir
hechos nuevos.

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

## Trazas de ejemplo

En [`docs/examples/`](./docs/examples/) hay cinco trazas curadas con:

- la pregunta y la configuración efectiva del run;
- el informe final, sus claims, fuentes, confianza y limitaciones;
- el uso agregado de tokens y latencia;
- los eventos del grafo (plan, dispatch, nodos y errores).

Para que el repositorio sea publicable, los snippets de las fuentes se recortaron
a 280 caracteres y se normalizaron las referencias `【src_…】`, `[[src_…]]` y
`[^src_…]` al formato `[src_…]`. Las métricas, URLs, claims y errores no se
alteraron. Consulta el índice en [`docs/examples/README.md`](./docs/examples/README.md).

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

Estado actual: **93 tests pasan** y `ruff` no reporta errores. Los tests no hacen
llamadas reales a APIs: usan fakes, `respx` y fixtures. Pueden ejecutarse en CI
sin claves.

## Limitaciones

- **No hay evaluación sistemática todavía.** Las cinco preguntas demuestran que
  el flujo funciona, pero no constituyen un benchmark. Falta el corpus congelado,
  los baselines y la comparación multiagente frente a un agente único (Fase 4).
- **La calidad no está garantizada por el validador.** El validador comprueba que
  los IDs citados existan y que los claims tengan fuentes; no demuestra que cada
  fuente respalde semánticamente la afirmación. Esa comprobación requiere revisión
  humana o un juez independiente.
- **Free tier.** Groq agotó su TPD y Gemini su cuota diaria durante la sesión. Para
  reproducir las cinco preguntas hay que esperar el reinicio de cuota o usar un
  plan de pago. Tavily queda lejos del límite, pero no es ilimitado.
- **Datos vivos.** Las URLs y snippets pueden cambiar. Las trazas son una foto del
  2026-10-22, no una garantía de disponibilidad futura.
- **Un error recuperado.** La traza de RAG conserva el `JSONDecodeError` del
  analista y su fallback determinista. Se documenta para no ocultar el fallo.
- **Alcance pendiente.** API FastAPI/SSE, UI mínima, Docker, HITL y *durabilidad*
  con checkpointer están en fases posteriores. No se incluye MCP.
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
│   └── examples/          # 5 trazas reales curadas
├── scripts/
│   ├── run_research.py
│   └── spike_provider.py
├── src/
│   ├── agents/            # supervisor, planner, researcher, analyst, critic, writer
│   ├── tools/             # Tavily, DDG, arXiv, Wikipedia, fetch, SSRF, router
│   ├── budget.py
│   ├── cache.py
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
- Este proyecto es una demostración técnica, no un servicio de producción. No debe
  desplegarse públicamente sin autenticación, rate limiting y revisión de seguridad.

## Licencia

MIT, igual que el resto del portafolio.
