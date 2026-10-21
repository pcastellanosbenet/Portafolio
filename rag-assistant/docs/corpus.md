# Corpus y reproducibilidad

Este proyecto se construyó sobre **The KNX Standard v3.0.0**. El estándar está
protegido por derechos de autor y no se redistribuye con el repositorio. Por eso
la reproducibilidad se plantea en varios niveles: el código y los tests se pueden
ejecutar con un `git clone`, pero las métricas del corpus KNX requieren una copia
local obtenida legalmente.

## Qué contiene el repositorio

Se versionan:

- El código de ingesta, recuperación, evaluación, API y despliegue.
- Los tests, que no necesitan el corpus ni modelos externos.
- Las preguntas de evaluación y los resultados agregados.
- Los metadatos de los PDFs evaluados, sin texto extraído.
- Un corpus sintético de demostración para probar el flujo completo.

No se versionan:

- Los PDFs del estándar KNX.
- `chunks.jsonl`, `entities.jsonl` o `manifest.jsonl` generados a partir del corpus.
- Los embeddings.
- El índice de Qdrant.
- Cualquier otro artefacto derivado que contenga texto del estándar.

## Edición y alcance

| Dato | Valor |
| :--- | ---: |
| Edición | The KNX Standard v3.0.0 |
| PDFs del corpus local | 178 |
| Páginas del corpus local | 10.908 |
| PDFs usados en la evaluación | 25 |
| Páginas de esos 25 PDFs | 2.111 |
| Preguntas de evaluación | 20 |

Los 25 PDFs evaluados son los referenciados por las preguntas de
[`eval/questions.jsonl`](../eval/questions.jsonl). No son una muestra aleatoria:
se eligieron para cubrir glosario, interworking, datapoint types, seguridad,
perfiles, certificación, application notes y varios medios de comunicación.

El corpus completo no se indexó por coste de CPU. Las métricas del README
corresponden al subconjunto de 25 PDFs y no deben presentarse como resultados
sobre los 178 PDFs.

## Cómo obtener una copia legal

La copia debe obtenerse a través de los canales oficiales de **KNX Association**
y respetar su licencia. Este repositorio no incluye enlaces a espejos no oficiales
ni un script para descargar el estándar.

Una vez disponibles los PDFs, apunta `KNX_CORPUS_DIR` al directorio que contiene
las carpetas de volúmenes:

```text
The KNX Standard v3.0.0/
├── 03 Volume 3 System Specifications/
├── 04 Volume 4 Hardware Requirements/
├── 05 Volume 5 Certification Manual/
├── ...
└── Application Notes/
```

Las rutas del manifiesto son relativas a ese directorio. No se guardan rutas
absolutas ni nombres de usuario.

## Validar la copia local

El manifiesto [`corpus_manifest.json`](corpus_manifest.json) contiene los
metadatos de los 25 PDFs evaluados: ruta relativa, título, volumen, número de
documento, versión, estado, páginas y SHA-256. No contiene texto.

```bash
cd rag-assistant
python -m scripts.check_corpus --corpus "$KNX_CORPUS_DIR"
```

El comando comprueba:

- que los 25 archivos existen en las rutas esperadas;
- que el número de páginas coincide;
- que el `doc_id` calculado coincide;
- que el SHA-256 coincide, salvo que se use `--no-hash`.

Opciones útiles:

```bash
# Si los PDFs se volvieron a guardar y cambió el hash pero no el contenido
python -m scripts.check_corpus --corpus "$KNX_CORPUS_DIR" --no-hash

# Listar también PDFs que no están en el manifiesto
python -m scripts.check_corpus --corpus "$KNX_CORPUS_DIR" --check-extra

# Salida legible por máquina
python -m scripts.check_corpus --corpus "$KNX_CORPUS_DIR" --json
```

Para auditar el corpus completo, sin compararlo con los 25 documentos evaluados:

```bash
python -m scripts.inspect_corpus --corpus "$KNX_CORPUS_DIR" \
  --output /tmp/knx-audit.json
```

Si el validador encuentra diferencias, comprueba primero la edición y la versión
de cada documento. Un PDF re-guardado puede cambiar su SHA-256 aunque el
contenido visible sea equivalente; en ese caso usa `--no-hash` y revisa páginas y
`doc_id`.

## Niveles de reproducibilidad

| Nivel | Qué se puede reproducir | Requisito |
| :--- | :--- | :--- |
| Código y tests | `pytest`, `ruff` y la estructura del pipeline | Python 3.12 y dependencias |
| Demo | Ingesta, recuperación, API y evaluación sobre el corpus sintético | El repositorio y modelos públicos |
| Pipeline propio | Ingesta de otros PDFs y consultas con citas | PDFs de entrada |
| Métricas KNX | Las cifras del README y los archivos de `eval/results/` | Copia licenciada de la edición exacta |
| Inspección | Preguntas, qrels, resultados y análisis de errores ya publicados | El repositorio |

La reproducibilidad de las métricas KNX es **condicionada**: no se promete que un
`git clone` sin corpus produzca los mismos números. Se promete que el código, la
metodología y los comandos están documentados, y que una copia legal puede
validarse antes de ejecutar la ingesta.

## Corpus de demostración

Para que un fork pueda ejecutar el flujo completo sin una licencia del estándar,
el repositorio incluye un corpus **sintético** en [`demo/documents.json`](../demo/documents.json).
Sus documentos describen un protocolo ficticio llamado NexaBus, se generan como
PDFs con `scripts/build_demo_corpus.py` y se indexan en `artifacts-demo/`.

```bash
cd rag-assistant
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

Las métricas de demo sirven como **smoke test** del pipeline. No son métricas
KNX, no son comparables con las del README y no demuestran conocimiento del
estándar. La separación es deliberada: el corpus de demo es público y el corpus
KNX sigue siendo local y licenciado.
