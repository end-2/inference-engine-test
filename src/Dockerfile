# CPU inference images use model weights mounted read-only at /model.
ARG BASE_IMAGE=python:3.12-slim-bookworm

FROM ${BASE_IMAGE} AS builder-llamacpp

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CMAKE_ARGS="-DGGML_NATIVE=OFF" \
    CMAKE_BUILD_PARALLEL_LEVEL=12

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY llamacpp/base/requirements.txt /build/requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /build/requirements.txt \
    && /opt/venv/bin/pip check \
    && /opt/venv/bin/python -c "import fastapi, uvicorn, llama_cpp"

FROM ${BASE_IMAGE} AS runtime-llamacpp

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

COPY --from=builder-llamacpp /opt/venv /opt/venv

WORKDIR /app
COPY llamacpp/__init__.py /app/llamacpp/
COPY llamacpp/base/*.py /app/llamacpp/base/
USER 1000:1000
EXPOSE 8000
ENTRYPOINT ["python", "-m", "llamacpp.base.server"]

FROM runtime-llamacpp AS enhanced-batch-llamacpp
COPY llamacpp/enhanced/__init__.py /app/llamacpp/enhanced/
COPY llamacpp/enhanced/batch/*.py /app/llamacpp/enhanced/batch/
ENTRYPOINT ["python", "-m", "llamacpp.enhanced.batch.server"]

FROM runtime-llamacpp AS enhanced-cache-llamacpp
COPY llamacpp/enhanced/__init__.py /app/llamacpp/enhanced/
COPY llamacpp/enhanced/cache/*.py /app/llamacpp/enhanced/cache/
ENTRYPOINT ["python", "-m", "llamacpp.enhanced.cache.server"]

FROM runtime-llamacpp AS base-metric-llamacpp
USER 0
COPY llamacpp/base_metric/requirements.txt /tmp/metric-requirements.txt
RUN pip install --no-cache-dir -r /tmp/metric-requirements.txt && pip check
COPY llamacpp/base_metric/*.py /app/llamacpp/base_metric/
COPY inference_metrics.py /app/
USER 1000:1000
ENTRYPOINT ["python", "-m", "llamacpp.base_metric.server"]

FROM ${BASE_IMAGE} AS transformers-runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/tmp/huggingface \
    OMP_NUM_THREADS=4

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY transformer/requirements.txt /tmp/requirements.txt
# The CPU index avoids CUDA runtime dependencies on Linux x86_64.
RUN pip install --no-cache-dir torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip check \
    && python -c "import torch, transformers; assert torch.version.cuda is None"
COPY llamacpp/__init__.py /app/llamacpp/
COPY llamacpp/base/*.py /app/llamacpp/base/
COPY transformer/__init__.py /app/transformer/
COPY transformer/base/*.py /app/transformer/base/
RUN groupadd --gid 1000 inference \
    && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /tmp inference
ENV TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor
USER 1000:1000
EXPOSE 8000
ENTRYPOINT ["python", "-m", "transformer.base.server"]

FROM runtime-llamacpp AS base-llamacpp

FROM transformers-runtime AS transformers-enhanced-batch
COPY transformer/enhanced/__init__.py /app/transformer/enhanced/
COPY transformer/enhanced/batch/*.py /app/transformer/enhanced/batch/
ENTRYPOINT ["python", "-m", "transformer.enhanced.batch.server"]

FROM transformers-runtime AS transformers-enhanced-cache
COPY llamacpp/enhanced/__init__.py /app/llamacpp/enhanced/
COPY llamacpp/enhanced/cache/__init__.py llamacpp/enhanced/cache/cache.py /app/llamacpp/enhanced/cache/
COPY transformer/enhanced/__init__.py /app/transformer/enhanced/
COPY transformer/enhanced/cache/*.py /app/transformer/enhanced/cache/
ENTRYPOINT ["python", "-m", "transformer.enhanced.cache.server"]

FROM transformers-runtime AS transformers-base-metric
USER 0
COPY transformer/base_metric/requirements.txt /tmp/metric-requirements.txt
RUN pip install --no-cache-dir -r /tmp/metric-requirements.txt && pip check
COPY inference_metrics.py /app/
COPY transformer/base_metric/*.py /app/transformer/base_metric/
USER 1000:1000
ENTRYPOINT ["python", "-m", "transformer.base_metric.server"]

FROM transformers-runtime AS transformers-base
