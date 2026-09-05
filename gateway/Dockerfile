# --- build stage: install deps into a venv, keeps the final image slim ---
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt

# --- final stage ---
FROM python:3.12-slim

RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app

COPY --from=builder /venv /venv
COPY app ./app

ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
