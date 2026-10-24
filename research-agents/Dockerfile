FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RESEARCH_DB_PATH=/app/artifacts/research.db \
    RESEARCH_CHECKPOINT_PATH=/app/artifacts/checkpoints.db

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY app ./app
COPY scripts ./scripts
COPY eval/frozen ./eval/frozen
COPY eval/questions.json ./eval/questions.json
COPY bin ./bin
COPY README.md ./

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/artifacts \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
