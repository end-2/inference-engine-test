# CPU-only llama.cpp inference image. The GGUF model is not baked in;
# it is mounted read-only at /model from the kind node (/models).
ARG BASE_IMAGE=python:3.12-slim-bookworm

FROM ${BASE_IMAGE} AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CMAKE_ARGS="-DGGML_NATIVE=OFF" \
    CMAKE_BUILD_PARALLEL_LEVEL=12

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY base/requirements.txt /build/requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /build/requirements.txt \
    && /opt/venv/bin/pip check \
    && /opt/venv/bin/python -c "import fastapi, uvicorn, llama_cpp"

FROM ${BASE_IMAGE} AS runtime

USER 0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    OMP_NUM_THREADS=4 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY base/*.py /app/base/
USER 1000:1000
EXPOSE 8000
ENTRYPOINT ["python", "-m", "base.server"]

FROM runtime AS enhanced-batch
COPY enhanced/__init__.py /app/enhanced/
COPY enhanced/batch/*.py /app/enhanced/batch/
ENTRYPOINT ["python", "-m", "enhanced.batch.server"]

FROM runtime AS enhanced-cache
COPY enhanced/__init__.py /app/enhanced/
COPY enhanced/cache/*.py /app/enhanced/cache/
ENTRYPOINT ["python", "-m", "enhanced.cache.server"]

FROM runtime AS base-metric
USER 0
COPY base-metric/requirements.txt /tmp/metric-requirements.txt
RUN pip install --no-cache-dir -r /tmp/metric-requirements.txt && pip check
COPY base-metric/*.py /app/base_metric/
USER 1000:1000
ENTRYPOINT ["python", "-m", "base_metric.server"]

FROM runtime AS base
