# Сборка из корня репозитория: docker build -f apps/api/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app/apps/api
COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
RUN pip install .
COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY seed /app/seed
COPY prompts /app/prompts
COPY mcp/mock-corp/mock_corp /app/mcp/mock-corp/mock_corp

ENV SEED_DIR=/app/seed PROMPTS_DIR=/app/prompts PYTHONPATH=/app/apps/api:/app/mcp/mock-corp ATTACHMENTS_DIR=/data/attachments
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m app.cli seed-if-empty && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
