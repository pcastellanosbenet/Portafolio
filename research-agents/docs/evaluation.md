# Evaluación con corpus congelado

> **Estado (2026-10-29):** el marco de evaluación está implementado. Se ejecutó
> el *smoke eval* real de 6 ejecuciones (2 preguntas × B0/B1/B2), **B0, B1 y B2
> completos sobre las 20 preguntas**. B1 necesitó dos sesiones y B2 tres porque
> sus consumos superan el TPD de 200.000 por modelo y día. B2 conserva un
> `JSONDecodeError` del researcher en M05 y un juicio de C04 que hubo que
> repetir. Las 3 repeticiones de robustez siguen pendientes. Este documento
> separa el smoke, los lotes B0/B1/B2 y la robustez: **la comparación de 20
> preguntas está completa, pero todavía no hay 3 repeticiones**.

## Por qué un corpus congelado

Una evaluación con búsqueda web en vivo no es reproducible: los resultados
cambian entre ejecuciones, las páginas desaparecen y cada sistema puede recibir
evidencia distinta. Para comparar B0, B1 y B2 con las mismas condiciones, la
Fase 4 usa un corpus versionado:

- 30 documentos de Wikipedia en español e inglés, recuperados el **2026-10-23**.
- Licencia **CC BY-SA 4.0**, con URL, atribución y fecha de recuperación.
- URL canónica, `source_id` derivado de la URL y SHA-256 del contenido.
- Búsqueda léxica determinista y *aliases* para consultas en español.
- `fetch_page` solo devuelve páginas del corpus; no hay *fallback* a Internet.

Archivos:

| Archivo | Contenido |
| :--- | :--- |
| `eval/frozen/corpus.json` | Documentos, metadatos de licencia, URLs y hashes |
| `eval/questions.json` | 20 preguntas, hechos de referencia, fuentes esperadas y rúbrica |
| `eval/results/smoke-20261023b/` | Registros crudos, resumen y gráfico del smoke real |
| `eval/results/eval-full-20261024/` | B0, B1 y B2 completos sobre 20 preguntas; robustez pendiente |

El corpus se valida al cargarlo: si un documento cambia y su SHA-256 no coincide,
la evaluación falla antes de ejecutar modelos. Los tests comprueban la integridad,
la licencia, la unicidad de IDs y que cada fuente esperada exista en el corpus.

## Preguntas

Hay 20 preguntas, cinco por categoría:

| Categoría | IDs | Qué mide |
| :--- | :--- | :--- |
| Factual | F01–F05 | Definiciones y mecanismos presentes en el corpus |
| Comparación | C01–C05 | Diferencias y similitudes entre dos conceptos |
| Multi-hop | M01–M05 | Relacionar dos o tres documentos |
| Sin respuesta | U01–U05 | Reconocer que el corpus no contiene la información |

Las preguntas U01–U05 preguntan por datos actuales o externos al corpus (cuotas,
rankings, precios, detalles de entrenamiento). La respuesta correcta es abstenerse
de inventar, no recuperar una página web.

Cada pregunta respondible declara:

- `expected_facts`: hechos de referencia y variantes de superficie que cuentan
  como cobertura.
- `expected_source_urls`: fuentes del corpus que deberían sostener la respuesta.
- `rubric`: nota breve para el juez y para la revisión humana.

## Sistemas comparados

Los tres sistemas usan el mismo corpus, las mismas herramientas congeladas y los
mismos límites duros de llamadas y tokens. La diferencia es la orquestación:

| Sistema | Diseño | Componentes |
| :--- | :--- | :--- |
| **B0** | Agente único ReAct | Un researcher con herramientas; responde directamente |
| **B1** | Pipeline fijo | Planner → researchers → writer, sin supervisor, analista ni critic |
| **B2** | Equipo completo | Grafo de Fase 3: supervisor, planner, researchers, analyst, critic, writer y HITL desactivado |

B1 y B0 son las ablaciones principales: permiten estimar qué aporta la
coordinación completa frente a un pipeline fijo o un solo agente. El CLI permite
seleccionar sistemas con `--systems b0,b1,b2` y limitar rondas, workers y pasos
con los overrides documentados en `scripts/run_eval.py`.

## Juez y rúbrica

El juez recibe una carga **ciega**: no ve el nombre del sistema, su uso de tokens
ni su latencia. Solo recibe la pregunta, los hechos y fuentes de referencia, la
respuesta, los claims, las fuentes y las limitaciones.

Rúbrica 0/1/2:

- **2**: correcta y completa; cubre todos los hechos esperados, no contiene
  claims materiales sin soporte y las citas apuntan a las fuentes esperadas. En
  una pregunta sin respuesta, se abstiene explícitamente.
- **1**: parcial; cubre algunos hechos o tiene un problema menor de soporte o de
  citas.
- **0**: incorrecta, incompleta de forma sustancial, cita fuentes inventadas o no
  se abstiene cuando debía hacerlo.

La salida es estructurada y se valida localmente. Si el juez da un 2 con hechos
sin cubrir, o un 2 a una pregunta sin respuesta sin abstención, el runner reintenta
una vez con una corrección explícita. Si vuelve a fallar, el error se guarda en
`judge_error` y no se inventa una puntuación.

En el smoke se intentó usar Gemini como juez independiente, pero la API devolvió
timeouts repetidos (`OpenAITimeoutError`). Para no bloquear el lote se usó Groq
`openai/gpt-oss-20b` como juez. Es una limitación real: **el juez del smoke no es
de un proveedor distinto al sistema evaluado**. La configuración independiente
queda implementada y debe usarse cuando Gemini esté disponible.

## Métricas

| Métrica | Definición | Lectura |
| :--- | :--- | :--- |
| `task_success_binary` | 1 si el juez da 2; 0 en otro caso | Métrica principal de calidad |
| `task_success_score` | Puntuación 0/1/2 del juez | Permite ver mejoras parciales |
| `factual_coverage` | Hechos esperados cubiertos / total, por coincidencia de variantes | Determinista; puede dar falsos positivos por coincidencia léxica |
| `judge_factual_coverage` | Hechos que el juez declara cubiertos / total | Complementa la cobertura determinista |
| `citation_precision` | Citas a URLs esperadas / citas totales | Estricta: penaliza fuentes adicionales aunque sean válidas |
| `citation_validity` | Citas a fuentes recuperadas / citas totales | Detecta IDs inventados o fuera del informe |
| `source_recall` | URLs esperadas citadas / URLs esperadas | Cobertura de las fuentes de referencia |
| `claim_support_rate` | Claims con al menos una fuente válida / claims | Comprueba estructura, no entailment |
| `claim_relevance_rate` | Claims con una fuente esperada / claims | Versión estricta del soporte |
| `abstention_correct` | 1 si una pregunta sin respuesta se abstiene y el run terminó | Solo se evalúa en U01–U05 |
| `avg_llm_calls`, `avg_tokens` | Media por ejecución | Coste del sistema |
| `p50_latency_s`, `p95_latency_s` | Percentiles de duración | Incluyen esperas del limitador de TPM |

`citation_precision` y `citation_validity` se reportan por separado a propósito.
Una respuesta puede citar solo fuentes reales (validez 1,0) pero incluir fuentes
que no están en el conjunto esperado (precisión menor). No se debe interpretar la
precisión estricta como una medida de entailment.

## Smoke eval real

Configuración:

| Parámetro | Valor |
| :--- | :--- |
| Preguntas | F01 (factual) y U01 (sin respuesta) |
| Sistemas | B0, B1, B2 |
| Repeticiones | 1 |
| Corpus | `eval/frozen/corpus.json`, 30 documentos |
| Proveedor principal | Groq |
| Modelo principal | `openai/gpt-oss-120b` (planner/analyst/critic/writer de B1/B2) |
| Modelo rápido | `openai/gpt-oss-20b` (B0, researchers y juez) |
| Juez | Groq `openai/gpt-oss-20b` (Gemini no respondió) |
| Fallback del sistema | Desactivado |
| Límites | 1 ronda, 1 worker, 1 paso de herramienta, 12 llamadas, 30.000 tokens |

Resultados globales:

| Sistema | Éxito tarea | Score juez | Cobertura | Precisión citas | Validez citas | Recall fuentes | Soporte claims | Abstención | Llamadas | Tokens | p50 | p95 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| B0 · agente único | 1,00 | 2,00 | 1,00 | 0,67 | 1,00 | 1,00 | 1,00 | 1,00 | 2 | 1.786 | 1,8 s | 56,3 s |
| B1 · pipeline fijo | 0,50 | 1,50 | 1,00 | 0,40 | 1,00 | 1,00 | 1,00 | 1,00 | 8 | 9.703 | 241,9 s | 302,0 s |
| B2 · equipo completo | 1,00 | 2,00 | 1,00 | 0,25 | 1,00 | 1,00 | 1,00 | 1,00 | 10 | 16.128,5 | 363,6 s | 419,8 s |

Por categoría (éxito de tarea):

| Categoría | B0 | B1 | B2 |
| :--- | :---: | :---: | :---: |
| Factual (F01) | 1 | 0 | 1 |
| Sin respuesta (U01) | 1 | 1 | 1 |

El juez consumió 6 llamadas y 13.250 tokens adicionales, no incluidos en la tabla
de tokens de los sistemas.

### Lectura honesta del smoke

- **B0 resolvió F01 y U01 con 2 llamadas y 1.786 tokens de media.** Fue el sistema
  más barato y rápido en este lote.
- **B1 falló F01 (score 1)**: cubrió los hechos, pero añadió una afirmación sobre
  que el aprendizaje profundo requiere grandes volúmenes de datos que no estaba
  soportada por las fuentes. Es un fallo de fidelidad, no de formato.
- **B2 resolvió ambas preguntas (score 2), pero con 10 llamadas y 16.128,5 tokens
  de media.** Su precisión estricta de citas en F01 fue 0,25: citó 8 fuentes y
  solo 2 pertenecían al conjunto esperado. La validez fue 1,00, así que no inventó
  IDs; simplemente incluyó fuentes adicionales.
- **La latencia de B1/B2 está dominada por las esperas del free tier**, no por
  inferencia pura. B0 también tuvo una ejecución de 56 s por la misma razón.
- **B2 no es mejor en todo**: en este lote empató con B0 en calidad y costó ~9×
  más tokens. Con dos preguntas no se puede concluir que el equipo completo sea
  superior; hace falta la evaluación completa.

### Revisión manual

Se revisaron las **6 respuestas del smoke (100% del lote)**. La puntuación humana
coincidió con la del juez en las 6 para la rúbrica 0/1/2. Los hallazgos fueron:

1. En el smoke, B1 F01 añadió un claim no soportado sobre datos y deep learning;
   en el lote B1 posterior, F01 ya no tuvo claims no soportados.
2. B2 F01: tabla Markdown con una fila partida y citas adicionales que bajan la
   precisión estricta aunque el juez diera 2.
3. B0/B1/B2 U01: las tres se abstuvieron correctamente; el detector determinista
   tuvo que ampliarse para reconocer “no se dispone de información/evidencia”.

Esta revisión del smoke es una muestra pequeña; la revisión del 20% del lote
B0/B1 se documenta más abajo.

## Lote B0 completo (20 preguntas)

El 2026-10-24 se ejecutó **B0 sobre las 20 preguntas** con el corpus congelado,
una repetición, una ronda, un worker y un paso de herramienta. B0 usó el modelo
rápido `openai/gpt-oss-20b`, que también actuó como juez; las trazas lo confirman
aunque `run_meta.json` registre ambos modelos. Es un lote real de B0; las
secciones siguientes añaden B1 y B2 sobre las mismas 20 preguntas.

| Métrica | B0 |
| :--- | :---: |
| Registros | 20 |
| Éxito de tarea | 0,25 |
| Score medio del juez | 1,20 |
| Cobertura factual | 0,56 |
| Precisión estricta de citas | 0,83 |
| Validez de citas | 1,00 |
| Recall de fuentes | 0,89 |
| Soporte de claims | 1,00 |
| Abstención correcta (U01–U05) | 1,00 |
| Llamadas medias | 2 |
| Tokens medios | 2.143 |
| Latencia p50 / p95 | 58,5 s / 59,8 s |

Éxito de tarea por categoría:

| Categoría | B0 |
| :--- | :---: |
| Factual | 0,20 |
| Comparación | 0,20 |
| Multi-hop | 0,00 |
| Sin respuesta | 0,60 |

Lectura honesta:

- **B0 acierta 5 de 20 preguntas con la rúbrica estricta** (2/2 del juez). Es un
  resultado bajo y debe mostrarse tal cual.
- **Las cinco preguntas sin respuesta se abstuvieron**, pero U01 y U03 incluyeron
  citas irrelevantes y el juez les dio 1 en lugar de 2. Por eso la abstención
  correcta es 1,00 mientras el éxito de tarea de esa categoría es 0,60: son
  métricas distintas.
- **La latencia de ~58 s por ejecución está dominada por el limitador de TPM**,
  no por inferencia pura. Los tokens medios son bajos (2.143) porque B0 hace
  pocas llamadas.
- **No se debe concluir que B0 sea el mejor sistema.** Hay B0, B1 y B2
  completos; las 15 preguntas respondibles no se han revisado todas manualmente.
  La muestra manual es del 20%, no una auditoría completa.

### Revisión manual de B0 (4 de 20)

Se revisaron una pregunta por categoría: F01, C01, M01 y U01. La puntuación
humana coincidió con la del juez en las cuatro:

| Pregunta | Juez | Humano | Hallazgo |
| :--- | :---: | :---: | :--- |
| F01 | 2 | 2 | Define AA y AD; la cobertura determinista da 1,00 |
| C01 | 2 | 2 | Comparación correcta; precisión estricta 0,67 por fuentes adicionales |
| M01 | 1 | 1 | Falta la idea de atención como selección/supresión de información |
| U01 | 1 | 1 | Se abstiene, pero cita fuentes irrelevantes |

Esta muestra es el 20% del lote B0. La revisión de B1, con 4 registros, está en
la sección siguiente.

Registros, resumen y gráfico:
[`eval/results/eval-full-20261024/`](../eval/results/eval-full-20261024/).
El resumen B0+B1 se regenera sin llamadas nuevas (los 40 registros ya existen):

```bash
.venv/bin/python -m scripts.run_eval \
  --systems b0,b1 --run-id eval-full-20261024 --resume \
  --max-rounds 1 --max-workers 1 --max-tool-steps 1 \
  --max-llm-calls 12 --max-tokens 30000 \
  --judge-provider groq --judge-model openai/gpt-oss-20b
```

## Lote B1 completo (20 preguntas)

B1 se ejecutó en dos sesiones con el mismo `run_id`: 11 registros el 2026-10-25
(F01–F05, C01–C05, M01) y los 9 restantes el 2026-10-26 (M02–M05, U01–U05).
El primer corte fue por cuota, no por un fallo: el runner preservó los registros
y el segundo `--resume` omitió los 11 ya completados. No hubo errores de sistema
ni del juez en los 20 registros.

Consumo medido: **210.213 tokens de 20b** (sistema + juez) y **82.828 de 120b**
en total. La primera sesión usó 127.774/49.946 y la segunda 82.439/32.882.

| Métrica | B1 (20 registros) |
| :--- | :---: |
| Éxito de tarea | 0,55 (11/20) |
| Score medio del juez | 1,55 |
| Cobertura factual | 0,56 |
| Cobertura factual del juez | 0,82 |
| Precisión estricta de citas | 0,74 |
| Validez de citas | 1,00 |
| Recall de fuentes | 0,91 |
| Soporte de claims | 1,00 |
| Abstención correcta (U01–U05) | 1,00 |
| Llamadas medias | 9,10 |
| Tokens medios | 11.972 |
| Latencia p50 / p95 | 357,3 s / 360,9 s |

Éxito de tarea por categoría:

| Categoría | B0 | B1 | n |
| :--- | :---: | :---: | :---: |
| Factual | 0,20 | 0,20 | 5 |
| Comparación | 0,20 | 0,40 | 5 |
| Multi-hop | 0,00 | 0,60 | 5 |
| Sin respuesta | 0,60 | 1,00 | 5 |

B1 acierta 11 de 20: F01, C01, C03, M01, M03, M04 y U01–U05. B0 acierta 5:
F01, C01, U02, U04 y U05. La mejora se concentra en multi-hop (3/5 vs 0/5) y
en las preguntas sin respuesta (5/5 vs 3/5); factual no mejora (1/5 en ambos) y
comparación sube de 1/5 a 2/5.

Lectura honesta:

- **B1 gana en éxito de tarea, pero no gratis.** Sube de 0,25 a 0,55, usa 5,6×
  los tokens medios (11.972 vs 2.143), 4,6× las llamadas (9,10 vs 2) y 6,1× la
  latencia p50 (357,3 s vs 58,5 s). La precisión estricta de citas baja de 0,83
  a 0,74; la cobertura determinista queda igual (0,56) y el recall de fuentes
  sube ligeramente (0,91 vs 0,89).
- **La mejora está en descomposición y abstención.** B1 resuelve 3 de 5
  multi-hop y las 5 preguntas sin respuesta; B0 no resuelve ningún multi-hop y
  falla 2 de 5 sin respuesta. Para preguntas factuales simples, B0 sigue siendo
  más barato y más preciso en citas.
- **Una sola repetición no demuestra robustez.** Estas diferencias son de un
  único lote; las 3 repeticiones de robustez siguen pendientes. No se debe
  generalizar a otros corpus ni presentar B1 como “mejor” sin el coste.

### Revisión manual de B1 (4 de 20)

Se revisaron F01, C01, M01 y U01; la puntuación humana coincidió con la del juez
en las cuatro (2/2). B1 U01 se abstiene correctamente y no inventa una cuota.
B1 F01 mantiene el **falso negativo de la métrica léxica**: la cobertura
determinista da 0,333 porque la respuesta usa “subcampo de la informática y la
inteligencia artificial” en vez de las variantes esperadas, mientras que el juez
considera cubiertos los 3 hechos.

La muestra manual acumulada hasta B1 es 8 de 40 registros (20%): 4 de B0 y 4 de
B1, con 8/8 de coincidencia juez-humano. B2 añade otros 4 registros en la
sección siguiente.

## Lote B2 completo (20 preguntas)

B2 se ejecutó en tres sesiones con el mismo `run_id`: 7 registros el 2026-10-27
(F01–F05, C01–C02), 7 el 2026-10-28 (C03–C05, M01–M04) y 6 el 2026-10-29 (M05 y
U01–U05), más la repetición de C04. El primer juicio de C04 falló con
`StructuredOutputError`; se conservó el registro defectuoso fuera del árbol y se
repitió. El resultado final no tiene errores de juez.

M05 sí conserva un error del sistema: un `JSONDecodeError` del researcher hizo
perder una subpregunta y el informe quedó incompleto (score 1). No se oculta: es
el único registro B2 con error.

Consumo final medido: **222.292 tokens de 120b** y **201.186 de 20b** (sistema +
juez) en 20 registros. El intento fallido de C04 añadió ~11.200 de 120b y ~8.100
de 20b que no están incluidos en ese total final.

| Métrica | B2 (20 registros) |
| :--- | :---: |
| Éxito de tarea | 0,45 (9/20) |
| Score medio del juez | 1,45 |
| Cobertura factual | 0,60 |
| Cobertura factual del juez | 0,77 |
| Precisión estricta de citas | 0,75 |
| Validez de citas | 1,00 |
| Recall de fuentes | 0,83 |
| Soporte de claims | 1,00 |
| Relevancia de claims | 0,93 |
| Abstención correcta (U01–U05) | 1,00 |
| Llamadas medias | 10,95 |
| Tokens medios | 18.587 |
| Latencia p50 / p95 | 424,8 s / 538,6 s |

Éxito de tarea por categoría:

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

Lectura honesta:

- **B2 no es la mejor opción global.** B1 tiene más éxito (0,55 vs 0,45), mejor
  score (1,55 vs 1,45) y usa 1,55× menos tokens (11.972 vs 18.587). B2 tiene una
  precisión de citas ligeramente mejor (0,75 vs 0,74), pero peor recall de
  fuentes (0,83 vs 0,91) y peor cobertura del juez (0,77 vs 0,82).
- **Frente a B0, B2 tampoco domina.** Gana 4 preguntas más, pero usa 8,7× los
  tokens y 7,3× la latencia p50, con menor precisión de citas (0,75 vs 0,83) y
  menor recall (0,83 vs 0,89). B0 sigue siendo la opción barata.
- **El error de M05 importa.** El researcher no pudo parsear una respuesta JSON,
  perdió una subpregunta y el informe no cubrió dos hechos. Es un fallo real de
  robustez del sistema, no un artefacto del juez.

### Revisión manual de B2 (4 de 20)

Se revisaron F01, C01, M01 y U01; la puntuación humana coincidió con la del juez
en las cuatro (2/2). F01 añade una tabla con generalizaciones no citadas y baja a
0,50 de precisión de citas; C01 está limpio (1,00); M01 mantiene un falso
negativo léxico (0,667) porque la respuesta dice “asigna pesos” en vez de
“realza/disminuye”; U01 se abstiene correctamente pero cita tres fuentes
irrelevantes (precisión y recall 0,00).

La muestra manual acumulada final es **12 de 60 registros (20%)**: 4 de B0, 4 de
B1 y 4 de B2, con **12/12 de coincidencia juez-humano**. Es una muestra pequeña,
no una auditoría completa.

## Taxonomía de fallos observada

| Tipo | Ejemplo | Tratamiento |
| :--- | :--- | :--- |
| Claim no soportada | En el smoke, B1 F01 afirmó una necesidad de grandes volúmenes de datos sin evidencia | El juez la penaliza; el critic estructural no la detecta |
| Dilución de citas | B2 F01 citó 8 fuentes para 2 esperadas | Se reporta precisión estricta y validez por separado |
| Defecto de formato | B2 F01 generó una tabla Markdown incompleta | Revisión humana; no afecta al score del juez |
| Coste/latencia | B2 usó ~8,7× tokens y ~7,3× la latencia p50 de B0 | Se reportan tokens y percentiles, no solo calidad |
| Fallo del juez | Gemini devolvió timeouts | Se registra `judge_error`; se usó Groq y se declara la limitación |
| Cuota | El lote completo no cabe en una sesión de free tier | Runner reanudable y ejecución por lotes |

## Reproducción

Desde `research-agents`:

```bash
uv venv --python 3.12
uv pip install -r requirements-dev.txt
cp .env.example .env
# edita .env con GROQ_API_KEY, GEMINI_API_KEY y TAVILY_API_KEY

# Validar corpus y plan sin llamar a APIs
.venv/bin/python -m scripts.run_eval --dry-run

# Reproducir el smoke (6 ejecuciones)
.venv/bin/python -m scripts.run_eval \
  --systems b0,b1,b2 \
  --question-id F01 --question-id U01 \
  --run-id smoke-20261023b \
  --max-rounds 1 --max-workers 1 --max-tool-steps 1 \
  --max-llm-calls 12 --max-tokens 30000 \
  --judge-provider groq --judge-model openai/gpt-oss-20b
```

Para reanudar un lote interrumpido, usa el mismo `--run-id` y `--resume`. El
runner omite las claves `(pregunta, sistema, repetición)` ya presentes en
`records.jsonl` y recalcula las métricas derivadas al generar el resumen.

La evaluación completa prevista es:

```bash
.venv/bin/python -m scripts.run_eval \
  --systems b0,b1,b2 \
  --run-id eval-full-YYYYMMDD \
  --max-rounds 1 --max-workers 1 --max-tool-steps 1 \
  --judge-provider <proveedor> --judge-model <modelo>
```

Debe ejecutarse por lotes con `--resume` para respetar la cuota. Las 3
repeticiones de robustez se harán sobre un subconjunto acordado, no sobre las 20
preguntas completas.

B1 y B2 ya están completos; B2 necesitó tres sesiones. El comando se conserva
para reanudar un lote interrumpido o repetir la evaluación:

```bash
.venv/bin/python -m scripts.run_eval \
  --systems b2 --run-id eval-full-20261024 --resume \
  --max-rounds 1 --max-workers 1 --max-tool-steps 1 \
  --max-llm-calls 12 --max-tokens 30000 \
  --judge-provider groq --judge-model openai/gpt-oss-20b
```

No mezcles B2 con nuevas repeticiones de B0/B1 en el mismo día con el plan
gratuito: B2 ya roza el TPD de 120b por sí solo.

## Presupuesto de cuota y decisión de ejecución

El plan gratuito de Groq limita **cada modelo** a 30 RPM, 1.000 RPD, 8.000 TPM y
**200.000 TPD** (comprobado en la documentación oficial el 2026-10-25). El juez
también consume tokens del modelo que se le asigna. Esto hace que el benchmark
completo no quepa en una sola sesión:

| Bloque | 120b | 20b | Base |
| :--- | ---: | ---: | :--- |
| B0/20 | 0 | 83.337 | medido: 42.860 del sistema + 40.477 del juez |
| B1/20 | 82.828 | 210.213 | medido en dos días: 127.774/49.946 + 82.439/32.882 |
| B2/20 | 222.292 | 201.186 | medido en tres sesiones (7+7+6; C04 repetido) |
| **Total** | **305.120** | **494.736** | **B0+B1+B2; falta robustez** |

Las cifras de B0, B1 y B2 son medidas y no incluyen el intento fallido de C04
(~11.200/8.100). B1 no cupo en un día (210.213 de 20b) y se partió en 11 + 9;
B2 tampoco (201.186 de 20b y 222.292 de 120b) y se partió en 7 + 7 + 6. El
runner reanuda con el mismo `run_id` y `--resume` sin repetir preguntas. La
robustez sigue pendiente.

## Limitaciones

- **El smoke no es la evaluación completa.** Solo hay 2 preguntas; las métricas
  agregadas no son representativas.
- **La comparación B0/B1/B2 de 20 preguntas está completa; falta robustez.**
  Los tres sistemas están medidos sobre las mismas preguntas, pero no hay
  todavía 3 repeticiones sobre el subconjunto acordado.
- **El juez no fue independiente.** Gemini falló por timeouts tanto en el smoke
  como en B0, B1 y B2. Un juez del mismo proveedor puede compartir sesgos con el
  sistema evaluado.
- **La cobertura factual es léxica.** Las variantes están escritas a mano; una
  respuesta correcta con otra formulación puede no coincidir.
- **La precisión de citas es estricta.** Penaliza fuentes adicionales válidas.
  Por eso se reporta también validez y recall.
- **No hay entailment semántico.** `claim_support_rate` comprueba que el claim
  tenga una fuente válida, no que la fuente lo implique.
- **Wikipedia no es una verdad absoluta.** El corpus es una foto del 2026-10-23;
  las respuestas se evalúan contra ese corpus, no contra el estado actual de la web.
- **La latencia incluye rate limiting.** No debe presentarse como latencia pura
  del proveedor.
- **La evaluación de 20 preguntas está completa; la robustez no.** B0, B1 y B2
  tienen 20/20. B1 necesitó dos sesiones y B2 tres porque sus consumos superan el
  TPD de 200.000 por modelo y día. C04 se repitió por un fallo del juez y M05
  conserva un error del researcher. No se han inventado resultados.
- **Ningún sistema es uniformemente mejor.** B1 gana en éxito global y
  abstención; B2 gana en comparación; B0 es el más barato y el más preciso en
  citas. La comparación honesta debe incluir coste y calidad de citas, no solo
  el score.
- **B2 tiene un error de sistema.** M05 perdió una subpregunta por un
  `JSONDecodeError` del researcher y el informe quedó incompleto (score 1). Es
  el único registro B2 con error; se conserva y se documenta.

## Licencia y atribución del corpus

Los textos de Wikipedia se distribuyen bajo **CC BY-SA 4.0**. Cada documento del
corpus incluye `license`, `license_url`, `attribution`, `retrieved_at` y la URL de
la página original. El corpus se incluye solo como evidencia de evaluación; no se
presenta como obra propia. Consulta también `eval/README.md`.
