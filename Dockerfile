# Dockerfile for Hugging Face Spaces (Docker SDK).
# HF runs the container with no extra args; we expose port 7860 (the
# HF default) and start the multi-visitor web mode.

FROM python:3.12-slim AS base

# OpenCV needs these C libraries even with -headless.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face requires a non-root user (UID 1000).
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WECFU_SESSIONS_ROOT=/tmp/wecfu_sessions

WORKDIR /app

COPY --chown=user pyproject.toml ./
COPY --chown=user wecfu/ ./wecfu/

RUN pip install --user --no-cache-dir .

EXPOSE 7860

CMD ["wecfu", "web", "--host", "0.0.0.0", "--port", "7860"]
