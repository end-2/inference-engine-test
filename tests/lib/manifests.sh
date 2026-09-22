# Read only deployable files in the selected directory, excluding scenario patches.
read_manifests() {
    for manifest in "$1"/*.yaml; do
        cat "$manifest" || return
        printf '\n---\n'
    done
}
