# Optimized Production Dockerfile for Brook Music Bot on Railway
FROM python:3.12-slim

# Install system dependencies (FFmpeg + build tools for TgCrypto)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Set environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/usr/local/bin:$PATH"

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies (using --prefer-binary for faster builds if possible)
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Build-time syntax gate: fail the image build if any Python file has syntax errors.
RUN python -m compileall -q bot config.py

# Ensure directories are created (env files should be provided via service variables in production)
RUN mkdir -p /app/sessions && chmod -R 777 /app/sessions


# Create necessary directories
RUN mkdir -p /var/log/musicbot /tmp/musicbot && \
    chmod -R 777 /var/log/musicbot /tmp/musicbot

# Health check (checks if the bot process is running)
HEALTHCHECK --interval=30s --timeout=15s --start-period=30s --retries=3 \
    CMD pgrep -f "python -m bot" || exit 1

# Start the bot
CMD ["python", "-m", "bot"]
