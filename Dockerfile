# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    zlib1g-dev \
    libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

# Install package into image
COPY pyproject.toml README.md LICENSE /app/
COPY services /app/services
RUN pip install --upgrade pip && pip install --no-cache-dir .

# Final stage
FROM python:3.11-slim

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy only the installed packages from builder
COPY --from=builder /usr/local /usr/local
ENV PYTHONUNBUFFERED=1

# Default entrypoint is the ragops CLI
ENTRYPOINT ["ragops"]
CMD ["--help"]
