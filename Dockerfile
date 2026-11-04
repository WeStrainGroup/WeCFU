# Hugging Face Spaces: build the pinned CPU runtime and verified model cache.
FROM python:3.12-slim

# OpenCV needs these C libraries even with -headless.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face requires a non-root user (UID 1000).
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/runtime/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WECFU_SESSIONS_ROOT=/tmp/wecfu_sessions \
    WECFU_MODEL_HOME=/home/user/.cache/wecfu/models \
    WECFU_SAM_DEVICE=cpu \
    SAM2_BUILD_CUDA=0 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

WORKDIR /app

COPY --chown=user pyproject.toml README.md LICENSE NOTICE THIRD_PARTY_NOTICES.md ./
COPY --chown=user LICENSES/ ./LICENSES/
COPY --chown=user wecfu/ ./wecfu/

RUN /usr/local/bin/python -m venv /home/user/runtime \
    && python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.14.1 torchvision==0.29.1 \
    && python -m pip install --no-cache-dir '.[models]' \
    && python -m wecfu.setup_models \
    && python -m wecfu.setup_models --check --runtime-check

# All remote model acquisition happens above. Requests use the local cache.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

EXPOSE 7860

CMD ["wecfu", "web", "--host", "0.0.0.0", "--port", "7860"]
