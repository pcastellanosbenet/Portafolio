# Pavel Castellanos · AI Engineer Portfolio

Proyectos de inteligencia artificial donde aplico **machine learning, deep learning y NLP**
a problemas concretos. Cada proyecto es reproducible, está documentado y reporta métricas,
no solo resultados visuales.

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
| Asistente RAG sobre documentación | Recuperación de información, evaluación cuantitativa, API y despliegue | Transformers · FastAPI · Docker | — | Planificado |

> `traffic-signs` y `bert-attention` están terminados y documentados. El siguiente paso es
> el asistente RAG sobre documentación.

## Sobre mí

Soy un entusiasta de la inteligencia artificial con formación universitaria en
Telecomunicaciones y Electrónica. La mayor parte de mis conocimientos en IA los he
desarrollado de forma autodidacta, explorando aprendizaje automático, aprendizaje profundo
y modelos generativos, y aplicándolos en proyectos prácticos. Me apasiona aprender y busco
crecer en entornos colaborativos donde pueda aportar desde el análisis y la implementación
técnica de proyectos con impacto real.

## Cómo trabajo

- **Reproducibilidad:** semillas fijas, dependencias versionadas y un comando claro para
  entrenar y evaluar. Los datasets no se suben al repositorio: cada proyecto incluye un
  script de descarga.
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
processing and retrieval-augmented generation. Every project is reproducible, documented
and evaluated with quantitative metrics. Datasets are not committed; each project ships a
download script. Code is released under the MIT license.
