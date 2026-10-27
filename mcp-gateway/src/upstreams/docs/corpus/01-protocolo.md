# Protocolo MCP 2026-07-28

La revisión `2026-07-28` de Model Context Protocol elimina el handshake clásico de
`initialize` en la era moderna. El cliente descubre el servidor con `server/discover`,
que devuelve las versiones soportadas, las capacidades y la identidad del servidor.

## Peticiones sin sesión

Cada petición HTTP incluye la cabecera `MCP-Protocol-Version` y un bloque `_meta` con la
versión negociada, la información del cliente y sus capacidades. El servidor no emite
`Mcp-Session-Id`, así que puede atender peticiones independientes sin estado de conexión.

Las cabeceras `Mcp-Method` y `Mcp-Name` permiten validar que el cuerpo JSON-RPC coincide
con la ruta declarada. Si `Mcp-Name` no coincide con el nombre de la herramienta, el
servidor responde con el error `-32020`. Una versión no soportada devuelve `-32022` con
la lista de versiones aceptadas.

## Aprobaciones con MRTR

Las operaciones destructivas pueden requerir aprobación humana. El patrón MRTR
(Machine-Readable Tool Result) devuelve un resultado `input_required` con una petición
de elicitación. El cliente muestra la pregunta, recoge la respuesta y reintenta la
llamada con `inputResponses` y `requestState`. El servidor valida la respuesta antes de
ejecutar la acción.

## Suscripciones

`subscriptions/listen` abre un stream de cambios. El filtro declara qué eventos interesan
(`tools_list_changed`, `prompts_list_changed`, `resources_list_changed`). El servidor
confirma el subconjunto que puede atender y publica eventos cuando cambia el catálogo.
No hay replay: tras una desconexión, el cliente debe volver a suscribirse y refrescar.

## Cache hints

`tools/list` puede incluir `ttlMs` y `cacheScope`. Un `ttlMs` positivo indica frescura y
`cacheScope: public` permite compartir la respuesta entre contextos de autorización. El
catálogo del gateway es determinista para que estas pistas sean útiles.
