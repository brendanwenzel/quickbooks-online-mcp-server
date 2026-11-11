#!/usr/bin/env bash
set -euo pipefail
[[ $(id -un) == coral ]] || { echo 'Build as coral.' >&2; exit 1; }
[[ $# == 1 && ! -e $1 && ! -L $1 ]] || { echo 'Usage: build-release.sh NEW_DIRECTORY' >&2; exit 1; }
app=$(cd "$(dirname "$0")/.." && pwd)
repo=$(git -C "$app" rev-parse --show-toplevel)
commit=$(git -C "$repo" rev-parse HEAD)
[[ $commit == "$(git -C "$repo" rev-parse origin/main)" && -z $(git -C "$repo" status --porcelain) ]] || { echo 'Build only from clean published main.' >&2; exit 1; }
target=$(rustc -vV | awk '$1 == "host:" {print $2}')
[[ $target == "$(uname -m)-unknown-linux-gnu" ]]
output=$(realpath -m "$1")
parent=${output%/*}
[[ -d $parent ]]
stage=$(mktemp -d "$parent/.qbo-package.XXXXXXXX")
cleanup() { local status=$?; rm -f -- "$stage/qbo-mcp-keepalive" "$stage/source-commit" "$stage/build-target" "$stage/baseline-sha256" "$stage/manifest.sha256"; rmdir "$stage" 2>/dev/null || true; exit "$status"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
QBO_BUILD_COMMIT=$commit QBO_BUILD_TARGET=$target cargo build --locked --release --manifest-path "$app/Cargo.toml" --bin qbo-mcp-keepalive --target "$target" --target-dir "$app/target"
install -m 0755 "$app/target/$target/release/qbo-mcp-keepalive" "$stage/qbo-mcp-keepalive"
printf '%s\n' "$commit" > "$stage/source-commit"
printf '%s\n' "$target" > "$stage/build-target"
printf '%s\n' c3d00adfba5b2311c5dd39ed608c19cd31dff7c8be06a12325fb556d4bc6dc46 > "$stage/baseline-sha256"
expected=$(printf 'qbo-mcp-keepalive: configuration via QBO_KEEPALIVE_CONFIG; no work performed\nsource=%s\ntarget=%s' "$commit" "$target")
[[ $("$stage/qbo-mcp-keepalive" --help) == "$expected" ]]
(cd "$stage" && sha256sum qbo-mcp-keepalive source-commit build-target baseline-sha256 > manifest.sha256)
chmod 0755 "$stage"
chmod 0644 "$stage/source-commit" "$stage/build-target" "$stage/baseline-sha256" "$stage/manifest.sha256"
[[ ! -e $output && ! -L $output ]]
mv -T --no-clobber "$stage" "$output"
[[ ! -e $stage && ! -L $stage ]]
printf 'Prepared %s from %s; only help invoked.\n' "$output" "$commit"
