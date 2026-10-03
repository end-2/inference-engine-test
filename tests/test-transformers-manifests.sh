#!/bin/sh
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
. "$ROOT/config/models/smollm2-135m-transformers.env"
PATH="${LOCAL_K8S_BIN_DIR:-$ROOT/.bin}:$PATH"
export PATH
KUBECTL=${KUBECTL:-kubectl}
KUBECONFIG=$("${LOCAL_K8S_SCRIPT:-$ROOT/scripts/local-k8s.sh}" kubeconfig)
export KUBECONFIG
rendered=$(mktemp -d "${TMPDIR:-/tmp}/transformers-manifests.XXXXXX")
trap 'rm -rf "$rendered"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
for variant in base enhanced-batch enhanced-cache; do
    "$ROOT/scripts/render-k8s.sh" "$ROOT/k8s/inference/profiles/transformers-$variant-cpu.yaml" > "$rendered/$variant.yaml"
    "$KUBECTL" create --dry-run=client --validate=false -f "$rendered/$variant.yaml" -o json > "$rendered/$variant.json"
done
"$ROOT/scripts/render-k8s.sh" "$ROOT/k8s/aiperf/profiles/smollm2.yaml" > "$rendered/aiperf.yaml"
"$KUBECTL" create --dry-run=client --validate=false -f "$rendered/aiperf.yaml" -o json > "$rendered/aiperf.json"
python3 - "$rendered" "$SERVED_MODEL_NAME" "$MODEL_DIRECTORY" <<'PY'
import json
from pathlib import Path
import sys
root, model, directory = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
for variant in ['base', 'enhanced-batch', 'enhanced-cache', 'aiperf']:
    text = (root / f'{variant}.json').read_text().strip()
    items = []
    while text:
        data, end = json.JSONDecoder().raw_decode(text)
        items.extend(data.get('items', [data]))
        text = text[end:].strip()
    kind = 'Job' if variant == 'aiperf' else 'Deployment'
    workload = next(item for item in items if item['kind'] == kind)
    spec = workload['spec']['template']['spec']
    container = spec['containers'][0]
    resources = container['resources']
    assert resources['requests'] == resources['limits']
    assert 'nvidia.com/gpu' not in resources['limits']
    args = container['args']
    if variant == 'aiperf':
        env = {v['name']: v.get('value') for v in container['env']}
        assert workload['metadata']['name'] == 'aiperf-smollm2'
        assert env['MODEL_ID'] == model
        assert env['API_URL'] == 'http://transformers-base:8000'
        assert env['CONCURRENCIES'] == '1,2,4,8'
        assert args[args.index('--tokenizer')+1] == '/tokenizer'
        assert args[args.index('--request-count')+1] == '100'
        volume_name = 'tokenizer'
    else:
        assert args[args.index('--served-model-name')+1] == model
        assert args[args.index('--n-threads')+1] == '4'
        assert resources['limits'] == {'cpu': '8', 'memory': '16Gi'}
        volume_name = 'model'
    mount = next(v for v in container['volumeMounts'] if v['name'] == volume_name)
    assert mount['readOnly']
    volume = next(v for v in spec['volumes'] if v['name'] == volume_name)
    assert volume['hostPath'] == {'path': f'/models/{directory}', 'type': 'Directory'}
print('PASS: SmolLM2 model, tokenizer, threads, sweep and Guaranteed resources')
PY
