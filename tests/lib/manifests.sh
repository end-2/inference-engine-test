# Render the selected Helm profile without contacting the cluster.
read_manifests() {
    "$ROOT/scripts/render-k8s.sh" "$1"
}
