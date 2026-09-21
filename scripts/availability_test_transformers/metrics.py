from pathlib import Path
from datetime import datetime, timezone
import concurrent.futures, json, urllib.parse, urllib.request, sys

s = json.loads(Path(sys.argv[1]).read_text())
raw = Path(s["raw"])
out = raw / "prometheus"
out.mkdir(exist_ok=True)
start = datetime.fromisoformat(s["collection_start"]).timestamp()
end = datetime.fromisoformat(
    s.get("experiment_complete", datetime.now(timezone.utc).isoformat())
).timestamp()
queries = {
    "node_ready": 'kube_node_status_condition{condition="Ready"}',
    "node_labels": "kube_node_labels",
    "pod_ready": 'kube_pod_status_ready{namespace="availability-test-transformers"}',
    "pod_info": 'kube_pod_info{namespace="availability-test-transformers"}',
    "pod_phase": 'kube_pod_status_phase{namespace="availability-test-transformers"}',
    "pod_restarts": 'kube_pod_container_status_restarts_total{namespace="availability-test-transformers"}',
    "deployment_available": 'kube_deployment_status_replicas_available{namespace="availability-test-transformers"}',
    "ready_endpoints": 'availability:service_ready_endpoints{namespace="availability-test-transformers"}',
    "unready_endpoints": 'availability:service_unready_endpoints{namespace="availability-test-transformers"}',
    "endpoints": 'kube_endpointslice_endpoints{namespace="availability-test-transformers"}',
    "up": "up",
    "requests": "transformers_requests_total",
    "request_rate": "sum by (outcome) (rate(transformers_requests_total[1m]))",
    "inflight": "transformers_requests_in_flight",
    "duration_p95": 'histogram_quantile(0.95,sum by (le)(rate(transformers_request_duration_seconds_bucket{outcome="success"}[1m])))',
    "duration_buckets": "transformers_request_duration_seconds_bucket",
    "duration_sum": "transformers_request_duration_seconds_sum",
    "duration_count": "transformers_request_duration_seconds_count",
    "ttft_buckets": "transformers_time_to_first_token_seconds_bucket",
    "ttft_p95": "histogram_quantile(0.95,sum by (le)(rate(transformers_time_to_first_token_seconds_bucket[1m])))",
    "tokens": "transformers_tokens_total",
    "scrape_duration": "scrape_duration_seconds",
}


def fetch(item):
    name, q = item
    url = (
        s["prometheus_url"]
        + "/api/v1/query_range?"
        + urllib.parse.urlencode({"query": q, "start": start, "end": end, "step": "5s"})
    )
    data = json.load(urllib.request.urlopen(url, timeout=20))
    assert data["status"] == "success", data
    (out / (name + ".json")).write_text(
        json.dumps(
            {"query": q, "start": start, "end": end, "step_seconds": 5, **data},
            indent=2,
        )
    )
    return name, len(data["data"]["result"])


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    print(list(pool.map(fetch, queries.items())))
(raw / "metric-range.json").write_text(
    json.dumps({"start": start, "end": end, "step_seconds": 5}, indent=2)
)
