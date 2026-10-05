#!/bin/sh
# Local generated credentials use a bounded, shell- and property-safe alphabet.
set +x
set -eu
umask 077
unset PGPASSWORD FLYWAY_PASSWORD
LC_ALL=C
export LC_ALL
_secret_workspace=""
_secret_value=""

secret_cleanup() {
    if test -n "$_secret_workspace"; then
        rm -rf -- "$_secret_workspace"
    fi
    unset _secret_value
}
trap 'secret_cleanup' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

secret_failure() {
    printf '%s\n' 'Local credential preparation stopped; preserve state and use the recovery guide.' >&2
    exit 1
}

read_secret() {
    _secret_path="${LIMS_SECRET_DIR:-/run/secrets}/$1"
    test -f "$_secret_path" && test ! -L "$_secret_path" || secret_failure
    _secret_size="$(wc -c < "$_secret_path")"
    test "$_secret_size" -gt 0 && test "$_secret_size" -le 129 || secret_failure
    _secret_value="$(cat -- "$_secret_path")"
    case "$_secret_value" in
        ""|*[!a-zA-Z0-9._~-]*) secret_failure ;;
    esac
}

secret_workspace() {
    _secret_workspace="$(mktemp -d "${TMPDIR:-/tmp}/lims-credentials.XXXXXXXX")"
}

prepare_password_file() {
    secret_workspace
    PGPASSFILE="$_secret_workspace/pgpass"
    : > "$PGPASSFILE"
    while test "$#" -gt 0; do
        _secret_role="$1"
        read_secret "$2"
        printf '*:*:*:%s:%s\n' "$_secret_role" "$_secret_value" >> "$PGPASSFILE"
        shift 2
    done
    unset _secret_value
    export PGPASSFILE
}

emit_secret_setting() {
    read_secret "$2"
    printf "\\set %s '%s'\n" "$1" "$_secret_value"
    unset _secret_value
}

private_psql() {
    psql --no-psqlrc --set=ON_ERROR_STOP=1 "$@" > /dev/null 2>&1 || secret_failure
}

public_psql() {
    if _public_result="$(psql --no-psqlrc --set=ON_ERROR_STOP=1 "$@" 2>/dev/null)"; then
        printf '%s\n' "$_public_result"
    else
        secret_failure
    fi
}
