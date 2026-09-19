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
COPY requirements.txt /build/requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /build/requirements.txt \
    && /opt/venv/bin/pip check \
    && /opt/venv/bin/python -c "import fastapi, uvicorn, llama_cpp"

FROM ${BASE_IMAGE}

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
COPY engine.py server.py /app/
USER 1000:1000
EXPOSE 8000
ENTRYPOINT ["python", "/app/server.py"]
