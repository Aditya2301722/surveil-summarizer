# Dockerfile - production-friendly for the FastAPI app
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install small build deps (kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Copy requirements first for Docker cache
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# Copy source code
COPY src/ /app/src/

# If you have an .env file you can copy it (optional)
#COPY .env /app/.env

ENV PYTHONPATH=/app/src
EXPOSE 8080

CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
