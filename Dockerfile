FROM python:3.10-slim

WORKDIR /app

# Install system utilities: ffmpeg (for video/thumbnails/sample cut) and aria2 (for high-speed torrent/url download)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    aria2 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces routes internal traffic through port 7860
EXPOSE 7860

CMD ["python", "main.py"]
