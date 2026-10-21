# Hardware, modelos y rendimiento

## Equipo de referencia

| Componente | Valor |
| :--- | :--- |
| CPU | Intel Core i5-7200U @ 2.50 GHz |
| Núcleos / hilos | 2 núcleos físicos / 4 hilos |
| Extensiones | AVX2, FMA, F16C |
| RAM | 7 GB |
| RAM disponible con VS Code y Firefox abiertos | ~2,3 GB |
| Swap | 4 GB |
| GPU | No dedicada |
| Disco libre | ~37 GB |
| Sistema | Ubuntu, Python 3.12 vía `uv` |

Este equipo no permite ejecutar modelos grandes con comodidad. El proyecto está
diseñado para que la recuperación y la evaluación sean viables en CPU y para que
el LLM sea reemplazable.

## Modelos elegidos

| Uso | Modelo | Tamaño aproximado | Papel |
| :--- | :--- | :--- | :--- |
| Embeddings | `intfloat/multilingual-e5-small` | ~470 MB en disco, 384 dimensiones | Recuperación densa bilingüe |
| Reranker | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | ~470 MB | Reordenar los mejores candidatos |
| LLM por defecto | `qwen2.5:1.5b-instruct-q4_K_M` | ~1 GB | Respuesta local rápida |
| LLM de calidad | `qwen2.5:3b-instruct-q4_K_M` | ~2,2 GB | Modo opcional con más latencia |
| Descartado | modelos de 7B | ~4,5 GB+ | No caben con holgura en 7 GB |

Los tamaños son aproximados y dependen de la cuantización y del runtime. La regla
práctica es dejar al menos 1 GB libre para el sistema y el navegador.

## Medidas reales de la ingesta

Mediciones tomadas en este equipo con el PDF
`03_07_02 Datapoint Types v02.02.01 AS.pdf` (251 páginas):

| Modo | Tiempo | Chunks | Tablas | Entidades | RSS máximo |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Con extracción de tablas | 65,0 s | 379 | 266 | 849 | 483 MB |
| Sin extracción de tablas | 2,1 s | 113 | 0 | 0 | 483 MB |

La extracción de tablas es la parte más cara del parsing: multiplica por ~30 el
tiempo en este documento. A cambio, produce el catálogo exacto de DPT/PID y chunks
de tabla recuperables. Para el corpus completo conviene decidir qué volúmenes
necesitan tablas y cuáles pueden indexarse solo con texto.

## Medidas reales de embeddings

`intfloat/multilingual-e5-small` en CPU, con `batch_size=16`:

| Medida | Valor |
| :--- | ---: |
| Carga inicial del modelo (primera vez, con descarga) | 36,2 s |
| Carga con modelo ya en caché | 11,2 s |
| Embedding de 64 chunks | 28,6 s |
| Rendimiento sostenido | ~2,0–2,2 chunks/s |
| Embedding de una consulta | ~0,04 s |
| RSS máximo | ~1,3 GB |

Con los ~2,0 chunks/s medidos en el subconjunto, indexar los ~13.000 chunks
estimados del corpus completo requiere aproximadamente 1,8 horas. Es un coste
único; las consultas solo embedden la pregunta. El índice se puede reutilizar y
la ingesta es incremental por `chunk_id`.

## Ollama: medidas reales

El script `scripts/benchmark_ollama.py` mide latencia, tokens de prompt, tokens de
salida, tokens/s y la memoria que reporta `/api/ps`. Usa una pregunta fija, sin
contexto RAG, y `num_thread=2`. **No es una evaluación de calidad**: mide la
infraestructura y sirve para elegir el modelo que cabe en este equipo.

Resultados en este portátil, con `num_ctx=4096`:

| Modelo | Carga en frío | 150 tokens de salida | Salida | RAM reportada |
| :--- | ---: | ---: | ---: | ---: |
| `qwen2.5:1.5b-instruct-q4_K_M` | 3,58 s | 23,26 s en frío / 16,36 s en caliente | 8,5–9,3 tok/s | 1,17 GB |
| `qwen2.5:3b-instruct-q4_K_M` | 7,87 s | 39,90 s en frío / 28,55 s en caliente | 5,3 tok/s | 2,17 GB |

En caliente, el 3B es aproximadamente **1,75× más lento** que el 1.5B para 150
tokens. La memoria reportada es la del modelo cargado; Ollama puede mantener
varios modelos en memoria hasta que se liberan con `ollama stop`.

Los JSON completos están en `docs/ollama_benchmark.json` (1.5B) y
`docs/ollama_benchmark_3b.json` (3B). El *preview* de respuesta del 1.5B inventó
el significado del acrónimo KNX en una pregunta sin contexto; el 3B dio una
definición más plausible. Es una observación puntual, no una métrica: refuerza la
necesidad de responder solo con contexto recuperado y de validar las citas.

## Recomendación

- Usar **1.5B Q4_K_M** como modo por defecto: es el único que deja margen para la
  API, Qdrant, el reranker y el navegador en 7 GB.
- Usar **3B Q4_K_M** solo cerrando aplicaciones: ocupa ~2,17 GB y deja el sistema
  muy justo. No es el modo de la demo.
- Mantener el reranker activado para consultas: añade latencia, pero mejora la
  precisión de los primeros puestos. Si la RAM aprieta, `RAG_USE_RERANKER=false`.
- Para una demo fluida, responder en *streaming* o mostrar primero las fuentes y
  después la respuesta. La API actual devuelve la respuesta completa.
