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
_active_client=""
_cleanup_held=""
PGCONNECT_TIMEOUT=5
export PGCONNECT_TIMEOUT

stop_active_client() {
    if test -n "$_active_client"; then
        trap '' INT TERM
        kill -s TERM -- "-$_active_client" 2>/dev/null || kill -s TERM "$_active_client" 2>/dev/null || :
        for _tick in 1 2 3 4 5 6 7 8 9 10; do
            kill -s 0 -- "-$_active_client" 2>/dev/null || break
            sleep 0.1
        done
        kill -s KILL -- "-$_active_client" 2>/dev/null || :
        kill -s KILL "$_active_client" 2>/dev/null || :
        wait "$_active_client" 2>/dev/null || :
        for _tick in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
            if ! kill -s 0 -- "-$_active_client" 2>/dev/null; then
                _active_client=""
                return 0
            fi
            sleep 0.1
        done
        _active_client=""
        _cleanup_held="group-exit-unconfirmed"
        return 1
    fi
}

run_client() {
    {
        setsid "$@" <&9 9<&- &
        _active_client=$!
    } 9<&0
    if wait "$_active_client"; then
        _client_status=0
    else
        _client_status=$?
    fi
    if kill -s 0 -- "-$_active_client" 2>/dev/null; then
        stop_active_client || :
        return 1
    fi
    _active_client=""
    return "$_client_status"
}

secret_cleanup() {
    stop_active_client || :
    if test -n "$_cleanup_held"; then
        printf '%s\n' 'Client-group exit remains unconfirmed; protected temporary files await operator recovery.' >&2
        return
    fi
    if test -n "$_secret_workspace"; then
        rm -rf -- "$_secret_workspace"
    fi
    unset _secret_value
}
trap 'secret_cleanup' EXIT
trap 'stop_active_client || :; exit 130' INT
trap 'stop_active_client || :; exit 143' TERM

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
    run_client psql --no-psqlrc --set=ON_ERROR_STOP=1 "$@" > /dev/null 2>&1 || secret_failure
}

public_psql() {
    run_client psql --no-psqlrc --set=ON_ERROR_STOP=1 "$@" \
        > "$_secret_workspace/public.out" 2>/dev/null || secret_failure
    _public_result="$(cat -- "$_secret_workspace/public.out")"
}
