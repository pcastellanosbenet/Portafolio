# Evaluación de enrutado de herramientas

Un gateway con muchas herramientas necesita medir si el modelo elige la correcta. La
evaluación no debe confundir "el modelo llamó a una tool" con "la tarea se completó".

## Tareas y gold

Cada tarea tiene una consulta en lenguaje natural, el servidor y la herramienta esperados,
los argumentos mínimos y un predicado de éxito determinista sobre fixtures. La corrección
comprueba tres cosas: selección, validez de argumentos y resultado. No se usa un juez LLM.

## Configuraciones

El modo estático expone todas las herramientas. El modo meta expone `find_tools` e
`invoke_tool`. El modo híbrido selecciona las mejores candidatas para la consulta y añade
un fallback de búsqueda. Comparar los tres permite medir el trade-off entre precisión,
tokens de definiciones y latencia.

## Métricas

Las métricas principales son precisión@1, validez de argumentos, éxito de tarea,
abstención correcta en tareas negativas, tokens de definiciones, tokens totales y latencia
p50/p95. También se registran los aciertos de caché y los fallos por upstream y por tool.

## Reproducibilidad

La temperatura es cero, el modelo y la versión quedan registrados y los resultados crudos
se guardan con fecha. El runner es reanudable por lotes para no agotar la cuota del
proveedor. Si un run queda incompleto, se publica como parcial y se explica el motivo.

## Lectura honesta

Un modo puede ganar en tokens y perder precisión. El README debe mostrar ambos lados y
analizar los fallos, no solo la media. Las tareas negativas son importantes: un router que
siempre llama a una herramienta falla aunque acierte en las positivas.
