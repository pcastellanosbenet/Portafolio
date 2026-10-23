# Resultados de evaluación

| Run | Estado | Contenido |
| :--- | :--- | :--- |
| `smoke-20261023b` | Completado | 2 preguntas (F01, U01) × B0/B1/B2 = 6 ejecuciones |

El smoke usa el corpus congelado y un juez Groq. La evaluación completa de las 20
preguntas y las 3 repeticiones de robustez **no se ha ejecutado**; no hay una tabla
de 20 preguntas en este repositorio. La metodología, los resultados y las
limitaciones están en [`../../docs/evaluation.md`](../../docs/evaluation.md).

Cada directorio de run contiene:

- `records.jsonl`: una línea por ejecución con respuesta, claims, fuentes, uso,
  traza, juicio y métricas.
- `summary.json`: agregados por sistema y categoría.
- `summary.md`: tabla legible y enlace al gráfico.
- `quality_vs_tokens.svg`: calidad frente a coste.
- `run_meta.json`: hashes del corpus y preguntas, y configuración efectiva.

No se incluyen claves, `.env` ni respuestas de proveedores sin procesar. Los
registros sí contienen el texto de las respuestas y fragmentos de las fuentes del
corpus, que se distribuye bajo CC BY-SA 4.0.
