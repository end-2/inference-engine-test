.PHONY: help up down test status download-model download-tokenizer build-image load-image build-benchmark-image load-benchmark-image benchmark

IMAGE_TAG ?= 0.1.0
AIPERF_IMAGE_TAG ?= 0.12.0
INFERENCE_IMAGE ?= local/llama-base:$(IMAGE_TAG)
INFERENCE_CONTEXT ?= src/base
INFERENCE_MANIFESTS ?= k8s/llama-base

help:
	@echo "Targets:"
	@echo "  up       Create or reuse the local Kubernetes cluster"
	@echo "  down     Delete the local Kubernetes cluster"
	@echo "  test     Run a no-GPU smoke Job with DNS lookup"
	@echo "  status   Show nodes and pods"
	@echo "  download-model  Download the pinned GGUF model file"
	@echo "  download-tokenizer  Download the pinned tokenizer for AIPerf"
	@echo "  build-image     Build the llama-base inference image"
	@echo "  load-image      Load the llama-base image into the cluster nodes"
	@echo "  build-benchmark-image  Build the AIPerf benchmark image"
	@echo "  load-benchmark-image   Load the AIPerf benchmark image into the cluster nodes"
	@echo "  benchmark  Build/load as needed, restart inference per concurrency, save docs/reports"

up:
	./scripts/local-k8s.sh up

down:
	./scripts/local-k8s.sh down

test:
	./scripts/local-k8s.sh test

status:
	./scripts/local-k8s.sh status

download-model:
	./scripts/download-model.sh

download-tokenizer:
	./scripts/download-tokenizer.sh

build-image:
	IMAGE_TAG=$(IMAGE_TAG) ./scripts/build-inference-images.sh base

load-image:
	IMAGE_TAG=$(IMAGE_TAG) ./scripts/load-inference-images.sh base

build-benchmark-image:
	AIPERF_IMAGE_TAG=$(AIPERF_IMAGE_TAG) ./scripts/build-benchmark-images.sh

load-benchmark-image:
	AIPERF_IMAGE_TAG=$(AIPERF_IMAGE_TAG) ./scripts/load-benchmark-images.sh

benchmark:
	INFERENCE_IMAGE="$(INFERENCE_IMAGE)" INFERENCE_CONTEXT="$(INFERENCE_CONTEXT)" \
	INFERENCE_MANIFESTS="$(INFERENCE_MANIFESTS)" AIPERF_IMAGE_TAG="$(AIPERF_IMAGE_TAG)" \
	./scripts/run-benchmark.py
