# Trazas reales curadas

Cinco ejecuciones reales del equipo de investigación, seleccionadas para la
documentación del proyecto. No son simulaciones ni respuestas escritas a mano.

| Archivo | Pregunta | Confianza | Claims | Fuentes | Búsquedas | Tokens | Latencia | Errores |
| :--- | :--- | :---: | ---: | ---: | ---: | ---: | ---: | :--- |
| [`01-agentic-ai.json`](./01-agentic-ai.json) | IA agéntica y sus limitaciones | media | 4 | 15 | 3 | 33.827 | 838,9 s | 0 |
| [`02-attention-transformers.json`](./02-attention-transformers.json) | Atención en transformers | alta | 4 | 17 | 4 | 33.222 | 597,2 s | 0 |
| [`03-rag-evaluation.json`](./03-rag-evaluation.json) | Evaluación de sistemas RAG | media | 4 | 19 | 4 | 27.339 | 590,6 s | 1 |
| [`04-lora-vs-finetuning.json`](./04-lora-vs-finetuning.json) | LoRA frente a fine-tuning completo | alta | 4 | 10 | 3 | 18.416 | 416,8 s | 0 |
| [`05-image-classification-metrics.json`](./05-image-classification-metrics.json) | Métricas de clasificación de imágenes | media | 3 | 15 | 3 | 23.749 | 534,6 s | 0 |

## Qué contiene cada archivo

```json
{
  "run_id": "…",
  "question": "…",
  "run_config": {
    "max_workers": 2,
    "max_tool_steps": 1,
    "max_rounds": 1,
    "llm_fallback_provider": null,
    "llm_max_output_tokens": 2500
  },
  "report": {
    "title": "…",
    "answer_markdown": "…",
    "claims": [],
    "sources": [],
    "confidence": "medium",
    "limitations": [],
    "usage": {}
  },
  "usage": {},
  "errors": [],
  "trace": []
}
```

- `report`: salida del writer y las fuentes que respaldan los claims.
- `usage`: llamadas LLM, tokens, búsquedas, latencia y modelos usados.
- `errors`: errores recuperados durante el run; no se ocultan.
- `trace`: eventos del grafo (plan, dispatch, nodos y cierre).

## Curación aplicada

Para poder publicar las trazas sin arrastrar contenido innecesario:

1. Se recortaron los snippets de las fuentes a 280 caracteres.
2. Se normalizaron las referencias `【src_…】`, `[[src_…]]` y `[^src_…]` al
   formato `[src_…]`.
3. Se eliminaron metadatos internos de las fuentes.
4. Se conservaron sin cambios las preguntas, URLs, claims, métricas, límites y
   errores.

No hay claves de API, rutas locales ni páginas completas en estos archivos.

## La traza de RAG

`03-rag-evaluation.json` es una ejecución real que terminó con un error recuperado:
el analista devolvió un JSON truncado y el nodo usó el análisis determinista de
respaldo. Aun así, el informe final tiene 4 claims, 19 fuentes y citas válidas. El
error se conserva en `errors` y en la traza. A partir de este caso se aumentó el
tope de salida y se compactaron las entradas del analyst, el critic y el writer.

No se repitió esta pregunta con una traza limpia porque la cuota diaria de Groq se
agotó durante la misma sesión.

## Reproducir

Los archivos son artefactos de lectura; no se usan como entrada del CLI. Para
generar una traza nueva:

```bash
cd research-agents
RESEARCH_MAX_ROUNDS=1 RESEARCH_MAX_TOOL_STEPS=1 RESEARCH_MAX_WORKERS=2 \
  .venv/bin/python -m scripts.run_research "Tu pregunta" --no-fallback
```

La traza se guarda en `artifacts/traces/` (ignorado por Git). Consulta el
[`README`](../README.md) para la configuración y los límites.
