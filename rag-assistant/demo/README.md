# Demo con corpus sintético

Este directorio permite probar el pipeline RAG completo **sin una copia del
estándar KNX**. El corpus es sintético y describe un protocolo ficticio llamado
**NexaBus**. No es el estándar KNX, no reproduce su contenido y no sirve para
afirmar nada sobre KNX.

El objetivo es que alguien que haga fork pueda ejecutar la ingesta, la
recuperación, la API y la evaluación sin redistribuir material licenciado.

## Contenido

| Archivo | Uso |
| :--- | :--- |
| `documents.json` | Definición legible de los 6 documentos sintéticos |
| `questions.jsonl` | 12 preguntas bilingües con respuesta de referencia |
| `results/retrieval.json` | Resultado real de evaluar el corpus de demo |
| `corpus/` | PDFs generados localmente; está ignorado por Git |

Los documentos cubren direcciones de grupo, datapoint types, propiedades,
sesiones seguras, medios y couplers, y certificación. Incluyen tablas con
identificadores `DPT` y `PID` ficticios; el lookup exacto de DPT se ejercita con
la tabla de datapoint types.

## Ejecutar la demo

Desde `rag-assistant/`:

```bash
python scripts/build_demo_corpus.py --clean

python -m src.ingest \
  --corpus demo/corpus \
  --artifacts artifacts-demo \
  --rebuild

python -m src.evaluate \
  --questions demo/questions.jsonl \
  --artifacts artifacts-demo \
  --top-k 10 \
  --no-reranker \
  --output demo/results/retrieval.json
```

La ingesta usa `multilingual-e5-small`, un modelo público, y guarda sus artefactos
en `artifacts-demo/`. `--artifacts artifacts-demo` también desplaza el índice
Qdrant a `artifacts-demo/qdrant`, de modo que la demo no toca el índice real de
`artifacts/qdrant`.

Para abrir la API con el índice de demo:

```bash
RAG_ARTIFACTS_DIR=artifacts-demo uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Y consultar:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is DPT 1.001 and how is it encoded?","top_k":3}' \
  | python -m json.tool
```

Si Ollama no está disponible, la API devuelve un extracto citado con
`used_llm=false`. Para generar respuestas con el modelo local, sigue las
instrucciones del README principal.

## Resultado de la demo

Última ejecución con 6 PDFs, 6 páginas, 12 chunks y `top_k=10`, sin reranker:

| Métrica | Valor |
| :--- | ---: |
| Preguntas | 12 |
| Recall@10 | 1,0000 |
| Hit@10 | 1,0000 |
| MRR | 0,9583 |
| nDCG@10 | 0,9692 |
| Page hit@10 | 1,0000 |

El detalle está en [`results/retrieval.json`](results/retrieval.json). Las cifras
son altas porque el corpus es diminuto y cada documento cubre un tema muy
distinto; no son una evaluación realista de recuperación.

**No compares estas métricas con las del corpus KNX.** Las métricas KNX están en
el README principal y en `eval/results/`, y solo se pueden reproducir con una
copia licenciada del estándar validada con `scripts/check_corpus.py`.

## Limpieza

`corpus/` y `artifacts-demo/` están ignorados. Se pueden borrar sin afectar al
repositorio:

```bash
rm -rf demo/corpus artifacts-demo
```
