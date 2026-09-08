# syntax=docker/dockerfile:1
# Heroku container deployment for Brook Music Bot (worker dyno type)
# Builds a minimal runtime image with Rust binary + ffmpeg for audio processing
#
# Deploy with:
#   heroku stack:set container
#   heroku container:push worker
#   heroku container:release worker
#   heroku ps:scale web=0 worker=1

# ---- Builder stage ----
# NOTE: the toolchain must match the version pinned in `RustConfig`
# (`VERSION=1.97.1`) — the code targets std APIs only available from there.
FROM rust:1.97-bookworm AS builder

# Install system dependencies for native crates (opus, openssl, etc.) and ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    clang \
    cmake \
    pkg-config \
    libssl-dev \
    libopus-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache dependencies: copy manifests first
COPY Cargo.toml Cargo.lock ./
# Create dummy source to build dependencies
RUN mkdir src && echo "fn main() {}" > src/main.rs
RUN cargo build --release --locked
# Remove dummy and copy real source
RUN rm -rf src
COPY src ./src
# Build actual binary
RUN cargo build --release --locked

# ---- Runtime stage ----
FROM debian:bookworm-slim

# Runtime dependencies: ca-certificates for HTTPS, ffmpeg for audio decoding,
# libopus0 and libssl3 for native crates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    libopus0 \
    libssl3 \
    libstdc++6 \
    libgcc-s1 \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp (standalone binary) for YouTube audio extraction
RUN pip3 install --break-system-packages --no-cache-dir yt-dlp \
    && ln -sf /usr/local/bin/yt-dlp /usr/bin/yt-dlp \
    && yt-dlp --version

WORKDIR /app

# Copy binary from builder
COPY --from=builder /app/target/release/brook-music-bot /app/brook-music-bot

# Non-root user for security
RUN useradd -r -u 1001 -s /sbin/nologin appuser && chown -R appuser:appuser /app
USER appuser

# Worker dynos receive no $PORT from Heroku; the internal Axum HTTP API binds 8000.
ENV RUST_LOG=debug
ENV RUST_BACKTRACE=1
EXPOSE 8000

CMD ["/app/brook-music-bot"]