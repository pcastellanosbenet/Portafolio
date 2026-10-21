# Coste de indexación del corpus completo

## Corpus

| Métrica | Valor |
| :--- | ---: |
| PDFs | 178 |
| Páginas | 10.908 |
| Tamaño | ~158 MB |
| Volúmenes | 2 a 10 + Application Notes |

El corpus no se incluye en el repositorio. Está en `RAG-Agent/The KNX Standard
v3.0.0/` y se pasa con `KNX_CORPUS_DIR`.

## Mediciones reales

Documento de referencia: `03_07_02 Datapoint Types v02.02.01 AS.pdf`, 251 páginas.

| Operación | Tiempo | Rendimiento |
| :--- | ---: | :--- |
| Parse + tablas + chunks | 65,0 s | ~0,26 s/página |
| Parse sin tablas + chunks | 2,1 s | ~0,008 s/página |
| Embeddings e5-small, 64 chunks | 28,6 s | ~2,2 chunks/s |
| Embedding de una consulta | 0,04 s | — |

Estas son medidas reales de este equipo. No son una proyección del corpus
completo.

### Subconjunto de evaluación

También se indexó un subconjunto de **25 PDFs / 2.111 páginas** (los documentos
referenciados por las 20 preguntas de evaluación):

| Métrica | Valor |
| :--- | ---: |
| Chunks | 2.512 |
| Chunks de tabla | 1.020 |
| Entidades | 1.032 |
| Parseo + chunking | 466 s (~0,22 s/página) |
| Embeddings + Qdrant | 1.247 s (~2,0 chunks/s) |
| Tiempo total | 1.730 s (~28 min 50 s) |
| Artefactos | 25 MB (Qdrant 18 MB) |

La densidad agregada es de **1,19 chunks/página**. Es menor que la del documento
DPT aislado (1,51) porque el subconjunto incluye documentos con mucho texto y
pocas tablas.

## Estimación para los 178 PDFs

Con la densidad agregada del subconjunto (1,19 chunks/página), el corpus completo
tendría aproximadamente **13.000 chunks**. La tabla anterior del DPT (1,51)
sobreestima el total porque ese documento es un caso especialmente denso.

| Escenario | Chunks estimados | Parse estimado | Embeddings estimados | Tiempo total |
| :--- | ---: | ---: | ---: | ---: |
| A. Todo con tablas | ~13.000 | ~40–60 min | ~1,8–2,1 h | ~2,5–3 h |
| B. Todo sin tablas | ~4.900 | ~2–5 min | ~35–40 min | ~45 min |
| C. Texto completo + tablas solo en documentos DPT/PID | ~9.000–11.000 | ~10–15 min | ~1,1–1,4 h | ~1,5 h |

Las cifras de los escenarios A, B y C son **extrapolaciones**, no ejecuciones
completas. La densidad de tablas varía mucho entre volúmenes; el catálogo DPT es
un caso especialmente denso y el subconjunto no es una muestra aleatoria.

## Disco y memoria

Estimaciones para el escenario A:

| Artefacto | Tamaño estimado |
| :--- | ---: |
| Vectores (384 × float32 × 13.000) | ~19 MB |
| Payloads y metadatos en Qdrant | ~40–80 MB |
| `chunks.jsonl` + `entities.jsonl` | ~35–70 MB |
| Modelo e5-small en caché | ~0,5 GB |
| Reranker en caché | ~0,5 GB |
| **Total aproximado** | **~1,1–1,6 GB** |

RAM durante la indexación: ~1,2 GB para el embedder, ~0,5 GB para el parser y
~0,2–0,5 GB para Qdrant local. En un equipo de 7 GB conviene cerrar el navegador
y el editor durante la ingesta completa.

## Estrategias más baratas (propuestas, no implementadas)

1. **Tablas solo donde aportan valor.** Extraer tablas únicamente de documentos
   con DPT, PID, máscaras o catálogos de propiedades (por ejemplo `03_05_01`,
   `03_07_02`, `03_07_03`, perfiles de volumen 6, propiedades de volumen 7 y
   AN193). El resto se indexa como texto. Es la mayor reducción de coste.
2. **Chunks más gruesos.** Subir de ~500 a ~800–1.000 palabras y reducir el
   solapamiento. Menos vectores y menos almacenamiento, a cambio de menor
   precisión en preguntas muy locales.
3. **Embeddings más pequeños o cuantizados.** Una versión ONNX int8 de un modelo
   multilingüe pequeño puede ser 2–4× más rápida en CPU, con cierta pérdida de
   recall. No se ha medido en este equipo.
4. **Cuantización binaria en Qdrant.** Reduce el vector a bits y acelera la
   búsqueda; requiere rescoring con vectores completos para no perder precisión.
5. **Catálogo estructurado para consultas exactas.** DPT, PID y máscaras pueden
   resolverse con SQLite/FTS o un diccionario en memoria sin pasar por embeddings.
   El proyecto ya extrae el catálogo; falta explotarlo como índice primario.
6. **Indexación incremental.** El ingest ya evita reembedder chunks cuyo
   `chunk_id` existe en Qdrant. Si cambia el parser o el chunking, los IDs cambian
   y hay que reconstruir. Una capa de hashing de contenido permitiría reutilizar
   vectores aunque cambie la numeración.
7. **Caché de consultas.** Para una demo, cachear embeddings de preguntas
   frecuentes y respuestas validadas reduce latencia sin tocar el índice.
8. **Indexar solo los volúmenes relevantes para la demo.** Por ejemplo, volumen 3
   (especificaciones), volumen 7 (aplicaciones) y Application Notes. Es una
   decisión de producto, no una optimización técnica.

## Recomendación

Para el portafolio, la opción más defendible es la **C**: texto completo y tablas
solo en los documentos que contienen catálogos estructurados. Mantiene la
cobertura del estándar, conserva el lookup exacto de DPT/PID y reduce el coste a
la mitad o menos. La opción A es la más completa y se puede ejecutar en una sola
tarde; la opción B es la más rápida, pero pierde el catálogo y parte del contexto
técnico.
