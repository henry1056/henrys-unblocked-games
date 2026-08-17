FROM python:3.12-slim

# System deps (gcc needed for bcrypt)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Persistent data lives outside the image
RUN mkdir -p /data/db /data/uploads/games && \
    chown -R nobody:nogroup /data

# Run as non-root
USER nobody

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/api/health')" || exit 1

CMD ["python3", "app.py"]
