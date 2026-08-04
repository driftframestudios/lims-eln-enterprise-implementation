#!/bin/sh
set -eu

application_password="$(tr -d '\r\n' < /run/secrets/postgres_app_password)"
PGPASSWORD="$(tr -d '\r\n' < /run/secrets/postgres_password)"
outbox_password="$(tr -d '\r\n' < /run/secrets/postgres_outbox_password)"
export PGPASSWORD

psql --set=ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=application_password="$application_password" \
    --set=outbox_password="$outbox_password" <<'SQL'
select format('alter role laboratory_app password %L', :'application_password') \gexec
select format('alter role laboratory_outbox_worker password %L', :'outbox_password') \gexec
SQL
