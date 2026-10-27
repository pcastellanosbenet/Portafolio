# Arquitectura de un gateway MCP

Un gateway MCP es a la vez servidor para el host y cliente para varios upstreams. El host
habla con un único endpoint; el gateway descubre herramientas, las renombra y decide
cuáles expone en cada momento.

## Catálogo y namespacing

Cada herramienta se registra con el nombre canónico `servidor__herramienta`. El prefijo
evita colisiones cuando dos servidores publican una tool con el mismo nombre, por ejemplo
`search`. El catálogo guarda el hash de la definición para detectar cambios y exigir una
nueva aprobación si la descripción o el esquema cambian.

El orden de `tools/list` es determinista. Esto reduce ruido en el prompt, permite cachear
la lista y hace que las evaluaciones sean reproducibles. Un cambio de catálogo invalida
la caché y se anuncia con `tools/list_changed`.

## Descubrimiento y degradación

Al arrancar, el gateway conecta con cada upstream y llama a `tools/list`. Si un upstream
falla, el gateway sigue funcionando con los demás y marca el estado como `degraded`. El
endpoint `/health` muestra qué servidores están conectados y cuántas herramientas aporta
cada uno.

Las llamadas se ejecutan con timeout, reintentos limitados y un tope de tamaño de salida.
Un error de upstream se convierte en un resultado de herramienta con `isError: true`, no
en una excepción opaca, para que el modelo pueda reaccionar.

## Divulgación progresiva

Exponer 25 herramientas en cada prompt cuesta tokens. Un gateway puede ofrecer el
catálogo completo, meta-herramientas (`find_tools`, `invoke_tool`) o una selección
híbrida de las mejores candidatas para la consulta. El modo híbrido busca un equilibrio:
reduce definiciones sin perder precisión de selección.

## Transportes

Streamable HTTP es adecuado para servidores compartidos y para Docker. stdio es útil para
procesos locales que el host lanza bajo demanda. El gateway usa HTTP hacia `docs-mcp` y
`ops-mcp`, y stdio hacia `research-mcp`, que puede ejecutarse en el mismo contenedor.
