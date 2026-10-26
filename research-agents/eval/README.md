# Datos de evaluación

Este directorio contiene el corpus congelado y el conjunto de preguntas de la
Fase 4. La metodología, las métricas y los resultados del smoke, de B0/20 y de
B1/20 están en [`../docs/evaluation.md`](../docs/evaluation.md).

## Archivos

| Ruta | Descripción |
| :--- | :--- |
| `frozen/corpus.json` | 30 documentos de Wikipedia con licencia, URL, fecha, atribución y SHA-256 |
| `questions.json` | 20 preguntas en cuatro categorías |
| `results/smoke-20261023b/` | Smoke real de 6 ejecuciones con B0/B1/B2 |
| `results/eval-full-20261024/` | B0 y B1 completos sobre 20 preguntas; B2 pendiente |

## Corpus

Cada documento tiene esta forma:

```json
{
  "doc_id": "doc_7c111d5b0d36",
  "source_id": "src_7c111d5b0d36",
  "title": "Aprendizaje automático",
  "url": "https://es.wikipedia.org/wiki/Aprendizaje_autom%C3%A1tico",
  "kind": "wikipedia",
  "language": "es",
  "license": "CC BY-SA 4.0",
  "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
  "attribution": "Wikipedia contributors",
  "retrieved_at": "2026-10-23",
  "sha256": "…",
  "aliases": ["machine learning", "ML"],
  "content": "…"
}
```

Reglas de validación:

- `url` debe ser canónica.
- `source_id` se deriva de la URL; no se elige a mano.
- `sha256` debe coincidir con el contenido.
- `doc_id`, `source_id` y `url` deben ser únicos.
- La licencia debe estar declarada.

Para añadir un documento, actualiza también `questions.json` si el documento es
una fuente esperada. El corpus se valida antes de ejecutar cualquier modelo; un
hash incorrecto detiene la evaluación.

## Preguntas

Cada pregunta declara:

```json
{
  "id": "F01",
  "category": "factual",
  "question": "…",
  "answerable": true,
  "expected_facts": [
    {"id": "F01-1", "text": "…", "any_of": ["…", "…"]}
  ],
  "expected_source_urls": ["https://es.wikipedia.org/wiki/…"],
  "rubric": "…"
}
```

Las preguntas `unanswerable` no declaran hechos ni fuentes esperadas: la respuesta
correcta es abstenerse. Las cuatro categorías (`factual`, `comparison`,
`multi_hop`, `unanswerable`) son obligatorias y cada una debe tener al menos una
pregunta.

## Resultados

`records.jsonl` guarda una línea JSON por ejecución con la respuesta cruda, claims,
fuentes, uso, traza, juicio y métricas. `summary.json`, `summary.md` y
`quality_vs_tokens.svg` se generan a partir de esos registros. `run_meta.json`
guarda los hashes del corpus y de las preguntas y la configuración efectiva.

Los resultados publicados incluyen el smoke, el lote B0/20 y el lote B1/20; no se
presentan como la evaluación completa B0/B1/B2. Para reproducirlos, consulta
los comandos de `docs/evaluation.md`.

## Licencia

Los textos de Wikipedia están bajo **CC BY-SA 4.0**. Cada documento incluye su
atribución y URL original. El resto del código y de los datos generados por el
proyecto se publica bajo la licencia MIT del repositorio.
