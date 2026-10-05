#!/bin/sh
set -eu
. "${LIMS_SECRET_HELPER:-/usr/local/lib/lims/secret-files.sh}"
prepare_password_file laboratory_app postgres_app_password
public_psql --tuples-only --no-align --command="select current_user, rolsuper, rolbypassrls from pg_roles where rolname = current_user"
identity="$_public_result"
test "$identity" = "laboratory_app|f|f" || secret_failure
printf '%s\n' 'Application role boundary observed.'
