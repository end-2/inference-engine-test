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
COPY inference/*.py /app/inference/
COPY llamacpp/__init__.py /app/llamacpp/
COPY llamacpp/base/*.py /app/llamacpp/base/
USER 1000:1000
EXPOSE 8000
ENTRYPOINT ["python", "-m", "llamacpp.base.server"]

FROM runtime-llamacpp AS enhanced-batch-llamacpp
COPY llamacpp/batch/*.py /app/llamacpp/batch/
ENTRYPOINT ["python", "-m", "llamacpp.batch.server"]

FROM runtime-llamacpp AS enhanced-cache-llamacpp
COPY llamacpp/cache/*.py /app/llamacpp/cache/
ENTRYPOINT ["python", "-m", "llamacpp.cache.server"]

FROM runtime-llamacpp AS base-metric-llamacpp
USER 0
COPY llamacpp/metrics/requirements.txt /tmp/metric-requirements.txt
RUN pip install --no-cache-dir -r /tmp/metric-requirements.txt && pip check
COPY llamacpp/metrics/*.py /app/llamacpp/metrics/
USER 1000:1000
ENTRYPOINT ["python", "-m", "llamacpp.metrics.server"]

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
COPY huggingface/requirements.txt /tmp/requirements.txt
# The CPU index avoids CUDA runtime dependencies on Linux x86_64.
RUN pip install --no-cache-dir torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip check \
    && python -c "import torch, transformers; assert torch.version.cuda is None"
COPY inference/*.py /app/inference/
COPY huggingface/__init__.py /app/huggingface/
COPY huggingface/runtime/*.py /app/huggingface/runtime/
RUN groupadd --gid 1000 inference \
    && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /tmp inference
ENV TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor
USER 1000:1000
EXPOSE 8000

FROM transformers-runtime AS transformers-llama-runtime
COPY huggingface/llama/*.py /app/huggingface/llama/
COPY huggingface/llama/base/*.py /app/huggingface/llama/base/
ENTRYPOINT ["python", "-m", "huggingface.llama.base.server"]

FROM runtime-llamacpp AS base-llamacpp

FROM transformers-llama-runtime AS transformers-enhanced-batch
COPY huggingface/llama/batch/*.py /app/huggingface/llama/batch/
ENTRYPOINT ["python", "-m", "huggingface.llama.batch.server"]

FROM transformers-llama-runtime AS transformers-enhanced-cache
COPY huggingface/llama/cache/*.py /app/huggingface/llama/cache/
ENTRYPOINT ["python", "-m", "huggingface.llama.cache.server"]

FROM transformers-llama-runtime AS transformers-base-metric
USER 0
COPY huggingface/llama/metrics/requirements.txt /tmp/metric-requirements.txt
RUN pip install --no-cache-dir -r /tmp/metric-requirements.txt && pip check
COPY huggingface/llama/metrics/*.py /app/huggingface/llama/metrics/
USER 1000:1000
ENTRYPOINT ["python", "-m", "huggingface.llama.metrics.server"]

FROM transformers-runtime AS transformers-mamba-base
COPY huggingface/mamba/*.py /app/huggingface/mamba/
COPY huggingface/mamba/base/*.py /app/huggingface/mamba/base/
ENTRYPOINT ["python", "-m", "huggingface.mamba.base.server"]

FROM transformers-mamba-base AS transformers-mamba-cache
COPY huggingface/mamba/cache/*.py /app/huggingface/mamba/cache/
ENTRYPOINT ["python", "-m", "huggingface.mamba.cache.server"]

FROM transformers-runtime AS transformers-hybrid
COPY huggingface/jamba/*.py /app/huggingface/jamba/
COPY huggingface/jamba/base/*.py /app/huggingface/jamba/base/
COPY huggingface/jamba/hybrid/*.py /app/huggingface/jamba/hybrid/
ENTRYPOINT ["python", "-m", "huggingface.jamba.hybrid.server"]

FROM transformers-llama-runtime AS transformers-pd
USER 0
COPY huggingface/llama/inference_distributed/requirements.txt /tmp/pd-requirements.txt
RUN pip install --no-cache-dir -r /tmp/pd-requirements.txt && pip check
COPY huggingface/llama/inference_distributed/*.py /app/huggingface/llama/inference_distributed/
USER 1000:1000
ENTRYPOINT ["python", "-m", "huggingface.llama.inference_distributed.server"]

FROM transformers-llama-runtime AS transformers-base
