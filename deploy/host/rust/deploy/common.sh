#!/usr/bin/env bash
# Fixed production paths. Tests transform copies in disposable directories.
base=/srv/apps/quickbooks-mcp/keepalive-rust
unit=qbo-mcp-keepalive.service
fragment=/etc/systemd/system/qbo-mcp-keepalive.service
dropin=/etc/systemd/system/qbo-mcp-keepalive.service.d/20-rust-release.conf
python=/srv/apps/quickbooks-mcp/bin/keepalive.py
old="/usr/bin/python3 $python"
new="$base/current/qbo-mcp-keepalive"
baseline=c3d00adfba5b2311c5dd39ed608c19cd31dff7c8be06a12325fb556d4bc6dc46
unit_baseline=a9e1b831b6a767c1d6b4394f5b154ade5269d00285e4ecd0a7c3640f43318875
files=(qbo-mcp-keepalive source-commit build-target baseline-sha256 manifest.sha256)
loaded() {
    local value path argv
    value=$(systemctl show "$unit" -p ExecStart --value)
    [[ $(grep -o '{' <<< "$value" | wc -l) == 1 ]] || return 1
    path=$(sed -n 's/^{ path=\([^ ;]*\) ;.*$/\1/p' <<< "$value")
    argv=$(sed -n 's/^.*argv\[\]=\([^;]*\) ; ignore_errors=.*$/\1/p' <<< "$value")
    [[ -n $path && $path == "${argv%% *}" ]] || return 1
    printf '%s\n' "$argv"
}
idle() { [[ $(systemctl show "$unit" -p ActiveState --value) == inactive ]]; }
identity() {
    [[ -f $fragment && ! -L $fragment && -f $python && ! -L $python ]]
    [[ $(sha256sum "$fragment" | cut -d' ' -f1) == "$unit_baseline" && $(sha256sum "$python" | cut -d' ' -f1) == "$baseline" ]]
    [[ $(systemctl show "$unit" -p FragmentPath --value) == "$fragment" && $(systemctl show "$unit" -p DynamicUser --value) == yes ]]
    case $(systemctl is-enabled "$unit" 2>/dev/null || true) in masked|masked-runtime) return 1;; esac
}
manifest() {
    local directory=$1 name
    for name in "${files[@]}"; do [[ -f $directory/$name && ! -L $directory/$name ]] || return 1; done
    [[ $(wc -l < "$directory/manifest.sha256") == 4 ]] || return 1
    awk 'NF!=2 || length($1)!=64 || $1 !~ /^[a-f0-9]+$/ || ($2!="qbo-mcp-keepalive" && $2!="source-commit" && $2!="build-target" && $2!="baseline-sha256") {exit 1} {seen[$2]++} END {if(length(seen)!=4) exit 1; for(n in seen) if(seen[n]!=1) exit 1}' "$directory/manifest.sha256" || return 1
    (cd "$directory" && sha256sum --check manifest.sha256) || return 1
}
help_matches() {
    local directory=$1 commit=$2 target=$3 actual expected
    actual=$(runuser -u coral -- "$directory/qbo-mcp-keepalive" --help)
    expected=$(printf 'qbo-mcp-keepalive: configuration via QBO_KEEPALIVE_CONFIG; no work performed\nsource=%s\ntarget=%s' "$commit" "$target")
    [[ $actual == "$expected" ]]
}
