FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY alembic ./alembic

RUN pip install --upgrade pip && pip install .

COPY scenarios ./scenarios
COPY golden_dialogues ./golden_dialogues

RUN addgroup --system --gid 1001 arena && \
    adduser --system --uid 1001 --ingroup arena arena && \
    mkdir -p /app/speech_cache && \
    chown -R arena:arena /app

USER arena
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
