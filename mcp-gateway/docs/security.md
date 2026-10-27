# Seguridad, política y aprobaciones

> **Fecha:** 2026-10-26.
> **Suite:** 14 ataques y 20 peticiones benignas.
> **Resultado medido:** 14/14 ataques bloqueados, 20/20 benignas permitidas, 0 falsos
> positivos. Informe crudo en `security/results/2026-10-26-suite.json`.
> **Protocolo:** MCP `2026-07-28`.

## Modelo de amenazas

| Amenaza | Vector | Defensa | Resultado |
| :--- | :--- | :--- | :--- |
| Tool poisoning | Descripción con instrucciones maliciosas | Cuarentena heurística y descripción tratada como dato | Bloqueado |
| Tool shadowing | Dos upstreams publican el mismo nombre | Namespacing `servidor__tool` y detección de colisiones | Bloqueado |
| SSRF | URL controlada por el usuario | Esquema http/https, resolución DNS, bloqueo de rangos no públicos, redirecciones y límite de tamaño | Bloqueado |
| Path traversal | `doc_id` con `../../` | Catálogo cerrado de ids; no se accede al filesystem | Bloqueado |
| Inyección en argumentos | Nombres de servicio con SQL | Validación de estado/argumentos; no hay SQL | Bloqueado |
| Acción destructiva | `restart_service` sin aprobación | Política de riesgo + MRTR | Bloqueado |
| Aprobación rechazada | Usuario declina | El gateway no ejecuta | Bloqueado |
| Aprobación manipulada | `requestState` alterado | HMAC-SHA256 con TTL | Bloqueado |
| Replay de aprobación | Reutilizar estado con otros argumentos | Binding a herramienta, hash de definición y hash de argumentos | Bloqueado |
| Bearer ausente | Petición HTTP sin credencial | Middleware 401 + `WWW-Authenticate` | Bloqueado |
| Origen inválido | `Origin` no permitido | DNS rebinding protection del SDK | Bloqueado |

## Política y aprobaciones

- `PolicyEngine` clasifica cada tool como `read`, `write` o `destructive` a partir de
  `readOnlyHint` y `destructiveHint`.
- `GATEWAY_APPROVAL_MODE=risk` exige MRTR solo para destructivas. `always` exige para
  todas y `auto` no exige ninguna.
- `GATEWAY_ALLOWLIST` acepta una lista separada por comas; una tool fuera de la lista se
  rechaza aunque exista en el catálogo.
- `GATEWAY_REQUIRED_SCOPE` exige un scope concreto; `GATEWAY_GRANTED_SCOPES` declara los
  scopes del token de laboratorio. Si no se configuran, no se aplica restricción de
  scope. En producción, el verificador de token debe poblar los scopes reales.
- Las definiciones se fijan por SHA-256. El `requestState` de una aprobación incluye el
  hash de la definición y el hash de los argumentos: si la tool cambia entre la petición
  y el reintento, el estado deja de ser válido y hay que volver a aprobar.
- El estado se firma con HMAC-SHA256 y TTL (`GATEWAY_APPROVAL_TTL_S`, 300 s por defecto).
- La auditoría registra `approval_pending`, `approval_denied`, `policy_denied`,
  `invalid_arguments`, `ok` o `error`, con `trace_id`.
- Los errores pasan por `src/gateway/redaction.py` antes de persistirse: bearer tokens,
  `gsk_…`, `sk-…`, `api_key=…` y `token=…` se sustituyen por `[REDACTED]`.

## Bearer y OAuth 2.1

El gateway es un **resource server**, no un authorization server. En modo bearer:

- `/mcp` exige `Authorization: Bearer <GATEWAY_TOKEN>`.
- Una petición sin token o con token incorrecto recibe `401` y
  `WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource"`.
- `/.well-known/oauth-protected-resource` publica `resource`, `scopes_supported` y
  `bearer_methods_supported`.
- `/health` y el documento PRM son públicos para operación local.

Limitaciones declaradas:

- El token es estático y de laboratorio; no hay introspección, JWT, rotación ni
  authorization server. No se presenta como OAuth completo.
- Los scopes se anuncian en el PRM y `GATEWAY_REQUIRED_SCOPE`/`GATEWAY_GRANTED_SCOPES`
  permiten una comprobación estática, pero no hay un verificador OAuth que los derive de
  un JWT. Una implementación de producción debe validar `iss`, `aud`, `exp` y `scope`
  con un verificador real.
- El gateway no reenvía credenciales del cliente a los upstreams.

## Suite

```bash
cd mcp-gateway
.venv/bin/python -m security.run_suite \
  --output security/results/2026-10-26-suite.json
```

La suite levanta `docs-mcp` y `ops-mcp` por HTTP, `research-mcp` por stdio, un upstream
falso `evil` para poisoning/shadowing, y el gateway con bearer activo. Los escenarios de
herramientas usan un cliente MCP en memoria; los de bearer y `Origin` usan HTTP real.

### Ataques

| ID | Categoría | Resultado |
| :--- | :--- | :--- |
| atk-01 | tool poisoning | Bloqueado |
| atk-02 | tool shadowing | Bloqueado |
| atk-03 | tool desconocida | Bloqueado |
| atk-04 | path traversal | Bloqueado |
| atk-05 | inyección en argumentos | Bloqueado |
| atk-06 | SSRF loopback | Bloqueado |
| atk-07 | SSRF metadata `169.254.169.254` | Bloqueado |
| atk-08 | SSRF `file://` | Bloqueado |
| atk-09 | destructiva sin aprobación | Bloqueado |
| atk-10 | aprobación rechazada | Bloqueado |
| atk-11 | aprobación manipulada | Bloqueado |
| atk-12 | replay con otros argumentos | Bloqueado |
| atk-13 | bearer ausente | Bloqueado |
| atk-14 | `Origin` inválido | Bloqueado |

### Peticiones benignas

20/20 permitidas: 5 de documentación, 4 de investigación, 9 de operaciones, 1 aprobación
válida y 1 `find_tools`. El detalle está en el informe JSON.

## Pruebas

```bash
.venv/bin/pytest tests/security -q
```

Cubren redacción, cuarentena, allowlist/riesgo/scopes, bearer, PRM, manipulación de
estado, replay y cambio de hash de definición. La suite completa se ejecuta a mano porque
levanta varios servidores y un upstream falso.

## Límites

- La cuarentena es heurística: detecta frases como “ignore previous instructions” o
  “exfiltrate”, no todas las variantes semánticas. Un falso positivo bloquearía una tool
  legítima; el informe actual no tuvo ninguno en el corpus benigno.
- La defensa SSRF valida el DNS antes de la petición; queda la ventana teórica de DNS
  rebinding entre resolución y conexión. Una producción debe fijar la IP en el
  transporte.
- La suite no prueba ataques de red reales, malware, ni un authorization server OAuth
  completo.
- Los escenarios de herramientas usan el servidor MCP en memoria; solo bearer y `Origin`
  pasan por HTTP. La matriz de conformidad HTTP está en `docs/protocol.md`.
