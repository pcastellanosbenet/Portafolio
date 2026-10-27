# Evaluación del router y del coste de contexto

> **Fechas:** A/B/C el 2026-10-26; robustez y ablaciones el 2026-10-27.
> **Modelo:** `openai/gpt-oss-120b` vía Groq, temperatura 0.
> **Corpus:** 60 tareas congeladas, SHA-256
> `f08f4ba65c96bc102238b961c25df4c42b5574f37ab75a356607ed2b783eda67`.
> **Resultados crudos A/B/C:** `eval/results/2026-10-26-{static,meta,hybrid}-groq.jsonl`.
> **Robustez:** `eval/results/2026-10-27-hybrid-robustness20-rep{1,2,3}.jsonl`.
> **Ablaciones:** `eval/results/2026-10-27-hybrid-k{5,8,12}-20.jsonl`.
>
> Todas las cifras de esta página salen de esos JSONL. No hay juez LLM ni métricas
> estimadas.

## Metodología

- 20 tareas de documentación, 15 de investigación, 15 de operaciones y 10 negativas.
- Cada tarea positiva tiene `gold` (servidor, herramienta y argumentos mínimos) y un
  predicado determinista sobre la salida.
- La corrección comprueba selección, validez de argumentos contra el esquema JSON y
  éxito del predicado. La validez de argumentos **no** exige igualdad con el `gold`.
- Las tareas negativas se puntúan como abstención correcta si no se invoca ninguna
  herramienta de upstream.
- El mismo prompt, modelo, temperatura y fixtures se usan en las tres configuraciones.
- `tool_tokens` se mide con `tiktoken` `o200k_base` sobre las definiciones serializadas.
  `prompt_tokens` y `completion_tokens` son los que reporta Groq. No son directamente
  comparables entre sí porque usan tokenizadores distintos; se publican por separado.

## Resultados A/B/C

| Configuración | Herramientas iniciales | Éxito | Selección@1 | Argumentos válidos | Abstención | Llamada innecesaria | Tokens defs | Prompt tokens | Tokens totales medios | p50 | p95 |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A. Estática | 22 | 58,33% | 58,00% | 100,00% | 90,00% | 10,00% | 2.493,0 | 983,32 | 1.111,2 | 3.175,5 ms | 10.259,5 ms |
| B. Meta-tools | 2 | 50,00% | 46,00% | 96,00% | 100,00% | 0,00% | 557,0 | 942,47 | 1.180,9 | 6.339,9 ms | 12.695,6 ms |
| C. Híbrida | 3 fijas + top-8 + 2 meta | 63,33% | 62,00% | 100,00% | 90,00% | 10,00% | 958,9 | 606,22 | 737,4 | 3.996,9 ms | 7.064,9 ms |

**Lectura directa:**

- Híbrida reduce los tokens de definiciones un **61,5%** frente a estática, los tokens de
  prompt un **38,4%** y los tokens totales medios un **33,7%**. El éxito sube 5,0 puntos
  porcentuales (58,33% → 63,33%), dentro del ruido esperable de 60 tareas.
- Meta reduce los tokens de definiciones un **77,7%**, pero **no** reduce el prompt total
  (942,47 vs 983,32; un 4,2% menos) y aumenta los tokens totales medios un **6,3%**
  porque el modelo necesita más rondas. El éxito cae 8,3 puntos.
- La abstención es 90% en estática e híbrida y 100% en meta. El único falso positivo
  repetido es `neg-07` (“Resume el PDF adjunto”), que llama a `docs__list_docs` en
  estática e híbrida.
- La caché no se usó en los runs completos (`cache_hit_rate = 0`), para que los tokens y
  las latencias no estuvieran contaminados por respuestas previas.

## Resultados por bloque

Éxito de tarea por bloque (porcentaje):

| Bloque | Tareas | Estática | Meta | Híbrida |
| :--- | ---: | ---: | ---: | ---: |
| Documentación | 20 | 35,00% | 35,00% | 30,00% |
| Investigación | 15 | 53,33% | 40,00% | 60,00% |
| Operaciones | 15 | 73,33% | 46,67% | 93,33% |
| Negativas (abstención) | 10 | 90,00% | 100,00% | 90,00% |
| **Total** | **60** | **58,33%** | **50,00%** | **63,33%** |

Operaciones es donde la divulgación híbrida funciona mejor: las tres herramientas fijas
incluyen `ops__list_services` y el router léxico encuentra `query_metrics`, `get_service`
o `restart_service`. Documentación es el punto débil de los tres modos: el modelo confunde
`search_docs`/`list_docs` con `read_doc`, `outline_doc` y `cite_doc`.

## Análisis de fallos

### Documentación

- En estática, 13/20 tareas fallan. La mayoría elige `docs__search_docs` cuando el `gold`
  era `read_doc`, `outline_doc` o `cite_doc`.
- En híbrida, 14/20 fallan; el patrón cambia a `docs__list_docs` cuando el documento ya
  está identificado en la pregunta.
- La descripción de `read_doc` no enumera los ids (`protocolo`, `gateway`, `seguridad`,
  `operacion`, `evaluacion`), así que el modelo no sabe que puede leer directamente.
  Es una mejora concreta para la siguiente iteración, no un resultado oculto.
- `docs-02` (“Busca información sobre SSRF”) elige `research__wikipedia_get` o
  `research__wikipedia_search` en estática/híbrida: el tema es compartido por dos
  upstreams y el router léxico no resuelve la ambigüedad.

### Investigación

- El modelo confunde con frecuencia `wikipedia_search` con `wikipedia_get` cuando la
  consulta empieza por “Busca…”. En estática fallan 7/15; en híbrida, 6/15; en meta,
  9/15.
- `research-08` selecciona correctamente `research__wikipedia_get`, pero llama con
  `title="Server Side Request Forgery"` y la fixture solo acepta
  `Server-side request forgery` (con guion). El fallo es de robustez de la herramienta,
  no de selección; queda como deuda conocida de robustez de la herramienta.
- `research-11` en meta usa `server="arxiv"` con `tool="arxiv_get"`; el gateway solo
  conoce `research__arxiv_get`. El error queda registrado como argumento inválido.
- `research-13` en meta usa `id` en lugar de `arxiv_id`.

### Operaciones

- Híbrida acierta 14/15. El único fallo es una tarea de escritura con la herramienta
  correcta pero un título con capitalización distinta (`latencia en checkout` frente a
  `Latencia en checkout`): el predicado era demasiado estricto.
- Meta acierta 7/15. La causa principal es que el modelo no siempre llama a
  `find_tools`/`invoke_tool` con el nombre canónico y, en varios casos, se abstiene.
- Estática acierta 11/15. `ops-10` selecciona `ops__search_logs` pero busca
  “error de conexión” en logs en inglés; la búsqueda no encuentra `connection`.
- `ops-12` selecciona correctamente `create_incident`; el fallo es de predicado, no de
  selección. Se reporta tal cual.

### Negativas

- `neg-07` (“Resume el PDF adjunto”) es el único falso positivo en estática e híbrida:
  el modelo llama a `docs__list_docs`. Meta no invoca ninguna herramienta.
- Las otras nueve negativas se abstienen correctamente en los tres modos.

## Robustez y ablations

La cuota diaria se renovó y se completaron las dos mediciones pendientes. Los nuevos
runs consumieron **93.621 tokens** de proveedor adicionales. Ninguna repetición usó
caché (`cache_hit_rate = 0` en las seis ejecuciones).

### 3 repeticiones sobre 20 tareas

Subconjunto estratificado: 7 de documentación, 5 de investigación, 5 de operaciones y 3
negativas (`eval/robustness_ids.json`). Cada repetición se ejecutó con un directorio de
caché vacío.

| Repetición | Éxito | Selección@1 | Tokens defs | Prompt tokens | p50 | p95 | Caché |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 55,00% | 52,94% | 973,2 | 599,4 | 821,6 ms | 5.075,2 ms | 0% |
| 2 | 55,00% | 52,94% | 999,1 | 643,7 | 4.035,6 ms | 9.786,2 ms | 0% |
| 3 | 55,00% | 52,94% | 999,1 | 643,7 | 3.760,3 ms | 7.623,8 ms | 0% |

El éxito y la selección fueron idénticos en las tres repeticiones, pero **no** los
aciertos concretos: en la repetición 1 falló `ops-10` y `neg-07` se abstuvo; en las
repeticiones 2 y 3 ocurrió lo contrario. La latencia varió de forma notable, como era
esperable en un servicio remoto. La varianza de precisión es, por tanto, cero en esta
muestra; la de latencia, alta.

### Ablations de `k`

Mismas 20 tareas, modo híbrido, caché vacía para cada valor de `k`:

| `k` | Éxito | Selección@1 | Argumentos válidos | Tokens defs | Prompt tokens | p50 | p95 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 55,00% | 52,94% | 100,00% | 893,3 | 623,3 | 2.667,7 ms | 8.194,0 ms |
| 8 | 50,00% | 52,94% | 100,00% | 999,1 | 643,5 | 2.616,1 ms | 7.917,6 ms |
| 12 | 55,00% | 52,94% | 100,00% | 1.020,0 | 650,6 | 3.527,8 ms | 6.162,2 ms |

No hay una tendencia monótona: `k=5` y `k=12` empatan en éxito y `k=8` falla una tarea
más (`ops-10`). Los tokens de definiciones sí crecen con `k` (893,3 → 1.020,0). En esta
muestra, reducir a `k=5` mantiene la precisión y ahorra contexto; no se generaliza a
partir de 20 tareas.

## Reproducción

```bash
cd mcp-gateway
.venv/bin/python eval/build_tasks.py
.venv/bin/python -m eval.validate_tasks

# Sin clave: valida el pipeline con el modelo oráculo
.venv/bin/python -m eval.run_eval --config hybrid --model fake --limit 60 \
  --output /tmp/eval-fake.jsonl

# Run real: la clave se carga desde el entorno, nunca se imprime
.venv/bin/python -m eval.run_eval --config hybrid --model groq \
  --llm-model openai/gpt-oss-120b --limit 60 \
  --output eval/results/2026-10-26-hybrid-groq.jsonl \
  --summary eval/results/2026-10-26-hybrid-groq.summary.json
```

El runner es reanudable: omite tareas con `status="ok"` ya presentes en el JSONL. Los
fallos de cuota se registran como `model_error` y el proceso sale con código 2 para poder
continuar en otro lote.

## Límites

- 60 tareas es una muestra pequeña; las diferencias de 5 puntos porcentuales no deben
  presentarse como significativas.
- El router es léxico (BM25 + expansión bilingüe explícita), no semántico. La expansión
  mejora las consultas español → inglés, pero no sustituye a embeddings.
- El prompt y las descripciones de herramientas son parte del sistema medido; cambiarlas
  exige repetir el run completo.
- La evaluación mide una llamada principal; no modela flujos de varios turnos donde el
  agente inspecciona un resultado y corrige.
- La robustez y las ablations usan 20 tareas; sirven para detectar inestabilidad y
  coste, no para estimar intervalos de confianza estrechos.
