# Spike de proveedores — 2026-10-22

Prueba de viabilidad de los proveedores gratuitos antes de construir el grafo completo.
El script usado es `scripts/spike_provider.py`; los resultados crudos están en
`artifacts/spike/` (ignorado por Git).

## Configuración probada

| Elemento | Valor |
| :--- | :--- |
| Python | 3.12.15 |
| Cliente | `langchain-openai` 1.7.2 con endpoints compatibles con OpenAI |
| Salida estructurada | `json_schema` |
| Tareas | 5: resumen, comparación, extracción, planificación y crítica |
| Groq | `openai/gpt-oss-120b` |
| Gemini | `gemini-3.8-flash` |
| Tavily | No usado en esta fase |

Los IDs de modelo se verificaron contra la API el 2026-10-22. Los modelos
`llama-3.3-70b-versatile` y `gemini-2.5-flash` ya no estaban disponibles para esta
cuenta, así que el `.env` se actualizó a los modelos vigentes.

## Resultados

### Groq — `openai/gpt-oss-120b`

| Métrica | Valor |
| :--- | ---: |
| Tareas completadas | 5/5 |
| Salida estructurada válida | 5/5 |
| Tokens totales | 2.626 |
| Latencia media | 0,969 s |
| Latencia mediana | 0,980 s |
| Errores 429 | 0 |

Las cinco tareas usaron `json_schema` sin fallback de método. El proveedor fue
estable y rápido en esta muestra.

### Gemini — `gemini-3.8-flash`

| Métrica | Valor |
| :--- | ---: |
| Tareas completadas | 4/5 |
| Salida estructurada válida | 4/4 de las respuestas emitidas |
| Tokens totales de las respuestas correctas | 2.233 |
| Latencia media | 29,397 s |
| Latencia mediana | 9,156 s |
| Errores 429 | 0 |
| Errores 503 | 1 |

La tarea de resumen falló tras agotar los reintentos con un `503 UNAVAILABLE`
(“model is currently experiencing high demand”). El fallo tardó 106,77 s y no
produjo respuesta. En una ejecución anterior también se obtuvo 4/5, con un fallo
transitorio distinto y una latencia atípica de 73 s.

Conclusión: Gemini es útil como fallback, pero no cumple el criterio de 5/5 como
proveedor principal en esta muestra. Su latencia mediana también es
aproximadamente 9 veces mayor que la de Groq.

### Observación sobre tokens

En Gemini, `input_tokens + output_tokens` no coincide con `total_tokens`
(p. ej. 24 + 102 = 126 frente a 572). El endpoint compatible con OpenAI reporta
tokens de caché o de razonamiento en el total. Para el presupuesto se usará
`total_tokens`, que es la cifra conservadora.

## Decisión

| Rol | Proveedor | Modelo |
| :--- | :--- | :--- |
| Principal | Groq | `openai/gpt-oss-120b` |
| Rápido (routing/extracción) | Groq | `openai/gpt-oss-20b` |
| Fallback | Gemini | `gemini-3.8-flash` |

El fallback está implementado y cubierto por tests con un error 503 simulado. En
producción, un fallo transitorio de Gemini no debería bloquear el run porque Groq
es el principal; si Groq falla, Gemini queda como segunda opción.

## Límites de los tiers gratuitos

- **Tavily:** 1.000 llamadas a la API al mes. Se implementó un contador
  persistente y se cachean las búsquedas en la Fase 2. El CI no hace llamadas
  reales.
- **Groq y Gemini:** los límites de RPM/TPM/RPD cambian con el tiempo. No se
  fijarán cifras en el README sin verificarlas en la consola el día de la
  medición. El cliente ya respeta `Retry-After` mediante backoff y fallback.
- **Presupuesto del spike:** 10 llamadas efectivas (5 por proveedor), más
  reintentos. No se observaron 429; sí un 503 transitorio en Gemini.

## Gate de la Fase 0

| Proveedor | ¿5/5? | ¿Salida estructurada? | Decisión |
| :--- | :--- | :--- | :--- |
| Groq | Sí | Sí, 5/5 | Principal |
| Gemini | No (4/5) | Sí, 4/4 emitidas | Fallback |

El gate se cumple para el sistema con Groq como principal. Gemini no se usa como
principal por su inestabilidad observada en el tier gratuito. La decisión quedó
registrada en el plan interno del proyecto y se continuó con la Fase 1.

## Fase 2 — uso real y límites observados (2026-10-22)

La Fase 2 ejecutó el grafo completo con herramientas reales. La configuración de
salida estructurada pasó de `json_schema` (spike) a `function_calling`, con un
fallback propio a JSON textual (`text_json`) porque Groq emitió en algunos casos
una tool call con el nombre del esquema (`researchPlan`) que no estaba en
`request.tools`.

### Cuotas observadas

| Proveedor / servicio | Límite observado | Evidencia |
| :--- | :--- | :--- |
| Groq `openai/gpt-oss-120b` | 8.000 TPM | HTTP 413 con `Requested 9349` en el critic |
| Groq `openai/gpt-oss-120b` | 200.000 TPD | `Used 199038, Requested 5103`; el run se detuvo |
| Gemini `gemini-3.8-flash` | 20 peticiones/día | Cuota agotada; fallback desactivado en los runs finales |
| Tavily | 1.000 llamadas/mes | Contador local en 34; 966 restantes |
| Tavily | Caché por consulta | Los *cache hits* no incrementan el contador |

El TPD de Groq se agotó al intentar repetir la pregunta de RAG. No se hicieron
más llamadas reales después de ese error. Las cifras no se generalizan a otras
cuentas ni a fechas posteriores.

### Qué se corrigió durante la fase

- Las tool calls pendientes al llegar al límite de pasos dejaban el subgrafo sin
  ejecutar la última búsqueda. Ahora el último paso ejecuta su tool y después
  finaliza.
- `max_workers` se usaba para recortar la lista de subpreguntas y perder trabajo.
  Ahora se envían todas con `Send` y la concurrencia se limita con
  `max_concurrency`; ningún worker se descarta.
- Los prompts del analyst, critic y writer recibían fuentes completas y podían
  superar el TPM. Se compactan notas y snippets; el critic recibe solo claims,
  IDs y títulos, sin snippets.
- El tope de salida se subió a 3.000 tokens después de observar un JSON truncado
  en el analista.
- Las citas en formato `【src_…】` no las detectaba el validador. Se normalizan
  antes de validar.

### Cinco ejecuciones reales

| Pregunta | Tokens | Latencia | Búsquedas | Errores |
| :--- | ---: | ---: | ---: | :--- |
| IA agéntica y limitaciones | 33.827 | 838,9 s | 3 | 0 |
| Atención en transformers | 33.222 | 597,2 s | 4 | 0 |
| Evaluación de RAG | 27.339 | 590,6 s | 4 | 1 (analista, recuperado) |
| LoRA frente a fine-tuning | 18.416 | 416,8 s | 3 | 0 |
| Métricas de clasificación de imágenes | 23.749 | 534,6 s | 3 | 0 |

Las trazas curadas están en [`examples/`](./examples/). La latencia incluye las
esperas del limitador TPM, por lo que no debe compararse con la latencia del
spike, que no tenía herramientas ni limitador.

### Conclusión para las siguientes fases

El free tier alcanza para una demo y para validar el flujo, pero no para una
evaluación sistemática: el TPD se agota antes de completar un conjunto amplio de
preguntas. La Fase 4 debe usar el corpus congelado, cachear búsquedas, ejecutar
por lotes con presupuesto explícito y reportar cuántas preguntas quedaron
bloqueadas por cuota. El fallback de Gemini no es una reserva infinita: su cuota
diaria también es limitada.

## Cierre de límites medidos (2026-10-25)

En la sesión de cierre se volvieron a comprobar los endpoints con una petición
mínima. Groq `openai/gpt-oss-120b` y `openai/gpt-oss-20b` respondieron `200` y
declararon `x-ratelimit-limit-tokens: 8000` (TPM). La página oficial de rate
limits confirma para ambos modelos **30 RPM, 1.000 RPD, 8.000 TPM y 200.000
TPD** en el plan gratuito. Gemini respondió `200` en `/models`. Las cabeceras no
incluyen el TPD, así que el valor se toma de la documentación y se contrasta con
el agotamiento observado en la Fase 2; no es una garantía futura.

| Recurso | Límite medido / observado | Uso conocido |
| :--- | :--- | :--- |
| Groq `openai/gpt-oss-120b` | 8.000 TPM; 200.000 TPD | B0/B1/B2 y juez; el TPD puede agotarse |
| Groq `openai/gpt-oss-20b` | 8.000 TPM; 200.000 TPD | B0, researchers y juez |
| Gemini `gemini-3.8-flash` | 20 peticiones/día observadas | Fallback; cuota agotada en sesiones anteriores |
| Tavily | 1.000 llamadas/mes | Contador persistente; no se usa en modo frozen |
| Corpus frozen | 30 documentos, 20 preguntas | No consume cuota de búsqueda |

Las cifras cambian con el proveedor y la cuenta. El cliente respeta `Retry-After`
y aplica backoff, pero la evaluación debe ejecutarse por lotes con `--resume` y
reportar cuántas preguntas quedaron bloqueadas. No se debe prometer una
reproducción completa del benchmark en una sola sesión de free tier.
