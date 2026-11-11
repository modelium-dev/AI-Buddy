# Сборка из корня репозитория: docker build -f mcp/mock-corp/Dockerfile .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY mcp/mock-corp/requirements.txt ./
RUN pip install -r requirements.txt
COPY mcp/mock-corp/mock_corp ./mock_corp
COPY seed /seed
ENV SEED_DIR=/seed
EXPOSE 8001
CMD ["uvicorn", "mock_corp.server:app", "--host", "0.0.0.0", "--port", "8001"]
