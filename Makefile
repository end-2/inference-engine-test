.PHONY: help up down test status

help:
	@echo "Targets:"
	@echo "  up       Create or reuse the local Kubernetes cluster"
	@echo "  down     Delete the local Kubernetes cluster"
	@echo "  test     Run a no-GPU smoke Job with DNS lookup"
	@echo "  status   Show nodes and pods"

up:
	./scripts/local-k8s.sh up

down:
	./scripts/local-k8s.sh down

test:
	./scripts/local-k8s.sh test

status:
	./scripts/local-k8s.sh status
