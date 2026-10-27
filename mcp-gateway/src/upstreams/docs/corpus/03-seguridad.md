# Seguridad en servidores MCP

Las herramientas MCP reciben datos de fuentes no confiables. Una descripción puede
contener instrucciones maliciosas y una salida puede intentar redirigir al modelo. El
gateway debe tratar definiciones y resultados como datos, nunca como instrucciones.

## Tool poisoning y shadowing

El hash-pinning detecta cambios en la definición de una herramienta. Si una descripción
cambia tras la aprobación, el gateway puede ponerla en cuarentena hasta que un humano la
revise. El namespacing evita que un servidor malicioso suplante a otro publicando el
mismo nombre de tool.

## SSRF

Una herramienta que descarga URLs debe validar el esquema y resolver el hostname. Solo se
permiten `http` y `https`; se bloquean loopback, rangos privados, link-local, multicast y
la dirección de metadatos `169.254.169.254`. Las redirecciones se validan de nuevo y el
tiempo y el tamaño de respuesta están acotados.

## Prompt injection en salidas

El contenido de una herramienta se delimita y se marca como no confiable. El gateway no
ejecuta instrucciones encontradas en el texto y el host debe separar claramente datos de
instrucciones del sistema. Para operaciones sensibles, la decisión no puede depender solo
del modelo.

## Least privilege

La allowlist limita qué herramientas puede invocar un cliente. Los niveles de riesgo
`read`, `write` y `destructive` permiten exigir aprobación solo en las acciones que
modifican estado. `restart_service` y `delete_namespace` son ejemplos destructivos;
`create_incident` es una escritura reversible.

## Auditoría

Cada llamada registra un `trace_id`, el servidor, la herramienta, el hash de argumentos,
la latencia y el estado. Nunca se guardan tokens ni argumentos completos con secretos.
La auditoría permite reconstruir una decisión y detectar patrones de abuso.
