FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONPATH="${PYTHONPATH}:/app"

CMD ["uvicorn", "app:app", "--port", "8000","--host", "0.0.0.0"]
