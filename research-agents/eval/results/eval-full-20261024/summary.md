# Evaluación eval-full-20261024

Generado: 2026-10-29T09:45:13.384345+00:00

Registros: 60

Este resumen agrega ejecuciones reales; la metodología, la revisión manual y las limitaciones están en `docs/evaluation.md`.

## Resultados globales

| Sistema | Éxito tarea | Score juez | Cobertura | Precisión citas | Validez citas | Recall fuentes | Soporte claims | Abstención | Llamadas | Tokens | Latencia p50 | Latencia p95 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| B0 · agente único (20) | 0.25 | 1.20 | 0.56 | 0.83 | 1 | 0.89 | 1 | 1 | 2 | 2143 | 58.5 | 59.8 |
| B1 · pipeline fijo (20) | 0.55 | 1.55 | 0.56 | 0.74 | 1 | 0.91 | 1 | 1 | 9.10 | 11972.35 | 357.3 | 360.9 |
| B2 · equipo completo (20) | 0.45 | 1.45 | 0.60 | 0.75 | 1 | 0.83 | 1 | 1 | 10.95 | 18587.30 | 424.8 | 538.6 |

## Éxito de tarea por categoría

| Categoría | B0 · agente único | B1 · pipeline fijo | B2 · equipo completo |
| :--- | :---: | :---: | :---: |
| factual | 0.20 | 0.20 | 0.20 |
| comparison | 0.20 | 0.40 | 0.60 |
| multi_hop | 0 | 0.60 | 0.20 |
| unanswerable | 0.60 | 1 | 0.80 |

El número entre paréntesis de la tabla global es el total de registros por sistema; las categorías usan solo sus propios registros, así que un n distinto no es comparable.

## Calidad frente a coste

El gráfico usa el éxito de tarea medio y los tokens medios por ejecución.

![Calidad frente a tokens](quality_vs_tokens.svg)
