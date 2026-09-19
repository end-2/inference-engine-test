ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE} AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Some dependencies, including crick, need compilation on Linux arm64.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir aiperf==0.12.0 \
    && /opt/venv/bin/pip check

FROM ${BASE_IMAGE}

# AIPerf 0.12 requires HF_HUB_OFFLINE unset for local tokenizer paths.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/tmp/huggingface \
    XDG_CACHE_HOME=/tmp/cache \
    MPLCONFIGDIR=/tmp/matplotlib \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv

WORKDIR /tmp
USER 1000:1000
ENTRYPOINT ["aiperf"]
