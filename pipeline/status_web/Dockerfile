FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create non-root user
RUN groupadd --system --gid 1001 appuser && \
    useradd --system --uid 1001 --gid appuser appuser && \
    chown -R appuser:appuser /app

USER appuser

CMD streamlit run app.py --server.port=8501 --server.address=0.0.0.0 --server.baseUrlPath="${BASE_URL_PATH:-}"


