# Fase 3 — HITL y reanudación real

Esta carpeta contiene la evidencia de la Fase 3: un run real pausado antes del
writer, reanudado en un **proceso distinto** con el mismo `thread_id` y aprobado
por una persona.

## Run

- **Pregunta:** «¿Qué es un transformer y para qué se usa en NLP?»
- **Run ID / thread ID:** `phase3-hitl-20261023`
- **Configuración:** 1 worker, 1 paso de herramienta por subpregunta, 1 ronda,
  fallback desactivado y HITL activo.
- **Resultado:** informe con 4 claims y 15 fuentes; confianza alta.
- **Uso:** 10 llamadas LLM, 24.652 tokens, 3 búsquedas y 301,8 s.
- **Errores:** ninguno. El writer terminó con `fallback=False`, sin el `413` que
  había aparecido en una prueba anterior.

La traza curada está en [`hitl-resume.json`](./hitl-resume.json). Incluye la
decisión de aprobación (`hitl`), el evento `hitl_decision`, la ruta del
supervisor, el uso por nodo y el informe final.

## Qué se comprobó

1. El grafo se detiene en `interrupt()` antes del writer y persiste el estado en
   SQLite asíncrono.
2. El proceso del CLI termina. Un segundo proceso lee el checkpoint con el mismo
   `thread_id` y reanuda la ejecución.
3. La aprobación continúa hacia el writer; el rechazo termina con
   `status="failed"` y sin informe.
4. El writer recibe notas y fuentes compactadas. La prueba anterior pidió 8.046
   tokens frente a un límite de 8.000 TPM y cayó al informe determinista; tras
   recortar notas a 300 caracteres y snippets a 120, el writer real completó el
   informe sin fallback.
5. La traza incluye nodo, modelo, tokens, latencia, tools y errores.

## Reproducir

```bash
cd research-agents
RESEARCH_MAX_ROUNDS=1 RESEARCH_MAX_TOOL_STEPS=1 RESEARCH_MAX_WORKERS=1 \
LLM_MAX_RETRIES=0 \
.venv/bin/python -m scripts.run_research \
  "¿Qué es un transformer y para qué se usa en NLP?" \
  --hitl --no-fallback --run-id mi-run

# En otro proceso:
.venv/bin/python -m scripts.run_research \
  --resume --thread-id mi-run --approve --no-fallback
```

Para rechazar:

```bash
.venv/bin/python -m scripts.run_research \
  --resume --thread-id mi-run --reject \
  --feedback "Faltan fuentes primarias."
```

Para reanudar un checkpoint que falló sin una decisión HITL:

```bash
.venv/bin/python -m scripts.run_research --resume --thread-id mi-run
```

## Curación

El JSON publicado recorta los snippets a 280 caracteres, normaliza las
referencias `【src_…†L…】` a `[src_…]` y elimina metadatos internos. No contiene
claves, rutas locales ni páginas completas. Las métricas, URLs, claims y errores
se conservan.
