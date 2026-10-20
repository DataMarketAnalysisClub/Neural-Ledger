# The public demo's API image with OCR for photographed statements and receipts (docs/runbooks/DEPLOY.md).
# A copy of backend/Dockerfile (keep both in sync) that adds EasyOCR on CPU torch, with its weights built in.
# pymupdf (AGPL-3.0) is left out on purpose, as in backend/pyproject.toml: photos are read by OCR, and a
# scanned PDF gets the API's "needs OCR" error. Build context: the repository root (app/ on the server).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NL_CONTRACTS_DIR=/app/contracts \
    NL_DATA_DIR=/app/data \
    NL_OCR_MODEL_DIR=/app/models/easyocr

WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/README.md backend/README.md
COPY backend/src backend/src
# CPU-only torch first, otherwise easyocr pulls the multi-GB CUDA build.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
# The `ocr` extra without pymupdf; `receipts` decodes the SII stamp on a photographed boleta.
ARG EXTRAS=api,pdf,ml,receipts
RUN pip install --no-cache-dir "./backend[${EXTRAS}]" "easyocr>=1.7" "Pillow>=10" "numpy>=1.26" \
    && ! pip show pymupdf >/dev/null 2>&1
# The running container never downloads weights (ocr_reader defaults to download=False).
RUN python -c "from neural_ledger.adapters.outbound.statements.ocr_tabular import prepare_models; prepare_models(model_dir='/app/models/easyocr')"

COPY contracts contracts
COPY data data

RUN useradd --create-home --uid 10001 app && mkdir -p /app/var && chown app /app/var
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "neural_ledger.bootstrap.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
