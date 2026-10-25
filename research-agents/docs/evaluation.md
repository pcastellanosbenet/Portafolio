# Evaluación con corpus congelado

> **Estado (2026-10-25):** el marco de evaluación está implementado. Se ejecutó
> el *smoke eval* real de 6 ejecuciones (2 preguntas × B0/B1/B2), **B0 completo
> sobre las 20 preguntas** y **B1 parcial con 11/20**. B2 sigue pendiente: el free
> tier de Groq limita cada modelo a 200.000 TPD y B1+B2 no caben en la misma
> sesión; los 9 registros restantes de B1 tampoco cabían tras 127.774 tokens de
> 20b. Las 3 repeticiones de robustez tampoco se han ejecutado. Este documento
> separa explícitamente el smoke, los lotes B0/B1 y la evaluación completa:
> **B0/20 y B1 parcial no son todavía el benchmark B0/B1/B2**.

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
| `eval/results/eval-full-20261024/` | Lote B0/20 y B1 por lotes; B2 pendiente |

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

Esta revisión es una muestra pequeña y no sustituye la revisión del 20% de una
evaluación completa.

## Lote B0 completo (20 preguntas)

El 2026-10-24 se ejecutó **B0 sobre las 20 preguntas** con el corpus congelado,
una repetición, una ronda, un worker y un paso de herramienta. B0 usó el modelo
rápido `openai/gpt-oss-20b`, que también actuó como juez; las trazas lo confirman
aunque `run_meta.json` registre ambos modelos. Es un lote real, pero **solo de
B0**: no sustituye la comparación B0/B1/B2.

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
- **No se debe concluir que B0 sea el mejor sistema.** Hay B0 completo y B1
  parcial; B2 sigue pendiente. Las 15 preguntas respondibles necesitan revisión
  manual antes de atribuir los fallos a una causa concreta.

### Revisión manual de B0 (4 de 20)

Se revisaron una pregunta por categoría: F01, C01, M01 y U01. La puntuación
humana coincidió con la del juez en las cuatro:

| Pregunta | Juez | Humano | Hallazgo |
| :--- | :---: | :---: | :--- |
| F01 | 2 | 2 | Define AA y AD; la cobertura determinista da 1,00 |
| C01 | 2 | 2 | Comparación correcta; precisión estricta 0,67 por fuentes adicionales |
| M01 | 1 | 1 | Falta la idea de atención como selección/supresión de información |
| U01 | 1 | 1 | Se abstiene, pero cita fuentes irrelevantes |

Esta muestra es el 20% del lote B0, no del lote completo B0/B1. La revisión de
B1, con 3 registros, está en la sección siguiente; U01 no se ejecutó.

Registros, resumen y gráfico:
[`eval/results/eval-full-20261024/`](../eval/results/eval-full-20261024/).
El resumen solo de B0 se regenera con:

```bash
.venv/bin/python -m scripts.run_eval \
  --systems b0 --run-id eval-full-20261024 --resume \
  --max-rounds 1 --max-workers 1 --max-tool-steps 1 \
  --max-llm-calls 12 --max-tokens 30000 \
  --judge-provider groq --judge-model openai/gpt-oss-20b
```

El resumen completo actual (B0 + B1 parcial) es el que está versionado; para
generarlo sin lanzar ejecuciones nuevas hace falta un script de agregación o
reanudar cuando la cuota lo permita.

## Lote B1 parcial (11 de 20)

El 2026-10-25 se reanudó B1 con el mismo `run_id` y `--resume`. Se completaron
F01–F05, C01–C05 y M01. A las 09:47 UTC el lote llevaba **127.774 tokens de
20b** (sistema + juez) y **49.946 de 120b**. Los 9 registros restantes
(M02–M05 y U01–U05) necesitaban aproximadamente 110.000 tokens más de 20b, por
encima de los 200.000 TPD. Para no forzar fallbacks ni registros con el juez
agotado, se interrumpió con `SIGINT`; el runner preservó los 11 registros y
escribió un resumen parcial.

| Métrica | B1 (11 registros) |
| :--- | :---: |
| Éxito de tarea | 0,36 (4/11) |
| Score medio del juez | 1,36 |
| Cobertura factual | 0,52 |
| Precisión estricta de citas | 0,81 |
| Validez de citas | 1,00 |
| Recall de fuentes | 0,91 |
| Soporte de claims | 1,00 |
| Abstención correcta | — (sin U) |
| Llamadas medias | 9,64 |
| Tokens medios | 13.106 |
| Latencia p50 / p95 | 359,4 s / 360,9 s |

Éxito de tarea por categoría (el tamaño de muestra importa):

| Categoría | B1 | n |
| :--- | :---: | :---: |
| Factual | 0,20 | 5 |
| Comparación | 0,40 | 5 |
| Multi-hop | 1,00 | 1 |
| Sin respuesta | — | 0 |

Lectura honesta:

- **B1 acierta 4 de 11**: F01, C01, C03 y M01. No es comparable con el 5/20 de
  B0 porque B1 no incluye las 5 preguntas sin respuesta y solo tiene 1 de 5
  multi-hop. Presentar 0,36 como “B1 supera a B0” sería incorrecto.
- **La calidad es parecida; el coste no.** B1 usa 6,1× los tokens medios y 6,1×
  la latencia p50 de B0 (9,64 vs 2 llamadas). La cobertura (0,52 vs 0,56) y la
  precisión de citas (0,81 vs 0,83) no mejoran de forma clara.
- **El corte es de cuota, no un fallo del sistema.** El runner es reanudable y
  el resumen parcial se generó sin inventar los 9 registros que faltan.

### Revisión manual de B1 (3 de 11)

Se revisaron F01, C01 y M01; la puntuación humana coincidió con la del juez en
las tres (2/2). B1 F01 es el caso más interesante: la cobertura determinista da
0,333 porque la respuesta usa “subcampo de la informática y la inteligencia
artificial” en vez de las variantes léxicas esperadas, mientras que el juez
considera cubiertos los 3 hechos. Es un **falso negativo de la métrica léxica**,
no un fallo de la respuesta. B1 U01 no se ejecutó por el corte de cuota.

La muestra manual acumulada es 7 de 31 registros (22,6%): 4 de B0 y 3 de B1.
No se presenta como una auditoría completa.

## Taxonomía de fallos observada

| Tipo | Ejemplo | Tratamiento |
| :--- | :--- | :--- |
| Claim no soportada | En el smoke, B1 F01 afirmó una necesidad de grandes volúmenes de datos sin evidencia | El juez la penaliza; el critic estructural no la detecta |
| Dilución de citas | B2 F01 citó 8 fuentes para 2 esperadas | Se reporta precisión estricta y validez por separado |
| Defecto de formato | B2 F01 generó una tabla Markdown incompleta | Revisión humana; no afecta al score del juez |
| Coste/latencia | B2 usó ~9× tokens y ~200× la latencia p50 de B0 | Se reportan tokens y percentiles, no solo calidad |
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

## Presupuesto de cuota y decisión de ejecución

El plan gratuito de Groq limita **cada modelo** a 30 RPM, 1.000 RPD, 8.000 TPM y
**200.000 TPD** (comprobado en la documentación oficial el 2026-10-25). El juez
también consume tokens del modelo que se le asigna. Esto hace que el benchmark
completo no quepa en una sola sesión:

| Bloque | 120b estimado | 20b estimado | Base de la estimación |
| :--- | ---: | ---: | :--- |
| B0/20 | 0 | ~83.000 | 42.860 del sistema + 40.477 del juez (medido) |
| B1/20 | ~91.000 | ~230.000 | 11 registros medidos y extrapolación de M/U |
| B2/20 | ~199.000 | ~173.000 | smoke B2 y 20 preguntas |
| **Total** | **~290.000** | **~486.000** | **supera 200.000 en ambos modelos** |

No son resultados: son estimaciones para planificar. La consecuencia práctica es
que B0, B1 y B2 deben ejecutarse en días distintos (o con un plan de pago) y que
no se debe presentar un lote parcial como si fuera la matriz completa. El runner
permite reanudar con el mismo `run_id` y `--resume`; B1 se ejecutó así. El
2026-10-25, tras 11 registros, B1 llevaba 127.774 tokens de 20b (sistema + juez)
y 49.946 de 120b; el corte se documenta en la sección del lote B1.

## Limitaciones

- **El smoke no es la evaluación completa.** Solo hay 2 preguntas; las métricas
  agregadas no son representativas.
- **El lote B0/20 tampoco es la evaluación completa.** B0 está medido y B1 quedó
  en 11/20 por el TPD; B2 no se ejecutó. Todavía no hay comparación completa
  entre sistemas ni 3 repeticiones de robustez.
- **El juez no fue independiente.** Gemini falló por timeouts tanto en el smoke
  como en el lote B0. Un juez del mismo proveedor puede compartir sesgos con el
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
- **La evaluación completa sigue pendiente.** B0 tiene 20/20; B1 quedó en 11/20
  porque los 9 registros restantes no cabían en el TPD de 200.000 tokens por
  modelo y día; B2 no se ejecutó. No se han inventado resultados para llenar la
  comparación de 20 preguntas.

## Licencia y atribución del corpus

Los textos de Wikipedia se distribuyen bajo **CC BY-SA 4.0**. Cada documento del
corpus incluye `license`, `license_url`, `attribution`, `retrieved_at` y la URL de
la página original. El corpus se incluye solo como evidencia de evaluación; no se
presenta como obra propia. Consulta también `eval/README.md`.
