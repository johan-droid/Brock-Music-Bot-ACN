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
# Remove dummy and copy real source (assets/ too: main.rs embeds assets/brook.png
# at compile time via include_bytes!)
RUN rm -rf src
COPY src ./src
COPY assets ./assets
# Build actual binary.
#
# IMPORTANT: Cargo fingerprints source files by mtime, and Docker layer caches can
# restore `src/` with mtimes older than the cached Cargo fingerprints above. When
# that happens `cargo build` does NOT recompile — the binary that ships is the
# dummy `fn main() {}` stub from the dependency-cache step, which runs and exits
# with status 0 instantly (the dyno "crash"). Force a rebuild deterministically by
# stamping every source file with an mtime in the far future (touching is done in
# the builder layer, which Docker does NOT re-normalize).
RUN find src -name '*.rs' -exec touch -d '2080-01-01T00:00:00Z' {} + \
    && cargo build --release --locked \
    && echo "=== Verifying real binary was produced ===" \
    && /bin/bash -c 'test "$(stat -c%s /app/target/release/brook-music-bot)" -gt 1000000 \
        || { echo "FATAL: cargo shipped the dummy stub binary (too small); refusing to build."; exit 1; }'

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

# Debug: verify the binary is the real bot (not the dependency-cache stub) and
# that all shared libraries are resolvable
RUN echo "=== Binary size check ===" \
    && /bin/bash -c 'test "$(stat -c%s /app/brook-music-bot)" -gt 1000000 \
        || { echo "FATAL: stub binary leaked into runtime image"; exit 1; }' \
    && ls -l /app/brook-music-bot \
    && echo "=== Shared library check ===" && ldd /app/brook-music-bot && echo "=== All OK ==="

# Non-root user for security
RUN useradd -r -u 1001 -s /sbin/nologin appuser && chown -R appuser:appuser /app
USER appuser

# Worker dynos receive no $PORT from Heroku; the internal Axum HTTP API binds 8000.
ENV RUST_LOG=info,brook_music_bot=debug,h2=warn,rustls=warn,reqwest=warn,hyper=warn,sqlx=warn
ENV RUST_BACKTRACE=1
EXPOSE 8000

CMD ["/app/brook-music-bot"]