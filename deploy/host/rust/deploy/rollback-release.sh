#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 && $# == 1 && $1 =~ ^[a-f0-9]{40}$ && $(hostname) == arbitrum ]] || { echo 'Usage on arbitrum: sudo rollback-release.sh SOURCE_COMMIT' >&2; exit 1; }
source "$(dirname "$0")/common.sh"
release=$base/releases/$1
exec 9>/run/lock/qbo-keepalive-release.lock
flock -n 9
identity
idle
[[ -d $release && ! -L $release && -L $base/current && $(readlink "$base/current") == "$release" && $(loaded) == "$new" ]]
manifest "$release"
[[ $(cat "$release/source-commit") == "$1" && $(cat "$release/baseline-sha256") == "$baseline" ]]
[[ -f $dropin && ! -L $dropin ]]
expected=$(printf '[Service]\nExecStart=\nExecStart=%s' "$new")
[[ $(cat "$dropin") == "$expected" ]]
saved=$dropin.rollback-$1
link=$base/.rollback-$1
[[ ! -e $link && ! -L $link ]]
[[ ! -e $saved && ! -L $saved ]]
changed=0
verified=0
cleanup() {
    local status=$?
    set +e
    if (( changed && ! verified )); then
        if idle && [[ -f $saved && ! -L $saved ]]; then
            if [[ ! -e $base/current && ! -L $base/current ]]; then
                ln -s "$release" "$link" && mv -Tf "$link" "$base/current"
            fi
            [[ $(readlink "$base/current") == "$release" ]] || { echo 'Current binding changed; manual recovery required.' >&2; exit 1; }
            mv -Tf "$saved" "$dropin"
            if systemctl daemon-reload && [[ $(loaded) == "$new" ]]; then echo 'Rollback failed; restored Rust binding.' >&2;
            else echo 'Binding recovery failed; immutable release remains installed.' >&2; fi
        else echo 'Service became active; retained files for safe manual recovery.' >&2; fi
        status=1
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
idle
[[ $(loaded) == "$new" ]]
changed=1
mv -T "$dropin" "$saved"
systemctl daemon-reload
[[ $(loaded) == "$old" ]]
[[ $(readlink "$base/current") == "$release" ]]
rm -- "$base/current"
verified=1
rm -- "$saved"
echo 'Restored Python watchdog binding; no job, timer or container invoked. Rust release retained.'
