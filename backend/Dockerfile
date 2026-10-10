# Build context: repository root (docker compose sets it), so contracts/ and data/ are available.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NL_CONTRACTS_DIR=/app/contracts \
    NL_DATA_DIR=/app/data

WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY README.md README.md
COPY backend/src backend/src
RUN pip install --no-cache-dir "./backend[api]"

COPY contracts contracts
COPY data data

RUN useradd --create-home --uid 10001 app && mkdir -p /app/var && chown app /app/var
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "neural_ledger.bootstrap.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
