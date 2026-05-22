# ==========================================
# Stage 1: Build dependencies (wheels)
# ==========================================
FROM python:3.11-slim AS builder

# Set shell and standard envs
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install compilation/build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements to leverage build caching
COPY requirements.txt .

# Create python wheels
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt


# ==========================================
# Stage 2: Final minimal production image
# ==========================================
FROM python:3.11-slim

LABEL maintainer="Antigravity Team"
LABEL description="Production Docker image for Job Market Intelligence Analyzer"

# Set non-interactive timezone environment and other Python runtime configurations
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install lightweight runtime packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder and install them
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* && \
    rm -rf /wheels

# Create system user for security (avoid running as root)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -m -s /bin/bash appuser

# Copy application source code (excluding files in .dockerignore)
COPY --chown=appuser:appgroup . .

# Create the staticfiles directory and set permissions (for collectstatic)
RUN mkdir -p /app/staticfiles && \
    chown -R appuser:appgroup /app

# Switch to the non-privileged user
USER appuser

# Expose the default port
EXPOSE 8000

# Collect static files during build time so they are embedded in the image
# We set dummy environment variables so Django loads settings successfully
RUN DATABASE_URL=sqlite:///:memory: \
    SECRET_KEY=django-insecure-build-placeholder \
    DEBUG=False \
    python manage.py collectstatic --noinput

# Run migrations and start the app dynamically binding to $PORT
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3"]
