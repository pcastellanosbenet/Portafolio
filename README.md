# Pavel Castellanos · AI Engineer Portfolio

Proyectos de inteligencia artificial donde aplico **machine learning, deep learning y NLP**
a problemas concretos. El código y los tests son reproducibles; cuando los datos son
públicos o están incluidos, también lo son las métricas. Cada proyecto está documentado y
reporta métricas reales, no solo resultados visuales.

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-F7931E?style=for-the-badge&logo=scikitlearn&logoColor=white)
![Hugging Face](https://img.shields.io/badge/Hugging%20Face-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)

## Proyectos

| Proyecto | Qué demuestra | Stack | Resultado | Estado |
| :--- | :--- | :--- | :--- | :--- |
| [Clasificación de señales de tráfico](./traffic-signs) | Visión por computador: CNN, transfer learning, augmentación, evaluación por clase y análisis de errores | PyTorch · torchvision | 97,47% accuracy · 43 clases | Completado |
| [Interpretabilidad de BERT](./bert-attention) | NLP: mecanismos de atención, análisis de capas y cabezas, visualización | PyTorch · Transformers | 12 capas × 12 cabezas · 8 mapas curados | Completado |
| [KNX RAG Assistant](./rag-assistant) | RAG end-to-end: ingesta de PDFs, búsqueda híbrida, citas, evaluación, API y Docker | Transformers · Qdrant · FastAPI · Docker | Recall@10 0,908 · MRR 0,850 · 20 preguntas | Completado |
| [research-agents](./research-agents) | Agentes: supervisor, planner, researchers paralelos, crítico, citas, HITL, trazas y evaluación con corpus congelado | LangGraph · Groq · Tavily · FastAPI · SQLite · Docker | 5 preguntas reales · HITL por CLI/API · B0/20 · smoke B0/B1/B2 · 149 tests | En desarrollo (Fase 5/6) |

> Los tres primeros proyectos están terminados y documentados. `research-agents`
> tiene cerradas las Fases 2, 3 y 5: herramientas, caché, paralelismo, runs
> reales, HITL y checkpointer SQLite, API/SSE, UI, CLI y Docker. La Fase 4 está
> parcial: B0 está medido sobre las 20 preguntas, pero B1/B2 y las repeticiones de
> robustez siguen pendientes por cuota/tiempo. Su README, `docs/evaluation.md` y
> `docs/phase5/README.md` documentan las métricas reales, la prueba E2E y las
> limitaciones.
>
> El corpus del estándar KNX no se redistribuye: se aporta localmente con una
> licencia válida y se indexa con los scripts del proyecto. `rag-assistant` incluye
> además un corpus sintético de demostración para probar el flujo completo sin ese
> corpus; sus métricas están separadas de las de KNX.

## Sobre mí

Soy un entusiasta de la inteligencia artificial con formación universitaria en
Telecomunicaciones y Electrónica. La mayor parte de mis conocimientos en IA los he
desarrollado de forma autodidacta, explorando aprendizaje automático, aprendizaje profundo
y modelos generativos, y aplicándolos en proyectos prácticos. Me apasiona aprender y busco
crecer en entornos colaborativos donde pueda aportar desde el análisis y la implementación
técnica de proyectos con impacto real.

## Cómo trabajo

- **Reproducibilidad:** semillas fijas, dependencias versionadas y un comando claro para
  entrenar y evaluar. Los datasets no se suben al repositorio. Cuando la licencia lo
  permite, cada proyecto incluye un script de descarga; cuando no, se documenta el
  requisito y se ofrece una alternativa de demostración. El corpus KNX se aporta
  localmente porque está protegido por derechos de autor.
- **Evaluación:** además de la métrica principal, reporto métricas por clase, matrices de
  confusión y análisis de errores. Un resultado sin contexto no cuenta.
- **Documentación:** cada README explica el problema, los datos, el enfoque, los resultados
  y las limitaciones del proyecto.
- **Ingeniería:** tests sobre la lógica crítica, linting y CI en GitHub Actions.

## Contacto

[![LinkedIn](https://img.shields.io/badge/LinkedIn-pavel--castellanos--1989pcb-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/pavel-castellanos-1989pcb)
[![GitHub](https://img.shields.io/badge/GitHub-pcastellanosbenet-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/pcastellanosbenet)

## About (English)

AI Engineer portfolio with hands-on projects in computer vision, natural language
processing and retrieval-augmented generation. Code and tests are reproducible, documented
and evaluated with quantitative metrics; metric reproduction depends on the corresponding
datasets. Datasets are not committed. Downloadable datasets ship with a fetch script, while
the copyrighted KNX corpus is supplied locally with a valid license. `rag-assistant` also
includes a synthetic demo corpus for running the full pipeline without the KNX corpus.
`research-agents` includes a frozen Wikipedia corpus, B0/B1/B2 baselines, a documented
smoke evaluation and a complete B0 run over 20 questions; B1/B2 and the robustness
repetitions are still pending. It also ships a FastAPI/SSE demo with a minimal UI, CLI and
Docker. Code is released under the MIT license.
