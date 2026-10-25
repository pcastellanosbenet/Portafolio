# Resultados de evaluación

| Run | Estado | Contenido |
| :--- | :--- | :--- |
| `smoke-20261023b` | Completado | 2 preguntas (F01, U01) × B0/B1/B2 = 6 ejecuciones |
| `eval-full-20261024` | Parcial | B0 completo sobre 20 preguntas; B1 parcial 11/20; B2 pendiente por el TPD de 200.000 tokens/modelo/día |

El smoke, el lote B0 y el lote B1 usan el corpus congelado y un juez Groq. **No
hay una tabla completa B0/B1/B2 de 20 preguntas** ni las 3 repeticiones de
robustez en este repositorio: B2 no cabe en la misma sesión por el límite de
200.000 TPD por modelo. La metodología, los resultados y las limitaciones están
en [`../../docs/evaluation.md`](../../docs/evaluation.md).

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
