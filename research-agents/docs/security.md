# Seguridad y límites de confianza

> Documento de la demo local de `research-agents`. Describe defensas
> implementadas, riesgos residuales y lo que **no** está resuelto. No es una
> auditoría de producción ni una garantía de seguridad.

## 1. Modelo de amenazas

La demo asume que el operador controla el proceso y el `.env`, pero no confía en:

- el contenido de páginas web y resultados de búsqueda;
- las respuestas de los proveedores LLM;
- las URLs que el modelo decide visitar;
- los clientes que pueden alcanzar el puerto local;
- los artefactos persistidos (checkpoints, caché, trazas).

Los activos a proteger son las claves de API, la cuota de los proveedores, la
integridad de los informes, la disponibilidad del proceso y los datos que se
persisten en disco.

## 2. Secretos

### Implementado

- `Settings` define `groq_api_key`, `gemini_api_key` y `tavily_api_key` como
  `SecretStr` (`src/config.py`).
- `.env` está en `.gitignore`; `.env.example` solo contiene valores vacíos.
- El `Dockerfile` no copia `.env`; `docker-compose.yml` lo inyecta en runtime con
  `env_file`, y `.dockerignore` lo excluye de la imagen.
- `has_api_key_for()` devuelve un booleano; `api_key_for()` nombra la variable de
  entorno, nunca su valor.
- `/health` solo publica `api_key_configured` y
  `fallback_api_key_configured`.
- La API redacta los secretos configurados y patrones `gsk_`, `sk-` y `AIza` en
  errores y eventos de traza (`app/manager.py`).
- Hay tests que comprueban que `/health` no expone la clave y que los errores
  públicos se redactan (`tests/test_api.py`).

### Riesgos residuales

- La redacción está en la capa API. El CLI escribe trazas en `artifacts/traces/`
  y el runner de evaluación escribe `records.jsonl` sin pasar por `_redact()`.
  Esos archivos están ignorados por Git, pero pueden contener errores crudos del
  proveedor.
- El patrón genérico no cubre todos los formatos de clave. Una clave de Tavily
  solo se elimina si está configurada y se sustituye por valor exacto.
- No hay gestor de secretos, rotación, cifrado en reposo ni Docker secrets.
- No hay una configuración de logging central con filtro de secretos. Algunos
  errores de búsqueda se registran con su texto completo.

## 3. Inyección de prompts

### Implementado

- **Allowlist de herramientas:** solo `search_web`, `search_arxiv`,
  `search_wikipedia` y `fetch_page`. No hay shell, escritura de archivos,
  navegador ni ejecución de código.
- `ToolNode(..., handle_tool_errors=True)` y `invoke_with_tools()` vinculan
  únicamente esas herramientas.
- Las fuentes se reconstruyen desde los `ToolMessage` reales; `ResearchAnswer` no
  incluye URLs para que el modelo no las invente.
- `sanitize_research_output()` descarta claims cuyas fuentes no fueron recuperadas
  y `validate_citations()` marca IDs desconocidos.
- El critic añade una comprobación determinista: cada claim debe tener al menos
  una fuente válida. No comprueba entailment.
- Las notas y snippets se compactan antes de enviarlos al analyst, critic y
  writer; el bloque de evidencia del researcher tiene un tope de 8.000 caracteres.
- La UI muestra el Markdown como texto y solo enlaza URLs `http`/`https`.

### Riesgos residuales

- **No hay delimitadores explícitos de contenido no confiable.** Una página puede
  incluir “ignora las instrucciones anteriores”; ese texto entra en el contexto
  del modelo como parte de un `ToolMessage`. La serialización JSON y el formato
  `[src_...]` ayudan, pero no son una defensa semántica.
- No hay allowlist de dominios ni proxy de contenido: `fetch_page` puede acceder
  a cualquier host público.
- La validación de citas es estructural, no semántica. Un claim puede citar una
  fuente real que no lo respalde.
- `validate_citations()` añade los problemas a `limitations`, pero no elimina
  referencias desconocidas del Markdown ni rechaza el informe.
- El juez de evaluación recibe la respuesta candidata en el mismo payload; una
  respuesta adversarial podría intentar influir en el juez. Es una evaluación
  offline, pero conviene separar instrucciones y contenido.
- No hay tests específicos de inyección de prompts.

## 4. SSRF y red

### Implementado

- `canonicalize_url()` acepta solo `http` y `https`, rechaza credenciales
  embebidas y normaliza host, puerto, path y query.
- `validate_public_url()` bloquea `localhost`, `*.local`, `metadata` y
  `metadata.google.internal`; solo permite puertos 80 y 443; resuelve el host y
  exige que todas las IPs sean globales.
- `HttpPageFetcher` usa `follow_redirects=False`, valida cada redirección y
  limita a tres saltos.
- Allowlist de `Content-Type`: `text/html`, `application/xhtml+xml` y
  `text/plain`.
- Límites: timeout de 20 s, `http_max_bytes=2.000.000` y
  `fetch_max_chars=12.000`.
- `fetch_page` devuelve un JSON de error controlado en vez de propagar la
  excepción.
- En modo frozen no hay red: `FrozenPageFetcher` solo sirve documentos del
  corpus.
- Tests de SSRF cubren loopback, redes privadas, link-local, metadatos, esquema
  `file://`, puerto no permitido y redirección a IP privada.

### Riesgos residuales

- **DNS rebinding / TOCTOU:** la validación resuelve el host, pero `httpx` vuelve
  a resolver al conectar. La IP validada no se fija.
- **Descarga completa antes de truncar:** `response.content` carga el cuerpo
  antes de aplicar `http_max_bytes`; no hay lectura en streaming ni comprobación
  previa de `Content-Length`.
- El timeout es por petición; con redirecciones no hay un deadline global.
- La caché se consulta antes de revalidar la URL; una caché local manipulada
  podría devolver contenido sin pasar por `validate_public_url()`.
- No hay allowlist de dominios, proxy de egreso ni bloqueo explícito de proxies
  del entorno.
- El límite de bytes no protege frente a cuerpos comprimidos que se descomprimen
  antes de medirlos.

## 5. Abuso de recursos

### Implementado

- `BudgetGuard` corta por llamadas, tokens y rondas; `max_tool_steps` limita el
  ReAct.
- `TokenRateLimiter` comparte una ventana de tokens/minuto por proceso.
- `TavilyBudget` reserva llamadas de forma atómica en SQLite y no consume en
  cache hits.
- La API tiene rate limit de 30 peticiones/minuto por IP en los POST y devuelve
  `429` con `Retry-After`.
- `RunManager` limita el registro a 200 runs y evacúa runs terminales sin
  suscriptores.
- El SSE tiene heartbeat y limpia suscriptores al desconectar.
- `recursion_limit` y límites de pasos evitan bucles infinitos.

### Riesgos residuales

- **Presupuesto no global en fan-out:** cada worker recibe un snapshot del usage.
  Varios workers pueden superar el límite antes de que el siguiente nodo
  secuencial lo detecte.
- Los reintentos del cliente LLM no siempre se contabilizan en `Usage`; el gasto
  real de intentos fallidos puede ser mayor que el reportado.
- El rate limit de API solo cubre POST, no GET ni SSE. Vive en memoria y no se
  comparte entre workers.
- `RateLimiter` no purga claves de IPs antiguas.
- `RunRecord.events` y las colas SSE no tienen cota. Un cliente lento o muchos
  eventos pueden crecer en memoria.
- No hay timeout global de ejecución ni cancelación del run cuando el cliente SSE
  se desconecta.
- Los runs en `awaiting_approval` no son terminales y no se evacúan; no hay TTL.
- El limitador TPM es una estimación por proceso, no un contador exacto.
- Tavily reserva una llamada por intento, incluidos reintentos.

## 6. HITL

### Implementado

- El nodo `approval` llama a `interrupt()` antes del writer.
- La API y el CLI reanudan con `Command(resume={"approved": ..., "feedback": ...})`.
- Se acepta bool, string o dict; el feedback se trunca a 2.000 caracteres.
- Un rechazo termina sin informe y se presenta como `rejected` en la API.
- El checkpointer guarda el estado para reanudar en otro proceso.

### Lo que no garantiza

- El feedback **no se reinyecta** en el writer ni en una nueva ronda.
- Un rechazo no inicia una revisión; termina el run.
- Se aprueba evidencia, no el borrador final; no hay edición del texto.
- El cliente de la API puede enviar `"hitl": false` y evitar la pausa aunque el
  servidor tenga `RESEARCH_HITL=true`.
- No hay autenticación de revisor ni auditoría de identidad; cualquiera que
  conozca el `run_id` puede aprobar o rechazar.
- No hay timeout para runs pendientes de aprobación.
- La aprobación no vuelve a validar citas ni hechos.

## 7. API y despliegue

### Implementado

- CORS limitado a `localhost`/`127.0.0.1` en los puertos de la demo.
- `allow_credentials=False`.
- Redacción de errores y trazas.
- Docker con usuario no root `appuser`, healthcheck y volumen nombrado.
- Un solo worker de uvicorn, tal como requiere el registro en memoria.

### Riesgos

- **No hay autenticación.** Cualquier cliente que alcance el puerto puede iniciar
  runs, consumir cuota, leer estados y aprobar/rechazar si conoce el `run_id`.
- No hay cuotas por usuario ni ownership de runs.
- El registro de runs vive en memoria; tras reiniciar, `GET` devuelve 404.
- El rate limiter es local y por proceso.
- No hay TLS, proxy inverso, cabeceras de seguridad ni límites de recursos en
  `docker-compose.yml`.
- `/docs` y OpenAPI quedan expuestos por defecto.
- `/health` revela nombres de modelos, backend de checkpointer, backend de
  búsqueda y flags de claves configuradas.
- El `hitl` controlado por request permite saltarse una política global.

**La demo debe quedarse en local.** No la expongas a Internet sin auth, TLS,
cuotas por usuario, persistencia del registro y límites de recursos.

## 8. Datos, privacidad y copyright

### Qué se persiste

- Caché SQLite: búsquedas y páginas extraídas (hasta 12.000 caracteres).
- Presupuesto Tavily: proveedor, periodo, llamadas y fecha; no guarda consultas.
- Checkpointer: pregunta, plan, notas, fuentes, análisis, crítica, informe,
  traza, errores y decisión HITL.
- Trazas CLI y resultados de evaluación: pregunta, respuestas, claims, fuentes,
  snippets, usage, errores y traza.
- Registro API en memoria: pregunta, informe, usage, errores, traza y eventos SSE.

### Riesgos

- No hay retención, borrado, anonimización ni cifrado en reposo.
- No hay filtro de PII en preguntas, páginas, notas o trazas.
- El contenido web puede estar sujeto a copyright; la caché y los informes
  guardan texto extraído. No hay política de `robots.txt` ni de licencias de
  páginas.
- Los resultados de evaluación publicados contienen respuestas completas del
  modelo y trazas; no contienen claves, pero sí contenido generado.
- El corpus de evaluación es Wikipedia CC BY-SA 4.0, con atribución y URL; el
  código se publica bajo MIT, pero el corpus conserva su licencia CC BY-SA 4.0.

## 9. Defensas implementadas frente a recomendaciones

| Tema | Implementado | Pendiente para producción |
| :--- | :--- | :--- |
| Secretos | `SecretStr`, `.env` ignorado, redacción API, Docker sin `.env` | Gestor de secretos, rotación, redacción global |
| Prompt injection | Allowlist de tools, contratos, citas estructurales, límites | Delimitadores, jerarquía de instrucciones, allowlist de dominios, entailment |
| SSRF | Validación de URL/IP/redirect, límites, allowlist MIME | IP pinning, streaming, deadline global, proxy de egreso |
| Cuotas | `BudgetGuard`, TPM, Tavily budget, rate limit API | Presupuesto global/distribuido, cuotas por usuario, contabilizar reintentos |
| HITL | `interrupt()`, checkpointer, API/CLI | Auth de revisor, feedback reinyectado, TTL, política server-side |
| Persistencia | SQLite, allowlist del checkpointer | Retención, cifrado, borrado, repositorio de runs |
| API | CORS local, redacción, Docker no root | Auth, TLS, límites por usuario, proxy, cabeceras |
| Observabilidad | Traza, SSE, usage | Logging estructurado, filtros de secretos, OpenTelemetry |

## 10. Recomendaciones priorizadas

1. **Auth y ownership de runs** en `GET`, SSE y `/approve`; HITL impuesto por el
   servidor y auditoría de revisor.
2. **Defensa de inyección de prompts:** marcar el contenido de herramientas como
   dato no confiable, delimitarlo y añadir instrucciones de jerarquía; valorar
   allowlist de dominios.
3. **SSRF endurecido:** resolver una vez, conectar a la IP validada, leer en
   streaming con tope, comprobar `Content-Length` y fijar un deadline global.
4. **Presupuesto global** y cuotas por usuario; contabilizar reintentos y evitar
   overshoot en fan-out.
5. **Persistencia de runs** y TTL para HITL; límites de eventos SSE y runs
   activos.
6. **Redacción centralizada** en API, CLI, evaluación y logs; no persistir
   errores crudos del proveedor.
7. **Validación semántica de citas** o revisión humana explícita; no confundir
   “claim con source_id” con “claim respaldado”.
8. **Retención y borrado** de checkpoints, trazas, caché y resultados; cifrado en
   reposo si se manejan datos sensibles.
9. **Tests de seguridad** para inyección, DNS rebinding, cuerpos grandes, SSE
   lento, presupuesto concurrente y redacción en CLI/eval.

Estas recomendaciones **no están implementadas** en el repositorio; se incluyen
para que el alcance de la demo quede claro.
