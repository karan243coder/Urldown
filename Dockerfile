FROM python:3.11-slim

# System dependencies — ffmpeg + aria2 + qBittorrent + fonts + procps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    aria2 \
    qbittorrent-nox \
    curl \
    wget \
    procps \
    fonts-dejavu-core \
    fontconfig \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Optional: libtorrent (not available on slim by default; if needed use 'apt-get install python3-libtorrent-rasterbar' on full base)

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -U "yt-dlp[default,curl-cffi]>=2026.7.4"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/downloads /tmp/bimbo_downloads /app/.aria2 /app/data /app/thumbnails /app/logs

# Health check
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8080/ || exit 1

EXPOSE 8080

CMD ["python", "-m", "bot"]
