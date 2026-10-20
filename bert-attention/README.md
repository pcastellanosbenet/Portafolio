# Interpretabilidad de BERT: atención por capas y cabezas

Este proyecto usa `bert-base-uncased` para resolver tareas de *masked language modeling*
(MLM) y visualizar, capa por capa y cabeza por cabeza, qué tokens reciben atención. El
objetivo no es entrenar otro modelo, sino **abrir la caja negra** y comprobar qué patrones
lingüísticos capturan las 12 capas y las 12 cabezas de BERT.

Es un proyecto de NLP e interpretabilidad con PyTorch y Hugging Face Transformers. Genera
144 mapas de atención por frase (12 capas × 12 cabezas), guarda los pesos originales y
documenta un conjunto curado de mapas para el análisis.

## Resultados

Predicciones para el token `[MASK]` (top-3, probabilidad entre paréntesis):

| Frase | Top-1 | Top-2 | Top-3 |
| :--- | :--- | :--- | :--- |
| `The [MASK] sat on the mat.` | girl (0,069) | man (0,067) | dog (0,057) |
| `The animal did not cross the street because it was too [MASK].` | late (0,120) | fast (0,113) | close (0,099) |
| `I learned a lot from this [MASK] artificial intelligence course.` | particular (0,081) | whole (0,064) | basic (0,039) |

Las probabilidades son bajas porque el MLM tiene muchas continuaciones plausibles; el
interés está en la representación y en la atención, no en obtener una única respuesta.

Hallazgos principales, con pesos de atención **sin normalizar**:

1. **Cabezas de token siguiente.** Las capas 3, cabeza 1 y cabeza 10, aprenden un patrón
   casi determinista: cada token atiende al siguiente. En la frase simple,
   `[MASK] → sat = 0,9996`, `sat → on = 0,9992` y `the → [MASK] = 1,000`.
2. **Correferencia en capas medias y tardías.** En la frase del animal, `it → animal`
   alcanza `0,854` en la capa 4, cabeza 11; `0,803` en la capa 11, cabeza 7; y `0,774` en
   la capa 11, cabeza 9. La capa 3, en cambio, prefiere `it → was = 1,000`: la sintaxis
   local domina antes que la correferencia.
3. **Sumideros de atención (*attention sinks*).** Muchas cabezas tardías concentran la
   atención en `[SEP]`, `[CLS]` o el punto final. La capa 7, cabeza 4, envía
   `[CLS] → [SEP] = 0,959`; la capa 11, cabeza 7, envía `street → . = 0,936`. En la última
   capa, la atención media de `[MASK]` al punto es `0,529` en la frase simple, `0,745` en
   la de correferencia y `0,486` en la del curso.
4. **La máscara usa el contexto local.** En la frase del curso, la capa 8, cabeza 5,
   muestra `[MASK] → this = 0,994`; la capa 11, cabeza 11, muestra
   `[MASK] → course = 0,984`. En la frase del animal, la capa 7, cabeza 12, muestra
   `[MASK] → too = 0,948`.
5. **La atención se concentra con la profundidad.** La entropía media por capa baja de
   `1,59` (capa 1) a `0,99` (capa 8) en la frase simple, y de `2,03` a `1,19` en la de
   correferencia. No es un descenso monótono: algunas capas tardías vuelven a repartir la
   atención.

![Capa 1, cabeza 6: atención temprana y global](../docs/attention/simple_layer01_head06.png)

![Capa 3, cabeza 1: patrón de token siguiente](../docs/attention/simple_layer03_head01.png)

![Capa 7, cabeza 4: atención al separador](../docs/attention/simple_layer07_head04.png)

![Capa 4, cabeza 11: it → animal](../docs/attention/coref_layer04_head11.png)

Las ocho figuras curadas están en [`docs/attention/`](../docs/attention). El resto de
mapas se puede regenerar con `python -m src.mask`; los pesos completos de los mapas
seleccionados están en [`results/analysis.json`](results/analysis.json).

## Cómo funciona la atención

Cada capa de BERT aplica *self-attention* multi-cabeza. Para cada token se calculan tres
proyecciones: **query** (qué busca), **key** (qué ofrece) y **value** (qué información
transmite). La afinidad entre queries y keys se mide con un producto escalar, se escala
por `√d_k` y se normaliza con softmax:

```text
Attention(Q, K, V) = softmax(QKᵀ / √d_k) V
```

Con 12 cabezas, cada una aprende una proyección distinta de 64 dimensiones. La matriz que
se visualiza es la softmax de una cabeza: la fila es el token que consulta (query) y la
columna es el token que recibe atención (key). Cada fila suma 1.

El proyecto usa la implementación **eager** de atención. Las versiones recientes de
Transformers usan SDPA por defecto, que no expone las matrices; sin `eager`,
`output_attentions=True` devuelve `None`.

## Metodología

1. Se tokeniza una frase con exactamente un `[MASK]`.
2. `BertForMaskedLM` devuelve los logits y las 12 matrices de atención.
3. Se selecciona la posición de `[MASK]` y se obtienen las predicciones top-k.
4. Se guarda un mapa por capa y cabeza. Para que sean legibles, cada fila se normaliza
   dividiéndola por su máximo; el JSON conserva los pesos originales.
5. Se eligen ocho mapas representativos tras inspeccionar los 144 de cada frase. La
   selección es cualitativa y está documentada en [`analysis.md`](analysis.md).

## Reproducir

```bash
cd bert-attention
uv venv --python 3.12
uv pip install -r requirements-dev.txt

# Una frase concreta: genera 144 mapas
uv run python -m src.mask "The [MASK] sat on the mat." --output results/heatmaps

# Análisis reproducible: 3 frases, 8 mapas curados y results/analysis.json
uv run python -m scripts.analyze_attention

# Tests y lint
uv run pytest -q
uv run ruff check src tests scripts
```

La primera ejecución descarga `bert-base-uncased` (~440 MB) desde Hugging Face. El modelo
se guarda en la caché local; no se versiona.

## Estructura

```text
bert-attention/
├── src/mask.py              # tokenización, predicción, mapas de atención, CLI
├── scripts/analyze_attention.py  # análisis de las 3 frases y mapas curados
├── tests/test_mask.py       # tests de máscara, color, formas y visualización
├── results/analysis.json    # pesos, predicciones, entropía y pares principales
├── analysis.md              # interpretación detallada por capa y cabeza
└── assets/fonts/            # fuente local heredada del ejercicio original
../docs/attention/          # 8 mapas curados usados en los README
```

## Limitaciones

- **La atención no es una explicación causal.** Un peso alto indica que una cabeza consulta
  un token, no que ese token sea la causa de la predicción. Para atribución causal harían
  falta ablaciones, *attention rollout* o métodos como integrated gradients.
- **Selección post hoc.** Los ocho mapas se eligieron después de mirar los 144 de cada
  frase. Es un análisis exploratorio, no una prueba estadística.
- **Solo tres frases.** Los patrones son ilustrativos; no generalizan por sí solos a todo
  el lenguaje.
- **BERT-base-uncased.** Es un modelo de 2018, en inglés y sin instrucciones. No representa
  el estado del arte actual, pero es un baseline interpretable y reproducible.
- **MLM, no generación.** `[MASK]` es una tarea artificial; las probabilidades bajas son
  esperables y no deben leerse como calibración perfecta.
- **Normalización por fila.** Las figuras exageran la relación dominante de cada fila. Los
  pesos originales están en `results/analysis.json` para no perder la escala.
- **Sin fine-tuning ni ablación de cabezas.** No se afirma qué cabeza es necesaria para la
  tarea; solo qué patrones aparecen.

## Referencias

- Vaswani et al. (2017), *Attention Is All You Need*.
- Devlin et al. (2019), *BERT: Pre-training of Deep Bidirectional Transformers*.
- Clark et al. (2019), *What Does BERT Look At? An Analysis of BERT's Attention*.
- Jain & Wallace (2019), *Attention is not Explanation*.
- Abnar & Zuidema (2020), *Quantifying Attention Flow in Transformers*.
