#!/usr/bin/env bash
# First Rust binding only. No timer, watchdog or container is started.
set -euo pipefail
[[ $EUID == 0 && $# == 1 && $(hostname) == arbitrum ]] || { echo 'Usage on arbitrum: sudo install-release.sh PACKAGE' >&2; exit 1; }
source "$(dirname "$0")/common.sh"
[[ -d $1 && ! -L $1 ]]
package=$(realpath "$1")
[[ $(find "$package" -mindepth 1 -maxdepth 1 | wc -l) == 5 ]]
manifest "$package"
commit=$(cat "$package/source-commit")
target=$(cat "$package/build-target")
[[ $commit =~ ^[a-f0-9]{40}$ && $target == "$(uname -m)-unknown-linux-gnu" && $(cat "$package/baseline-sha256") == "$baseline" ]]
exec 9>/run/lock/qbo-keepalive-release.lock
flock -n 9
identity
idle
[[ $(loaded) == "$old" ]]
release=$base/releases/$commit
pending=$base/.current-$commit
unit_tmp=$dropin.new-$commit
for path in "$release" "$base/current" "$dropin" "$pending" "$unit_tmp"; do [[ ! -e $path && ! -L $path ]]; done
for directory in "$base" "$base/releases" "${dropin%/*}"; do
    if [[ -e $directory || -L $directory ]]; then [[ -d $directory && ! -L $directory && $(stat -c %u "$directory") == 0 && $((8#$(stat -c %a "$directory") & 022)) == 0 ]];
    else install -d -o root -g root -m 0755 "$directory"; fi
done
stage=$(mktemp -d "$base/releases/.stage-$commit.XXXXXXXX")
changed=0
verified=0
cleanup() {
    local status=$?
    set +e
    if (( changed && ! verified )); then
        if idle; then
            rm -f -- "$dropin"
            if systemctl daemon-reload && [[ $(loaded) == "$old" ]]; then
                [[ $(readlink "$base/current") != "$release" ]] || rm -f -- "$base/current"
                echo 'Restored Python binding; no watchdog or timer invoked.' >&2
            else echo 'Rollback verification failed; retained immutable release for recovery.' >&2; fi
        else echo 'Service became active; retained binding and release for safe manual recovery.' >&2; fi
        status=1
    fi
    rm -f -- "$pending" "$unit_tmp"
    if [[ -n $stage && -d $stage ]]; then
        for name in "${files[@]}" previous-exec new-override; do rm -f -- "$stage/$name"; done
        rmdir "$stage" || status=1
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
chmod 0755 "$stage"
install -o root -g root -m 0755 "$package/qbo-mcp-keepalive" "$stage/qbo-mcp-keepalive"
for name in source-commit build-target baseline-sha256 manifest.sha256; do install -o root -g root -m 0644 "$package/$name" "$stage/$name"; done
manifest "$stage"
[[ $(cat "$stage/source-commit") == "$commit" && $(cat "$stage/build-target") == "$target" && $(cat "$stage/baseline-sha256") == "$baseline" ]]
printf '%s\n' "$old" > "$stage/previous-exec"
printf '[Service]\nExecStart=\nExecStart=%s\n' "$new" > "$stage/new-override"
help_matches "$stage" "$commit" "$target"
mv -T --no-clobber "$stage" "$release"
[[ ! -e $stage && ! -L $stage ]]
stage=
identity
idle
[[ $(loaded) == "$old" ]]
ln -s "$release" "$pending"
changed=1
mv -Tf "$pending" "$base/current"
idle
[[ $(loaded) == "$old" ]]
install -o root -g root -m 0644 "$release/new-override" "$unit_tmp"
mv -Tf "$unit_tmp" "$dropin"
systemctl daemon-reload
[[ $(loaded) == "$new" && $(readlink "$base/current") == "$release" ]]
cmp "$dropin" "$release/new-override"
manifest "$release"
help_matches "$release" "$commit" "$target"
verified=1
printf 'Installed %s; only help invoked. Timer, containers and configuration unchanged.\n' "$commit"
