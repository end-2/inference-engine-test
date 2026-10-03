.PHONY: help install up down test status download-model download-tokenizer build-image load-image build-benchmark-image load-benchmark-image render deploy benchmark benchmark-suite pd-deploy pd-benchmark

IMAGE_TAG ?= 0.1.0
DEVICE ?= cpu
GPU_SHARING ?= none
MPS_REPLICAS ?= 2
export GPU_SHARING MPS_REPLICAS
ifneq ($(filter $(DEVICE),cpu gpu),$(DEVICE))
$(error DEVICE must be cpu or gpu)
endif
AIPERF_IMAGE_TAG ?= 0.12.0
VARIANT ?= transformers-base
INFERENCE_BACKEND ?= $(if $(filter transformers-mamba-%,$(VARIANT)),mamba,$(if $(filter transformers-%,$(VARIANT)),transformers,llamacpp))
INFERENCE_IMAGE ?= local/$(VARIANT)$(if $(filter gpu,$(DEVICE)),-gpu):$(IMAGE_TAG)
INFERENCE_CONTEXT ?= src
INFERENCE_TARGET ?= $(VARIANT)$(if $(filter gpu,$(DEVICE)),-gpu)
INFERENCE_MANIFESTS ?= k8s/inference/profiles/$(VARIANT)-$(DEVICE).yaml
CACHE_POLICY ?= $(if $(filter transformers-enhanced-cache transformers-mamba-cache,$(VARIANT)),clear-before-sweep,preserve)
REPETITIONS ?= 3
BENCHMARK_CONFIG ?=
CUDA_GRAPH ?=
INFERENCE_NODE ?=
BENCHMARK_NODE ?=
PD_MODE ?= aggregated
PD_BENCHMARK_CONFIG ?= benchmarks/pd.json

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Download pinned kind, kubectl and Helm into .bin
up: ## Create or reuse the local cluster
down: ## Delete the local cluster
test: ## Run the cluster smoke test
status: ## Show nodes and pods
install up down test status:
	./scripts/local-k8s$(if $(filter gpu,$(DEVICE)),-gpu).sh $@

download-model: ## Download the selected model
	$(if $(filter mamba,$(INFERENCE_BACKEND)),./scripts/download-transformers-model.sh mamba-130m,$(if $(filter transformers,$(INFERENCE_BACKEND)),./scripts/download-transformers-model.sh,./scripts/download-model-llamacpp.sh))

download-tokenizer: ## Prepare the benchmark tokenizer
	$(if $(filter mamba,$(INFERENCE_BACKEND)),./scripts/download-transformers-model.sh mamba-130m,$(if $(filter transformers,$(INFERENCE_BACKEND)),./scripts/download-transformers-model.sh,./scripts/download-tokenizer-llamacpp.sh))

build-image: ## Build the selected VARIANT
	IMAGE_TAG=$(IMAGE_TAG) DEVICE=$(DEVICE) ./scripts/build-inference-images.sh $(VARIANT)

load-image: ## Load the selected VARIANT into kind
	IMAGE_TAG=$(IMAGE_TAG) DEVICE=$(DEVICE) ./scripts/load-inference-images.sh $(VARIANT)

render: ## Render the selected VARIANT through Helm without a cluster
	@./scripts/render-k8s.sh "$(INFERENCE_MANIFESTS)" --set-string "container.image=$(INFERENCE_IMAGE)"

deploy: ## Apply the selected VARIANT to the local cluster
	LOCAL_K8S_SCRIPT="$(CURDIR)/scripts/local-k8s$(if $(filter gpu,$(DEVICE)),-gpu).sh" \
	./scripts/k8s.sh apply "$(INFERENCE_MANIFESTS)" --set-string "container.image=$(INFERENCE_IMAGE)"

pd-deploy: ## Deploy aggregated or disaggregated inference on the MPS cluster
	GPU_SHARING=mps ./scripts/deploy-pd.sh "$(PD_MODE)"

pd-benchmark: ## Compare PD topologies across input, output, and concurrency sweeps
	python3 scripts/benchmark-pd.py --config "$(PD_BENCHMARK_CONFIG)"

build-benchmark-image: ## Build the AIPerf image
	AIPERF_IMAGE_TAG=$(AIPERF_IMAGE_TAG) ./scripts/build-benchmark-images.sh

load-benchmark-image: ## Load the AIPerf image into kind
	AIPERF_IMAGE_TAG=$(AIPERF_IMAGE_TAG) DEVICE=$(DEVICE) ./scripts/load-benchmark-images.sh

benchmark: ## Measure the selected VARIANT
	BENCHMARK_DEVICE="$(DEVICE)" INFERENCE_BACKEND="$(INFERENCE_BACKEND)" \
	INFERENCE_IMAGE="$(INFERENCE_IMAGE)" INFERENCE_CONTEXT="$(INFERENCE_CONTEXT)" \
	INFERENCE_TARGET="$(INFERENCE_TARGET)" \
	INFERENCE_MANIFESTS="$(INFERENCE_MANIFESTS)" AIPERF_IMAGE_TAG="$(AIPERF_IMAGE_TAG)" \
	BENCHMARK_CACHE_POLICY="$(CACHE_POLICY)" \
	./scripts/run-benchmark.py $(if $(CUDA_GRAPH),--cuda-graph "$(CUDA_GRAPH)")

benchmark-suite: ## Measure all variants, REPETITIONS=3
	python3 scripts/run-benchmark-suite.py --backend "$(INFERENCE_BACKEND)" --device "$(DEVICE)" --repetitions "$(REPETITIONS)" \
	  --image-tag "$(IMAGE_TAG)" --benchmark-image "local/aiperf:$(AIPERF_IMAGE_TAG)" \
	  $(if $(BENCHMARK_CONFIG),--config "$(BENCHMARK_CONFIG)") \
	  $(if $(INFERENCE_NODE),--inference-node "$(INFERENCE_NODE)") $(if $(BENCHMARK_NODE),--benchmark-node "$(BENCHMARK_NODE)")
