FROM python:3.10-slim-bullseye

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install high-performance network and media binaries
RUN apt-get update && apt-get install -y --no-install-recommends \
    aria2 \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway automatically assigns PORT; health check binds to it
CMD ["python", "main.py"]
