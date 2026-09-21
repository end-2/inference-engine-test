.PHONY: help install up down test status download-model download-tokenizer build-image load-image build-benchmark-image load-benchmark-image benchmark benchmark-suite

IMAGE_TAG ?= 0.1.0
AIPERF_IMAGE_TAG ?= 0.12.0
VARIANT ?= transformers-base
INFERENCE_BACKEND ?= $(if $(filter transformers-%,$(VARIANT)),transformers,llamacpp)
INFERENCE_IMAGE ?= local/$(VARIANT):$(IMAGE_TAG)
INFERENCE_CONTEXT ?= src
INFERENCE_TARGET ?= $(VARIANT)
INFERENCE_MANIFESTS ?= k8s/$(VARIANT)
CACHE_POLICY ?= $(if $(filter transformers-enhanced-cache,$(VARIANT)),clear-before-sweep,preserve)
REPETITIONS ?= 3
INFERENCE_NODE ?=
BENCHMARK_NODE ?=

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Download pinned kind and kubectl into .bin
up: ## Create or reuse the local cluster
down: ## Delete the local cluster
test: ## Run the cluster smoke test
status: ## Show nodes and pods
install up down test status:
	./scripts/local-k8s.sh $@

download-model: ## Download the selected model
	$(if $(filter transformers,$(INFERENCE_BACKEND)),./scripts/download-transformers-model.sh,./scripts/download-model-llamacpp.sh)

download-tokenizer: ## Prepare the benchmark tokenizer
	$(if $(filter transformers,$(INFERENCE_BACKEND)),./scripts/download-transformers-model.sh,./scripts/download-tokenizer-llamacpp.sh)

build-image: ## Build the selected VARIANT
	IMAGE_TAG=$(IMAGE_TAG) ./scripts/build-inference-images.sh $(VARIANT)

load-image: ## Load the selected VARIANT into kind
	IMAGE_TAG=$(IMAGE_TAG) ./scripts/load-inference-images.sh $(VARIANT)

build-benchmark-image: ## Build the AIPerf image
	AIPERF_IMAGE_TAG=$(AIPERF_IMAGE_TAG) ./scripts/build-benchmark-images.sh

load-benchmark-image: ## Load the AIPerf image into kind
	AIPERF_IMAGE_TAG=$(AIPERF_IMAGE_TAG) ./scripts/load-benchmark-images.sh

benchmark: ## Measure the selected VARIANT
	INFERENCE_BACKEND="$(INFERENCE_BACKEND)" \
	INFERENCE_IMAGE="$(INFERENCE_IMAGE)" INFERENCE_CONTEXT="$(INFERENCE_CONTEXT)" \
	INFERENCE_TARGET="$(INFERENCE_TARGET)" \
	INFERENCE_MANIFESTS="$(INFERENCE_MANIFESTS)" AIPERF_IMAGE_TAG="$(AIPERF_IMAGE_TAG)" \
	BENCHMARK_CACHE_POLICY="$(CACHE_POLICY)" \
	./scripts/run-benchmark.py

benchmark-suite: ## Measure all variants, REPETITIONS=3
	python3 scripts/run-benchmark-suite.py --backend "$(INFERENCE_BACKEND)" --repetitions "$(REPETITIONS)" \
	  --image-tag "$(IMAGE_TAG)" --benchmark-image "local/aiperf:$(AIPERF_IMAGE_TAG)" \
	  $(if $(INFERENCE_NODE),--inference-node "$(INFERENCE_NODE)") $(if $(BENCHMARK_NODE),--benchmark-node "$(BENCHMARK_NODE)")
