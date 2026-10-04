FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY scripts/check-mmlu.py /app/scripts/check-mmlu.py
COPY benchmarks/inference.json /app/benchmarks/inference.json
USER 1000:1000
ENTRYPOINT ["python3", "/app/scripts/check-mmlu.py"]
