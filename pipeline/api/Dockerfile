FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONPATH="${PYTHONPATH}:/app"

# Create non-root user
RUN groupadd --system --gid 1001 appuser && \
    useradd --system --uid 1001 --gid appuser appuser && \
    mkdir -p /data/results && \
    chown -R appuser:appuser /app /data/results

USER appuser

CMD ["uvicorn", "app:app", "--port", "8000","--host", "0.0.0.0"]
