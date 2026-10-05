#!/bin/sh
set -eu
. "${LIMS_SECRET_HELPER:-/usr/local/lib/lims/secret-files.sh}"
secret_workspace
read_secret postgres_migrator_password
printf 'flyway.password=%s\n' "$_secret_value" > "$_secret_workspace/flyway.conf"
unset _secret_value
exec 3< "$_secret_workspace/flyway.conf"
rm -- "$_secret_workspace/flyway.conf"
if flyway -workingDirectory=/flyway/project \
    -configFiles=/flyway/project/flyway.conf,- "$@" <&3 3<&- > /dev/null 2>&1; then
    printf '%s\n' 'Migration command completed.'
else
    printf '%s\n' 'Migration command stopped; retain the database and inspect migration status with the recovery guide.' >&2
    exit 1
fi
exec 3<&-
