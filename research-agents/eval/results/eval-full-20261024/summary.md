# Evaluación eval-full-20261024

Generado: 2026-10-24T07:35:07.615210+00:00

Registros: 20

Este resumen agrega ejecuciones reales; la metodología, la revisión manual y las limitaciones están en `docs/evaluation.md`.

## Resultados globales

| Sistema | Éxito tarea | Score juez | Cobertura | Precisión citas | Validez citas | Recall fuentes | Soporte claims | Abstención | Llamadas | Tokens | Latencia p50 | Latencia p95 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| B0 · agente único | 0.25 | 1.20 | 0.56 | 0.83 | 1 | 0.89 | 1 | 1 | 2 | 2143 | 58.5 | 59.8 |

## Éxito de tarea por categoría

| Categoría | B0 · agente único |
| :--- | :---: |
| factual | 0.20 |
| comparison | 0.20 |
| multi_hop | 0 |
| unanswerable | 0.60 |

## Calidad frente a coste

El gráfico usa el éxito de tarea medio y los tokens medios por ejecución.

![Calidad frente a tokens](quality_vs_tokens.svg)
