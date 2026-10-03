#!/bin/sh
# Render completely before applying or deleting any resources.
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -ge 2 ] || die "Usage: $0 apply|delete|render CHART_OR_VALUES_FILE [HELM_TEMPLATE_ARGS...]"
action=$1
shift
case $action in
    render) exec "$ROOT/scripts/render-k8s.sh" "$@" ;;
    apply|delete) ;;
    *) die "Unknown action: $action" ;;
esac
manifest=$(mktemp "${TMPDIR:-/tmp}/inference-manifests.XXXXXX")
trap 'rm -f "$manifest"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
"$ROOT/scripts/render-k8s.sh" "$@" > "$manifest"
"${LOCAL_K8S_SCRIPT:-$ROOT/scripts/local-k8s.sh}" kubectl "$action" -f "$manifest"
