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

- **Tavily:** 1.000 llamadas a la API al mes. Se implementará un contador
  persistente y se cachearán las búsquedas. El CI no hará llamadas reales.
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
registrada en `PLANS.md` y se continuó con la Fase 1.
