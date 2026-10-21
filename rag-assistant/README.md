# KNX RAG Assistant

Asistente local de recuperación aumentada (RAG) sobre el estándar **KNX v3.0.0**.
Responde preguntas técnicas en español o inglés usando únicamente los PDFs del
corpus, cita documento, sección y página, y se abstiene cuando la evidencia no
alcanza.

El proyecto está pensado para demostrar ingeniería RAG completa: ingesta de PDFs
reales, chunking con metadatos, búsqueda híbrida, lookup exacto de identificadores
KNX, evaluación de recuperación, API FastAPI y despliegue con Docker. El proyecto se ejecutó en
**local**: ni el corpus ni las preguntas se envían a APIs externas.

## Qué hace

- **Recuperación híbrida:** BM25 + embeddings densos, fusionados con Reciprocal
  Rank Fusion.
- **Lookup exacto:** DPT y PID se resuelven contra un catálogo extraído de las
  tablas. AN, máscaras y números de documento se detectan en la consulta y se
  usan para expandir la búsqueda y aplicar filtros.
- **Citas verificables:** cada respuesta con evidencia incluye `doc_id`, sección,
  páginas y un fragmento de la fuente.
- **Abstención:** si no hay contexto suficiente o las citas no son válidas, el
  agente no inventa una respuesta.
- **State machine determinista:** router, recuperación, un solo reintento y
  validación de citas. Sin LangGraph ni multiagentes.
- **LLM local:** Ollama con Qwen2.5 1.5B Q4_K_M por defecto; 3B como modo de
  calidad opcional.
- **API y UI local:** `/v1/query`, catálogo de documentos y una interfaz web
  mínima en `/`.

## Corpus y reproducibilidad

El corpus es el estándar **KNX v3.0.0**: 178 PDFs, 10.908 páginas y ~158 MB.
Incluye los volúmenes 2–10, especificaciones de sistema, perfiles, descripciones
de aplicación, requisitos de hardware, manual de certificación y Application
Notes.

El estándar está protegido por derechos de autor y **no se redistribuye**. Los
PDFs están fuera de este repositorio. El repositorio solo contiene código, tests,
preguntas, resultados agregados, metadatos y un corpus sintético de demo; no
incluye chunks, embeddings ni el índice de Qdrant del corpus KNX.

La reproducibilidad es **condicionada**:

| Nivel | Qué se puede reproducir | Requisito |
| :--- | :--- | :--- |
| Código y tests | `pytest`, `ruff` y el pipeline completo | Python 3.12 |
| Demo | Ingesta, recuperación, API y evaluación sobre un corpus sintético | El repositorio y modelos públicos |
| Pipeline propio | Ingesta de otros PDFs y consultas con citas | PDFs de entrada |
| Métricas KNX | Las cifras de este README y de `eval/results/` | Copia licenciada de la edición exacta |

La guía completa está en [`docs/corpus.md`](docs/corpus.md), junto con el
manifiesto de metadatos [`docs/corpus_manifest.json`](docs/corpus_manifest.json).
Para comprobar una copia local antes de indexarla:

```bash
python -m scripts.check_corpus --corpus "$KNX_CORPUS_DIR"
```

El validador comprueba los 25 PDFs del subconjunto evaluado, sus páginas y su
SHA-256. No sube ni copia los documentos. Si no tienes una copia licenciada,
puedes ejecutar la demo sintética que se describe más abajo; sus métricas no son
métricas KNX y no deben compararse con las de este README.

## Resultados

### Ingesta real (subconjunto de evaluación)

Durante la evaluación, por las características de mi equipo personal, se indexaron
solo los **25 PDFs referenciados por las 20 preguntas** (2.111 páginas). No es el
corpus completo de 178 PDFs.

| Métrica | Valor |
| :--- | ---: |
| PDFs | 25 |
| Páginas | 2.111 |
| Chunks | 2.512 |
| Chunks de tabla | 1.020 |
| Entidades extraídas | 1.032 |
| Parseo + chunking | 7 min 46 s |
| Embeddings + Qdrant | 20 min 47 s |
| Tiempo total | 28 min 50 s |
| Artefactos | 25 MB (Qdrant 18 MB) |
| RSS del parser | 483 MB |
| RSS durante embeddings | ~1,2 GB |

La densidad observada fue de **1,19 chunks/página** y **2,0 chunks/s** en la fase
de embeddings.   

### Evaluación de recuperación

Las métricas son document-level sobre las 20 preguntas, con `top_k=10`. Un
acierto significa que el documento relevante aparece en el top-10, no que la
respuesta sea correcta.

| Configuración | Recall@10 | Hit@10 | MRR | nDCG@10 |
| :--- | ---: | ---: | ---: | ---: |
| Híbrido BM25 + denso, sin reranker | 0,8917 | 0,95 | 0,7417 | 0,7553 |
| Híbrido + reranker | **0,9083** | **0,95** | **0,8500** | **0,8427** |

El reranker mejora sobre todo el orden de los resultados: MRR pasa de 0,742 a
0,850 y nDCG@10 de 0,755 a 0,843. La mejora es menor en recall porque el
subconjunto solo contiene 25 documentos y el top-10 ya cubre el 40% del corpus.

Por idioma, con reranker:

| Idioma | Preguntas | Recall@10 | MRR | nDCG@10 |
| :--- | ---: | ---: | ---: | ---: |
| Inglés | 15 | 0,9688 | 0,9062 | 0,9074 |
| Español | 5 | 0,6667 | 0,6250 | 0,5837 |

El rendimiento en español es claramente inferior. La pregunta
`¿Qué es una dirección de grupo en KNX?` no recupera ni el glosario ni el
documento de interworking en el top-10, y las preguntas de comparación y de
coupler pierden documentos relevantes. Es una limitación real del conjunto y del
modelo de embeddings, no un fallo de formato.

Los resultados completos, con el top-10 de cada pregunta, están en
[`eval/results/retrieval-no-reranker.json`](eval/results/retrieval-no-reranker.json)
y [`eval/results/retrieval.json`](eval/results/retrieval.json).

### Prueba de la API y del LLM

La API se validó con el índice real y Ollama en CPU:

- `/health`: 2.512 chunks, e5-small, reranker y Qwen2.5 1.5B disponibles.
- `/v1/query` con `How does KNX IP Secure protect tunnelling connections?` y
  `top_k=3`: respondió con `used_llm=true`, una cita y ~64 s de latencia.
- `/v1/query` con `What is DPT 1.001 and how is it encoded?` y `top_k=5`: el
  lookup exacto encontró 28 coincidencias, pero el 1.5B se abstuvo. Es el
  comportamiento correcto ante un modelo pequeño que no puede verificar la
  respuesta, aunque no sea el resultado ideal para una demo.
- `/v1/documents` y `/v1/documents/{doc_id}` devolvieron el catálogo y los
  metadatos esperados; `/` sirve la UI local.

La latencia incluye reranker, recuperación y generación. En la prueba se arrancó
la API con `OLLAMA_NUM_PREDICT=128`; el valor por defecto es 300. No es una cifra
de producción: el equipo no tiene GPU y el modelo corre en dos hilos.

## Arquitectura

```text
PDFs KNX
   │
   ├─ manifest.py ──► inventario + SHA-256 + páginas
   ├─ parse.py ─────► secciones, cabeceras y tablas (PyMuPDF)
   ├─ chunk.py ─────► chunks con sección, páginas, tipo y entidades
   ├─ entities.py ──► catálogo DPT/PID + extracción de AN/máscaras
   ├─ embeddings.py ► multilingual-e5-small (384 dimensiones)
   └─ index.py ─────► Qdrant (local o servidor)
                              │
Pregunta ──► agente ──► BM25 + búsqueda densa ──► RRF ──► reranker opcional
                              │
                              ├─ lookup exacto de identificadores
                              ├─ expansión de contexto
                              ├─ Ollama (Qwen2.5)
                              └─ validador de citas ──► respuesta + fuentes
```

## Cómo ejecutar

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/) y, para generar
respuestas, [Ollama](https://ollama.com/).

```bash
cd rag-assistant
uv venv --python 3.12
uv pip install --python .venv/bin/python \
  --index-strategy unsafe-best-match \
  -r requirements-dev.txt
```

### Demo sin corpus KNX

El repositorio incluye un corpus sintético de 6 documentos para probar el flujo
completo sin una licencia del estándar. Es un protocolo ficticio, no KNX:

```bash
python scripts/build_demo_corpus.py --clean

python -m src.ingest \
  --corpus demo/corpus \
  --artifacts artifacts-demo \
  --rebuild

python -m src.evaluate \
  --questions demo/questions.jsonl \
  --artifacts artifacts-demo \
  --top-k 10 \
  --no-reranker \
  --output demo/results/retrieval.json
```

Los artefactos y el índice se guardan en `artifacts-demo/`, separados del índice
real. Para servir la API con la demo:

```bash
RAG_ARTIFACTS_DIR=artifacts-demo uvicorn app.main:app --host 127.0.0.1 --port 8000
```

La demo usa `multilingual-e5-small` (modelo público) y no necesita Ollama para la
ingesta ni para la evaluación. Sus resultados son un smoke test, no una
evaluación de KNX. Los detalles están en [`demo/README.md`](demo/README.md).

### 1. Arrancar Ollama y descargar el modelo

```bash
ollama serve
ollama pull qwen2.5:1.5b-instruct-q4_K_M
```

El proyecto usa `http://127.0.0.1:11434` por defecto. Si Ollama no está
disponible, la API sigue funcionando y devuelve un extracto citado del mejor
chunk con `used_llm=false`.

### 2. Indexar el corpus

El corpus no se versiona. Ajusta la ruta si es distinta y valida la copia:

```bash
export KNX_CORPUS_DIR="../RAG-Agent/The KNX Standard v3.0.0"
python -m scripts.check_corpus --corpus "$KNX_CORPUS_DIR"

# Prueba rápida con un documento
python -m src.ingest --corpus "$KNX_CORPUS_DIR" --doc "03_07_02 Datapoint Types" --rebuild

# Corpus completo (puede tardar horas en CPU; ver docs/indexing-cost.md)
python -m src.ingest --corpus "$KNX_CORPUS_DIR" --rebuild
```

El comando `--artifacts` cambia también la ruta por defecto de Qdrant:
`--artifacts artifacts-demo` usa `artifacts-demo/qdrant`, no el índice real.

Opciones útiles:

- `--no-tables`: no extrae tablas; mucho más rápido, pero pierde el catálogo
  DPT/PID y parte del contenido técnico.
- `--doc "..."`: indexa solo los PDFs cuya ruta contiene el texto. Se puede
  repetir.
- `--parse-only`: genera `manifest.jsonl`, `chunks.jsonl` y `entities.jsonl` sin
  embeddings ni Qdrant.
- `--embedding-backend hashing`: backend determinista para tests; no es útil
  para recuperación real.


### 3. Arrancar la API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Abre `http://127.0.0.1:8000/` para la UI o prueba:

```bash
curl -s http://127.0.0.1:8000/health | python -m json.tool

curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is DPT 1.001 and how is it encoded?","top_k":5}' \
  | python -m json.tool
```

Endpoints:

| Método | Ruta | Descripción |
| :--- | :--- | :--- |
| GET | `/health` | Estado del índice, modelos y Ollama |
| POST | `/v1/query` | Pregunta con `top_k` y filtros opcionales |
| GET | `/v1/documents` | Catálogo paginado de documentos |
| GET | `/v1/documents/{doc_id}` | Metadatos de un documento |
| POST | `/v1/admin/reload` | Recarga el índice; requiere `X-Admin-Key` si hay clave |

Filtros de `/v1/query`: `volume_number`, `doc_id`, `doc_number`, `content_type`
y `entity`.

### 4. Evaluar la recuperación

```bash
python -m src.evaluate \
  --questions eval/questions.jsonl \
  --top-k 10 \
  --output eval/results/retrieval.json
```

Para comparar sin reranker:

```bash
python -m src.evaluate \
  --questions eval/questions.jsonl \
  --top-k 10 \
  --no-reranker \
  --output eval/results/retrieval-no-reranker.json
```

El conjunto actual tiene 20 preguntas bilingües. Es una semilla, no una
evaluación exhaustiva; el esquema y las métricas se explican en
[`eval/README.md`](eval/README.md).

### 5. Tests y lint

```bash
pytest -q
ruff check src tests scripts app
```

Los tests no descargan modelos ni usan el corpus KNX: usan fixtures deterministas,
el corpus sintético de demo y Qdrant en memoria.

## Docker

El `docker-compose.yml` levanta Qdrant y la API. La ingesta se ejecuta una vez
dentro del contenedor, con el corpus montado en `/data/knx`:

```bash
docker compose up -d qdrant

docker compose run --rm --build api python -m src.ingest \
  --corpus /data/knx \
  --rebuild

docker compose up api
```

La API queda en `http://127.0.0.1:8000`. El corpus se monta en solo lectura; los
artefactos y la caché de Hugging Face usan volúmenes de Docker. Si quieres
inspeccionar los artefactos generados dentro de Docker:

```bash
docker compose cp api:/app/artifacts ./artifacts
```

Para usar Ollama nativo, arráncalo escuchando en todas las interfaces para que
el contenedor pueda alcanzarlo:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

Alternativamente, el servicio `ollama` está detrás del perfil `ollama`:

```bash
OLLAMA_BASE_URL=http://ollama:11434 docker compose --profile ollama up --build
```

## Estructura

```text
rag-assistant/
├── app/
│   ├── main.py              # FastAPI y carga de recursos
│   ├── schemas.py           # request/response de la API
│   └── static/index.html    # UI local
├── demo/
│   ├── README.md            # alcance y límites de la demo
│   ├── documents.json       # corpus sintético (NexaBus, no KNX)
│   ├── questions.jsonl      # 12 preguntas de demo
│   └── results/             # métricas de demo, separadas de KNX
├── docs/
│   ├── architecture.md
│   ├── corpus.md            # licencia y niveles de reproducibilidad
│   ├── corpus_manifest.json # metadatos de los 25 PDFs evaluados
│   ├── hardware.md
│   ├── indexing-cost.md
│   ├── ollama_benchmark.json
│   └── ollama_benchmark_3b.json
├── eval/
│   ├── questions.jsonl      # 20 preguntas bilingües
│   ├── README.md
│   └── results/             # resultados reales de evaluación
├── scripts/
│   ├── build_demo_corpus.py
│   ├── check_corpus.py
│   ├── inspect_corpus.py
│   └── benchmark_ollama.py
├── src/
│   ├── config.py            # settings y rutas
│   ├── models.py            # dataclasses del dominio
│   ├── manifest.py          # inventario de PDFs
│   ├── parse.py             # secciones y tablas
│   ├── chunk.py             # chunking con metadatos
│   ├── entities.py          # DPT/PID/AN y query plan
│   ├── bm25.py              # índice léxico
│   ├── embeddings.py        # e5-small
│   ├── index.py             # Qdrant
│   ├── retrieve.py          # híbrido + RRF + contexto
│   ├── rerank.py            # cross-encoder
│   ├── llm.py               # cliente Ollama
│   ├── citations.py         # formato y validación de citas
│   ├── answer.py            # prompt, reintento y fallback
│   ├── agent.py             # state machine
│   ├── evaluate.py          # métricas de recuperación
│   └── ingest.py            # CLI de ingesta
├── tests/                   # 36 tests
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── requirements-dev.txt
```

## Limitaciones

- **Calidad del LLM:** Qwen2.5 1.5B es un modelo pequeño. En una prueba sin
  contexto inventó el significado del acrónimo KNX; por eso el agente exige
  contexto y valida citas. No se reportan métricas de corrección factual.
- **Evaluación de recuperación, no de respuesta:** las métricas actuales miden si
  los documentos correctos aparecen en el top-k. No miden si la respuesta es
  correcta ni si todas las afirmaciones están citadas.
- **Conjunto de preguntas pequeño:** 20 preguntas no bastan para afirmar
  robustez. Habría que ampliarlo a 50–80, incluir negativas y preguntas
  multdocumento.
- **Parsing heurístico:** la detección de secciones depende de tamaños de fuente,
  negritas y patrones. Algunos PDFs con maquetación irregular pueden quedar con
  secciones imprecisas.
- **Tablas:** PyMuPDF puede perder estructura en tablas complejas. Se filtran
  tablas pequeñas o sin estructura, lo que también puede descartar contenido útil.
- **Chunks empaquetados:** para evitar cientos de fragmentos diminutos, se agrupan
  secciones consecutivas. La cita muestra la primera ruta de sección y el rango de
  páginas; el texto del chunk conserva las rutas de todas las secciones incluidas.
- **Coste en CPU:** la indexación completa con tablas puede tardar horas; el
  análisis está en [`docs/indexing-cost.md`](docs/indexing-cost.md).
- **Sin streaming:** la API devuelve la respuesta completa; para una demo más
  fluida habría que añadir streaming de Ollama.
- **Corpus local:** no se incluye el estándar. Las métricas KNX requieren una
  copia licenciada y validada; el proyecto no es una redistribución del corpus ni
  un sustituto de la documentación oficial. La demo sintética permite probar el
  pipeline, pero no reproduce el rendimiento sobre KNX.

## Referencias

- KNX Association. *The KNX Standard v3.0.0* (corpus local, no redistribuido).
- Wang, L., et al. (2022). *Multilingual E5 Text Embeddings: A Technical Report*.
- Cormack, G. V., Clarke, C. L. A., & Büttcher, S. (2009). *Reciprocal Rank
  Fusion outperforms Condorcet and individual rank learning methods*.
- Qdrant. *Vector database documentation*.
- Ollama. *Local LLM runtime*.
