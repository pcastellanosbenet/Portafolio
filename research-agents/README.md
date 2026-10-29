# research-agents

Equipo de investigación multiagente construido con **LangGraph** y APIs compatibles
con OpenAI. Recibe una pregunta abierta, la descompone, busca evidencia en la web y
en fuentes académicas, verifica las citas y entrega un informe en Markdown con
trazabilidad de herramientas, tokens y latencia.

> **Estado (2026-10-29):** Fases 0–3 y 5 completadas. La Fase 4 está **casi
> cerrada**: el CLI, el grafo con herramientas reales, el HITL, la reanudación
> con checkpointer SQLite y el marco de evaluación con corpus congelado están
> cubiertos por tests; **B0, B1 y B2 están completos sobre las 20 preguntas**. B1
> necesitó dos sesiones y B2 tres por el TPD de 200.000; B2 conserva un error
> recuperable en M05. **Las 3 repeticiones de robustez siguen pendientes.** La
> demo FastAPI/SSE de la Fase 5 se verificó con una pregunta real: el informe,
> las citas, la traza y el usage existen, pero el run agotó el presupuesto de la
> prueba y usó fallbacks deterministas. Nada de eso se oculta en este README.

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
  reanudación en otro proceso con el mismo `thread_id`, tanto por CLI como por
  API/UI.
- **Producto local:** FastAPI con `POST /v1/research`, estado por run, SSE de
  traza, aprobación HITL, `/health`, UI mínima, CLI `research`/`resume`, Docker
  con volumen SQLite y rate limit básico.
- **Durabilidad:** checkpointer `AsyncSqliteSaver` con serialización JSON+ y una
  allowlist explícita de tipos de la aplicación.
- Trazas reproducibles sin claves ni datos privados. Cinco ejecuciones reales de
  la Fase 2 están en [`docs/examples/`](./docs/examples/) y una ejecución HITL
  reanudada está en [`docs/phase3/`](./docs/phase3/).
- **Evaluación con corpus congelado:** 30 documentos de Wikipedia con licencia,
  URL y SHA-256, 20 preguntas en cuatro categorías y comparación de B0 (agente
  único), B1 (pipeline fijo) y B2 (equipo completo) con juez ciego, métricas de
  citas y abstención, y reanudación por lotes. Metodología y resultados en
  [`docs/evaluation.md`](./docs/evaluation.md).

## Documentación

| Documento | Contenido |
| :--- | :--- |
| [`docs/architecture.md`](./docs/architecture.md) | Flujo del grafo, estado, contratos, herramientas, persistencia y producto |
| [`docs/patterns.md`](./docs/patterns.md) | Patrón → código → trade-off y cuándo no usar el equipo completo |
| [`docs/security.md`](./docs/security.md) | Secretos, prompt injection, SSRF, cuotas, HITL y límites de la demo |
| [`docs/evaluation.md`](./docs/evaluation.md) | Corpus congelado, juez, métricas, resultados y limitaciones |
| [`docs/spike.md`](./docs/spike.md) | Viabilidad de proveedores y límites medidos |
| [`docs/phase5/README.md`](./docs/phase5/README.md) | API, SSE, UI, CLI, Docker y prueba E2E |

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

El supervisor aplica guardas deterministas sobre el estado y elige la siguiente
ruta; en la implementación actual siempre hay una sola ruta válida, así que la
decisión es predecible y no consume una llamada LLM. El planner produce entre 1 y
4 subpreguntas. El researcher es un subgrafo ReAct con `ToolNode`: puede buscar,
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

### Evaluación con corpus congelado (Fase 4)

La Fase 4 sustituye la búsqueda web por un corpus versionado y ejecuta los tres
sistemas con las mismas herramientas y límites. El smoke real usa F01 (factual) y
U01 (sin respuesta) con Groq: `openai/gpt-oss-120b` para las llamadas principales
de B1/B2 y `openai/gpt-oss-20b` para B0, los researchers y el juez. Gemini no
respondió como juez por timeouts, así que el smoke no tiene un juez de proveedor
independiente; se documenta como limitación.

| Sistema | Éxito tarea | Score juez | Cobertura | Precisión citas | Validez citas | Abstención | Llamadas | Tokens | p50 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| B0 · agente único | 1,00 | 2,00 | 1,00 | 0,67 | 1,00 | 1,00 | 2 | 1.786 | 1,8 s |
| B1 · pipeline fijo | 0,50 | 1,50 | 1,00 | 0,40 | 1,00 | 1,00 | 8 | 9.703 | 241,9 s |
| B2 · equipo completo | 1,00 | 2,00 | 1,00 | 0,25 | 1,00 | 1,00 | 10 | 16.128,5 | 363,6 s |

El smoke demuestra que el pipeline es ejecutable y que las métricas se calculan
con datos reales, pero **no es la evaluación completa**: solo hay 2 de 20
preguntas. B1 falló F01 por una claim no soportada; B2 acertó ambas, pero en F01
citó 8 fuentes para 2 esperadas y consumió ~9× los tokens de B0. La revisión manual de las
6 respuestas y la taxonomía de fallos están en
[`docs/evaluation.md`](./docs/evaluation.md). Los registros crudos, el resumen y
el gráfico están en
[`eval/results/smoke-20261023b/`](./eval/results/smoke-20261023b/).

```bash
# Validar el corpus y el plan sin llamar a APIs
.venv/bin/python -m scripts.run_eval --dry-run

# Reproducir el smoke
.venv/bin/python -m scripts.run_eval \
  --systems b0,b1,b2 --question-id F01 --question-id U01 \
  --run-id smoke-20261023b \
  --max-rounds 1 --max-workers 1 --max-tool-steps 1 \
  --max-llm-calls 12 --max-tokens 30000 \
  --judge-provider groq --judge-model openai/gpt-oss-20b
```

Un lote interrumpido se reanuda con el mismo `--run-id` y `--resume`; las claves
`(pregunta, sistema, repetición)` ya completadas se omiten.

### Lote B0 completo (20 preguntas)

El 2026-10-24 se ejecutó B0 sobre las 20 preguntas con el mismo corpus congelado.
B0 usó el modelo rápido `openai/gpt-oss-20b`, que también fue el juez; es un
resultado real, pero **no es la comparación completa B0/B1/B2**:

| Sistema | Éxito tarea | Score juez | Cobertura | Precisión citas | Validez citas | Recall fuentes | Abstención | Llamadas | Tokens | p50 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| B0 · agente único | 0,25 | 1,20 | 0,56 | 0,83 | 1,00 | 0,89 | 1,00 | 2 | 2.143 | 58,5 s |

| Categoría | B0 |
| :--- | :---: |
| Factual | 0,20 |
| Comparación | 0,20 |
| Multi-hop | 0,00 |
| Sin respuesta | 0,60 |

B0 acertó 5 de 20 con la rúbrica estricta. Las cinco preguntas sin respuesta se
abstuvieron, pero U01/U03 citaron fuentes irrelevantes y el juez les dio 1. La
latencia está dominada por el limitador de TPM.

### Lote B1 completo (20 preguntas)

B1 se ejecutó en dos sesiones con el mismo `run_id`: 11 registros el 2026-10-25
(F01–F05, C01–C05, M01) y los 9 restantes el 2026-10-26 (M02–M05 y U01–U05).
El primer corte fue por cuota; el segundo `--resume` omitió los 11 ya
completados. No hubo errores de sistema ni del juez.

| Sistema | Éxito tarea | Score juez | Cobertura | Precisión citas | Validez citas | Recall fuentes | Abstención | Llamadas | Tokens | p50 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| B1 · pipeline fijo (20) | 0,55 | 1,55 | 0,56 | 0,74 | 1,00 | 0,91 | 1,00 | 9,10 | 11.972 | 357,3 s |

| Categoría | B0 | B1 | n |
| :--- | :---: | :---: | :---: |
| Factual | 0,20 | 0,20 | 5 |
| Comparación | 0,20 | 0,40 | 5 |
| Multi-hop | 0,00 | 0,60 | 5 |
| Sin respuesta | 0,60 | 1,00 | 5 |

B1 acierta 11 de 20 (F01, C01, C03, M01, M03, M04 y U01–U05); B0 acierta 5.
La mejora se concentra en multi-hop (3/5 vs 0/5) y en las preguntas sin
respuesta (5/5 vs 3/5). Factual no mejora y comparación sube de 1/5 a 2/5.

B1 gana en éxito de tarea, pero no gratis: usa **5,6× los tokens medios**,
4,6× las llamadas y **6,1× la latencia p50** de B0. La precisión estricta de
citas baja de 0,83 a 0,74; la cobertura determinista queda igual (0,56) y el
recall de fuentes sube de 0,89 a 0,91. La comparación B0/B1/B2 ya está
completa; falta la robustez. Registros y resumen en
[`eval/results/eval-full-20261024/`](./eval/results/eval-full-20261024/).

### Lote B2 completo (20 preguntas)

B2 se ejecutó en tres sesiones con el mismo `run_id`: 7 registros el 2026-10-27
(F01–F05, C01–C02), 7 el 2026-10-28 (C03–C05, M01–M04) y 6 el 2026-10-29
(M05 y U01–U05), más la repetición de C04. El primer juicio de C04 falló con
`StructuredOutputError`; el registro defectuoso se conservó fuera del árbol y se
repitió. El resultado final no tiene errores de juez, pero M05 conserva un
`JSONDecodeError` del researcher: una subpregunta se perdió y el informe quedó
incompleto.

| Sistema | Éxito tarea | Score juez | Cobertura | Precisión citas | Validez citas | Recall fuentes | Abstención | Llamadas | Tokens | p50 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| B2 · equipo completo (20) | 0,45 | 1,45 | 0,60 | 0,75 | 1,00 | 0,83 | 1,00 | 10,95 | 18.587 | 424,8 s |

| Categoría | B0 | B1 | B2 | n |
| :--- | :---: | :---: | :---: | :---: |
| Factual | 0,20 | 0,20 | 0,20 | 5 |
| Comparación | 0,20 | 0,40 | **0,60** | 5 |
| Multi-hop | 0,00 | **0,60** | 0,20 | 5 |
| Sin respuesta | 0,60 | **1,00** | 0,80 | 5 |

B2 acierta 9 de 20: F01, C01, C03, M01, C04, U01, U02, U03 y U05. B0 acierta 5
y B1 acierta 11. B2 es el mejor en comparación (3/5), pero cae en multi-hop
(1/5 frente a 3/5 de B1) y en abstención (4/5 frente a 5/5); factual sigue en
1/5 para los tres.

B2 **no es la mejor opción global**: B1 tiene más éxito (0,55 vs 0,45), mejor
score (1,55 vs 1,45) y usa 1,55× menos tokens (11.972 vs 18.587). B2 tiene una
precisión de citas ligeramente mejor (0,75 vs 0,74), pero peor recall de fuentes
(0,83 vs 0,91). Frente a B0, B2 usa 8,7× los tokens y 7,3× la latencia p50, con
menor precisión de citas (0,75 vs 0,83) y menor recall (0,83 vs 0,89). El
`JSONDecodeError` de M05 es un fallo real del sistema y se reporta, no se oculta.

### Revisión manual de B2 (4 de 20)

Se revisaron F01, C01, M01 y U01; la puntuación humana coincidió con la del juez
en las cuatro (2/2). F01 añade una tabla con generalizaciones no citadas y baja a
0,50 de precisión de citas; C01 está limpio (1,00); M01 mantiene un falso
negativo léxico (0,667) porque la respuesta dice “asigna pesos” en vez de
“realza/disminuye”; U01 se abstiene correctamente pero cita tres fuentes
irrelevantes (precisión y recall 0,00).

La muestra manual acumulada es **12 de 60 registros (20%)**: 4 de B0, 4 de B1 y
4 de B2, con **12/12 de coincidencia juez-humano**. Es una muestra pequeña, no
una auditoría completa.

### Consumo de cuotas observado

| Recurso | Límite observado | Uso observado |
| :--- | :--- | :--- |
| Groq `openai/gpt-oss-120b` | 8.000 TPM · 200.000 TPD | B1: 82.828; B2: 222.292 en 20 registros (tres sesiones) |
| Groq `openai/gpt-oss-20b` | 8.000 TPM · 200.000 TPD | B0: 83.337; B1: 210.213; B2: 201.186 |
| Gemini `gemini-3.8-flash` | 20 peticiones/día | Agotado; fallback desactivado |
| Tavily | 1.000 llamadas/mes | 34 usadas; 966 restantes |

Las cifras de TPM/TPD son las del plan gratuito; el TPD de ambos modelos de Groq
se confirmó en la documentación oficial el 2026-10-25. No se presentan como una
garantía de cuota futura. Las 17 búsquedas de la tabla incluyen Tavily, Wikipedia
y arXiv; no todas consumen Tavily.

El 2026-10-23 se verificó que Groq y Gemini volvieron a responder `200` con una
llamada mínima; Tavily seguía con 34 usos de 1.000, porque su límite es mensual.
El run HITL de la Fase 3 se ejecutó con esas cuotas restablecidas.

El 2026-10-24 el lote B0/20 consumió 42.860 tokens del sistema y 40.477 del juez
Groq. La prueba E2E de la API consumió 19.965 tokens y 4 búsquedas. Gemini siguió
fallando como juez por `OpenAITimeoutError`; por eso B0 usó Groq como juez y se
declara como limitación. B1 se partió en dos sesiones: 11 registros el
2026-10-25 (127.774 de 20b + 49.946 de 120b) y 9 el 2026-10-26 (82.439 de 20b +
32.882 de 120b). B2 se partió en tres: 7 el 27, 7 el 28 y 7 ejecuciones el 29
(incluida la repetición de C04). El runner reanudó sin repetir preguntas. El
total final de B2 es 222.292 de 120b y 201.186 de 20b; el intento fallido de C04
añadió ~11.200/8.100 no incluidos en ese total. La robustez sigue pendiente.

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

Requiere Python 3.12, [`uv`](https://docs.astral.sh/uv/) y una clave de Groq para
ejecutar. Gemini y Tavily son necesarios para el fallback y las trazas en vivo;
la evaluación con corpus congelado no usa Tavily. Las claves se leen de `.env` y
nunca se versionan.

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

## Demo de producto (Fase 5)

La API, la UI y el CLI comparten el mismo grafo y el mismo checkpointer SQLite.

```bash
cd research-agents
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Abre `http://127.0.0.1:8000/` para la UI y
`http://127.0.0.1:8000/docs` para OpenAPI. Endpoints:

| Método | Ruta | Uso |
| :--- | :--- | :--- |
| `GET` | `/health` | Checkpointer, proveedor, modelo y runs activos |
| `POST` | `/v1/research` | Crea un run (`202`) |
| `GET` | `/v1/research/{id}` | Estado, informe, usage, errores y traza |
| `GET` | `/v1/research/{id}/events` | Stream SSE |
| `POST` | `/v1/research/{id}/approve` | Aprobar o rechazar el HITL |

```bash
curl -sS http://127.0.0.1:8000/v1/research \
  -H 'content-type: application/json' \
  -d '{"question":"¿Qué es un transformer y para qué se usa en NLP?","language":"es"}'

# El id devuelto se usa para el estado y el stream:
curl -sS http://127.0.0.1:8000/v1/research/<run_id>
curl -N  http://127.0.0.1:8000/v1/research/<run_id>/events
```

CLI equivalente:

```bash
./bin/research research "¿Qué es un transformer?" --hitl --no-fallback
./bin/research resume --thread-id <thread_id> --approve --no-fallback
```

Docker:

```bash
cp .env.example .env   # edita las claves; no se versiona
docker compose up --build
```

El compose usa un volumen nombrado `research-data` para que el usuario no root
del contenedor pueda escribir `research.db` y `checkpoints.db` sin depender del
UID del host.

La prueba E2E real del 2026-10-24 (`api-live-20261024`) terminó en `completed`
con 4 claims, 19 fuentes, 19.965 tokens, 4 búsquedas y 23 eventos de traza. Usó
el límite ajustado de la prueba y agotó el presupuesto en critic/writer; por eso
el informe tiene confianza `low` y fallbacks deterministas. La API y el SSE
funcionaron; el resultado **no** representa la calidad sin esos límites. Detalles
en [`docs/phase5/README.md`](./docs/phase5/README.md) y traza en
[`docs/phase5/api-live-20261024.json`](./docs/phase5/api-live-20261024.json).

La demo es local: no tiene autenticación y el registro de runs vive en memoria.
No la expongas a Internet. Tras reiniciar la API, el checkpointer conserva el
estado para reanudar por CLI, pero `GET` no lista runs antiguos.

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

La API expone el mismo HITL: crea el run con `"hitl": true`, espera a
`status="awaiting_approval"` y llama a
`POST /v1/research/{id}/approve` con `{"approved": true|false, "feedback": "..."}`.
El stream SSE permanece abierto durante la pausa y recibe los eventos del writer
cuando se reanuda. La UI muestra los botones de aprobación y rechazo.

## Configuración

Todo se controla desde `.env`; los valores completos están en
[`.env.example`](./.env.example). Los principales son:

| Variable | Valor por defecto | Para qué sirve |
| :--- | :--- | :--- |
| `LLM_PROVIDER` / `LLM_MODEL` | `groq` / `openai/gpt-oss-120b` | Proveedor y modelo principal |
| `LLM_FAST_MODEL` | `openai/gpt-oss-20b` | Routing y tareas rápidas |
| `LLM_FALLBACK_PROVIDER` | vacío | Fallback opcional; vacío lo desactiva |
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
| `RESEARCH_FROZEN_CORPUS_PATH` | `eval/frozen/corpus.json` | Corpus de la evaluación congelada |
| `RESEARCH_JUDGE_PROVIDER` | vacío | Proveedor del juez; vacío usa el principal |
| `RESEARCH_JUDGE_MODEL` | vacío | Modelo del juez; vacío usa el modelo rápido |
| `RESEARCH_JUDGE_MAX_OUTPUT_TOKENS` | `1200` | Tope de salida del juez |
| `RESEARCH_JUDGE_MAX_RETRIES` | `1` | Reintentos del juez ante errores del proveedor |

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

Estado actual: **151 tests pasan** y `ruff` no reporta errores. Los tests no hacen
llamadas reales a APIs: usan fakes, `respx` y fixtures. Pueden ejecutarse en CI
sin claves. Cubren, entre otros, el tope de rondas, la aprobación y el rechazo
HITL, la reanudación tras un fallo simulado, el checkpointer SQLite asíncrono,
el esquema de traza, la recuperación ante `429` y timeouts, la integridad del
corpus congelado, la búsqueda y el fetch offline, las métricas, el parser del
juez, los runners B0/B1/B2 y la API con un grafo falso y un grafo LangGraph real
en memoria.

## Limitaciones

- **La comparación de 20 preguntas está completa; falta la robustez.** El corpus
  congelado, los baselines, el juez y el runner están implementados. El smoke de
  6 ejecuciones es real y B0, B1 y B2 están medidos sobre las 20 preguntas. No
  hay todavía 3 repeticiones de robustez sobre el subconjunto acordado.
- **La calidad no está garantizada por el validador.** El validador comprueba que
  los IDs citados existan y que los claims tengan fuentes; la comprobación del
  critic es estructural (claim con citas válidas), no entailment semántico. Esa
  comprobación requiere revisión humana o un juez independiente.
- **El juez no fue independiente.** Gemini devolvió timeouts y se usó Groq
  `openai/gpt-oss-20b` tanto en el smoke como en B0, B1 y B2. La infraestructura
  permite un proveedor distinto, pero estos resultados no lo consiguieron.
- **Ningún sistema es uniformemente mejor.** B1 gana en éxito global y
  abstención; B2 gana en comparación; B0 es el más barato y el más preciso en
  citas. La comparación honesta debe incluir coste y calidad de citas, no solo
  el score.
- **B2 tiene un error de sistema.** M05 perdió una subpregunta por un
  `JSONDecodeError` del researcher y el informe quedó incompleto (score 1). Es
  el único registro B2 con error; se conserva y se documenta.
- **Cobertura léxica y citas estrictas.** La cobertura factual se basa en
  variantes escritas a mano y la precisión de citas penaliza fuentes adicionales
  válidas. Se reportan validez y recall por separado; ninguna métrica mide
  entailment.
- **Free tier.** Durante la Fase 2 Groq agotó su TPD y Gemini su cuota diaria. El
  2026-10-23 ambas volvieron a responder; para reproducir las trazas y el smoke
  hay que respetar los límites o usar un plan de pago. Tavily queda lejos del
  límite, pero no es ilimitado. El smoke consumió 55.235 tokens de sistema y
  13.250 del juez.
- **Datos vivos en las trazas.** Las URLs y snippets de la Fase 2 y 3 pueden
  cambiar. La evaluación de Fase 4 no depende de la web: usa el corpus congelado
  del 2026-10-23.
- **Un error recuperado.** La traza de RAG conserva el `JSONDecodeError` del
  analista y su fallback determinista. Se documenta para no ocultar el fallo.
- **El feedback del rechazo no se reinyecta.** La API/UI permiten aprobar o
  rechazar, pero un rechazo termina el run sin informe y sin una nueva ronda.
- **La API es una demo local.** El registro de runs vive en memoria y no se
  reconstruye tras reiniciar; el checkpointer sí conserva el estado para reanudar
  por CLI. No hay autenticación, multiusuario, cuotas por usuario ni persistencia
  del historial. Usa un solo worker.
- **La prueba E2E expuso el límite de presupuesto.** El run real agotó las 10
  llamadas, el critic y el writer usaron fallback y el informe salió con confianza
  `low`. Es un resultado honesto del límite de la prueba, no la calidad esperada
  con más cuota.
- **Alcance pendiente.** Las 3 repeticiones de robustez. La revisión manual del
  20% está hecha (12/60, 12/12 de coincidencia juez-humano). La integración en CI
  ya está añadida y los tests no necesitan claves. No se incluye MCP.

## Cuándo no usar el equipo completo

B2 no es la respuesta por defecto. La comparación B0/B1/B2 y el propio diseño
sugieren reservarlo para preguntas que realmente necesitan descomposición,
evidencia múltiple y crítica:

- **Preguntas simples o autocontenidas:** B0 puede responder con una o dos
  llamadas y mucho menos coste.
- **Presupuesto ajustado o free tier:** el fan-out y las rondas consumen cuota
  rápido; un pipeline fijo es más predecible.
- **Latencia crítica:** B2 encadena planner, researchers, analyst, critic y
  writer, además de las esperas del rate limiter.
- **Verificación factual estricta:** el critic solo comprueba estructura de
  citas, no entailment. Si el coste de un error es alto, hace falta revisión
  humana o un verificador específico.
- **Reproducibilidad estricta:** los modelos generativos añaden variabilidad
  incluso con temperatura 0; el corpus congelado reduce el problema, no lo elimina.

La lectura honesta es usar B0/B1 cuando basten y reservar B2 para preguntas que
se beneficien de coordinación. Los detalles están en
[`docs/patterns.md`](./docs/patterns.md).

## Estructura

```text
research-agents/
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── bin/research            # launcher de la CLI research/resume
├── app/
│   ├── main.py             # app FastAPI, rutas y SSE
│   ├── manager.py          # registro de runs y fan-out de eventos
│   ├── schemas.py          # request/response
│   ├── rate_limit.py
│   └── static/             # UI mínima
├── docs/
│   ├── architecture.md    # flujo, estado, contratos y persistencia
│   ├── patterns.md        # patrón → código → trade-off
│   ├── security.md        # amenazas, defensas y límites
│   ├── spike.md
│   ├── evaluation.md      # metodología, resultados y limitaciones
│   ├── examples/          # 5 trazas reales curadas (Fase 2)
│   ├── phase3/            # run HITL real reanudado (Fase 3)
│   └── phase5/            # API/UI/Docker y E2E real (Fase 5)
├── eval/
│   ├── frozen/corpus.json # 30 documentos con licencia y SHA-256
│   ├── questions.json     # 20 preguntas en cuatro categorías
│   └── results/           # smoke, lote B0/B1/B2 y resúmenes
├── scripts/
│   ├── run_research.py
│   ├── research.py        # subcomandos research/resume
│   ├── run_eval.py        # runner de evaluación B0/B1/B2
│   └── spike_provider.py
├── src/
│   ├── agents/            # supervisor, planner, researcher, approval, analyst, critic, writer
│   ├── eval/              # corpus, métricas, juez, runners, resumen
│   ├── tools/             # Tavily, DDG, arXiv, Wikipedia, fetch, SSRF, router, frozen
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

El análisis completo de amenazas, defensas y riesgos residuales está en
[`docs/security.md`](./docs/security.md). En resumen:

- `.env` y `artifacts/` están en `.gitignore`.
- No se publican claves, pesos ni datasets privados. El corpus de evaluación sí
  se versiona: son extractos de Wikipedia con atribución y licencia CC BY-SA 4.0.
- Las trazas de ejemplo no contienen claves ni rutas locales; los snippets se
  recortaron.
- Las búsquedas y descargas pasan por límites de tamaño, timeout y validación SSRF.
- Los checkpoints solo deserializan una allowlist de modelos de la aplicación.
- La API no devuelve claves: `/health` solo indica si están configuradas y los
  errores públicos se redactan. CORS está limitado a orígenes locales y hay un
  rate limit en memoria de 30 peticiones/minuto por IP.
- La API no tiene autenticación y el registro de runs no persiste: es una demo
  local, no un servicio de producción. No debe desplegarse públicamente sin
  autenticación, rate limiting distribuido y revisión de seguridad.

## Licencia

MIT, igual que el resto del portafolio.
