FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o conteúdo do projeto para dentro do container
COPY . .

EXPOSE 8000

# Como o main.py está em src/api/main.py, o uvicorn deve apontar para lá: