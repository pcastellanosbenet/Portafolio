# Runbook de operaciones sintéticas

Este runbook describe el estado de laboratorio que expone `ops-mcp`. Los servicios son
sintéticos y se reinician al arrancar el servidor; no representan infraestructura real.

## Servicios

El entorno tiene cinco servicios: `api`, `worker`, `scheduler`, `db` y `cache`. Cada uno
reporta estado, réplicas, versión, latencia p95 y tasa de error. `api` y `worker` son los
más sensibles a latencia; `db` concentra los incidentes de capacidad.

## Incidentes

Los incidentes se identifican con `INC-001` y tienen severidad `sev1`, `sev2` o `sev3`.
El flujo recomendado es: listar incidentes abiertos, leer el detalle, revisar métricas y
logs del servicio afectado, y solo después proponer una acción. Cambiar el estado de un
incidente es una escritura reversible; reiniciar un servicio o borrar un namespace es
destructivo y requiere aprobación.

## Métricas y logs

`query_metrics` devuelve una serie corta y determinista por servicio. `search_logs`
filtra líneas sintéticas por texto y devuelve las más recientes. Los logs incluyen
marcadores como `timeout`, `connection refused` y `OOMKilled` para practicar diagnóstico.

## Despliegues

`deploy_history` muestra las últimas versiones desplegadas y su resultado. Un despliegue
fallido suele ir seguido de un aumento de errores; el runbook recomienda comparar la
versión actual con la anterior antes de reiniciar.

## Acciones destructivas

`restart_service` incrementa la generación del servicio y lo deja en estado `restarting`.
`delete_namespace` marca un namespace como eliminado. Ambas acciones exigen aprobación
humana y quedan registradas en la auditoría con su `trace_id`.
