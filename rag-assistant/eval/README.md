# Evaluación de recuperación

`eval/questions.jsonl` es el conjunto de preguntas de referencia. Cada línea tiene
este formato:

```json
{
  "id": "q001",
  "question": "What is DPT 1.001 and how is it encoded?",
  "language": "en",
  "type": "definition",
  "relevant_doc_ids": ["03-volume-3-system-specifications-03-07-02-datapoint-types-v02-02-01-as"],
  "relevant_pages": [21],
  "reference_answer": ""
}
```

Campos:

| Campo | Obligatorio | Uso |
| :--- | :--- | :--- |
| `id` | Sí | Identificador estable |
| `question` | Sí | Pregunta evaluada |
| `language` | No | `en` o `es`; se usa para agrupar métricas |
| `type` | No | Tipo de pregunta; se usa para agrupar métricas |
| `relevant_doc_ids` | Sí | Documentos que contienen la evidencia |
| `relevant_pages` | No | Páginas concretas, si se conocen |
| `reference_answer` | No | Respuesta de referencia; no se puntúa todavía |

El conjunto actual es una **semilla de 20 preguntas**. No es suficiente para
afirmar que el sistema es robusto. Para una evaluación seria conviene ampliarlo a
50–80 preguntas, con varias preguntas por volumen, negativas y preguntas que
requieran combinar dos documentos.

## Métricas

La evaluación actual mide recuperación a nivel de documento:

- **Recall@k**: fracción de documentos relevantes recuperados entre los primeros
  `k`.
- **Hit@k**: 1 si al menos un documento relevante aparece en el top `k`.
- **MRR**: inverso del rango del primer documento relevante.
- **nDCG@k**: ganancia descontada con relevancia binaria.
- **Page hit@k**: solo se calcula si la pregunta declara `relevant_pages`.

No se publican métricas de corrección factual ni de citas generadas. Eso requiere
un conjunto de respuestas de referencia y, preferiblemente, una evaluación humana.
El README del proyecto no debe presentar estas métricas como calidad de respuesta.

## Ejecutar

Con el índice ya construido:

```bash
cd rag-assistant
python -m src.evaluate \
  --questions eval/questions.jsonl \
  --top-k 10 \
  --output eval/results/retrieval.json
```

Para comparar sin reranker:

```bash
python -m src.evaluate \
  --questions eval/questions.jsonl \
  --top-k 10 \
  --no-reranker \
  --output eval/results/retrieval-no-reranker.json
```

Los resultados incluyen el detalle por pregunta, por tipo y por idioma. El archivo
`eval/results/` se puede versionar; los PDFs y el índice no.

## Resultados actuales

Subconjunto de 25 PDFs / 2.111 páginas, 20 preguntas y `top_k=10`:

| Configuración | Recall@10 | Hit@10 | MRR | nDCG@10 |
| :--- | ---: | ---: | ---: | ---: |
| Sin reranker | 0,8917 | 0,95 | 0,7417 | 0,7553 |
| Con reranker | 0,9083 | 0,95 | 0,8500 | 0,8427 |

El detalle está en `results/retrieval-no-reranker.json` y `results/retrieval.json`.
El conjunto es pequeño y el top-10 cubre el 40% de los 25 documentos: estas cifras
no son comparables con una evaluación sobre los 178 PDFs completos.

## Cómo ampliar el conjunto

1. Elegir un documento y una sección concreta.
2. Formular una pregunta que un ingeniero haría en un proyecto real.
3. Verificar que la respuesta está realmente en ese documento.
4. Añadir una pregunta negativa (“¿Qué dice el estándar sobre X?”) solo si X no
   aparece, para comprobar la abstención.
5. Ejecutar la evaluación y revisar los fallos de recuperación antes de tocar el
   ranking.
