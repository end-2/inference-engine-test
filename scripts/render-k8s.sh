#!/bin/sh
# Render a chart or one of its values files without contacting a cluster.
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
PATH="${LOCAL_K8S_BIN_DIR:-$ROOT/.bin}:$PATH"
export PATH
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -gt 0 ] || die "Usage: $0 CHART_OR_VALUES_FILE [HELM_TEMPLATE_ARGS...]"
target=$1
shift
if [ -d "$target" ]; then
    chart=$target
else
    [ -r "$target" ] || die "Cannot read Helm values: $target"
    chart=$(CDPATH='' cd -- "$(dirname -- "$target")" && pwd)
    while [ ! -f "$chart/Chart.yaml" ] && [ "$chart" != / ]; do
        chart=$(dirname -- "$chart")
    done
    set -- -f "$target" "$@"
fi
[ -f "$chart/Chart.yaml" ] || die "No Helm chart found for $target"
command -v helm >/dev/null 2>&1 || die "Missing helm. Run ./scripts/local-k8s.sh install."
exec helm template inference-test "$chart" "$@"
