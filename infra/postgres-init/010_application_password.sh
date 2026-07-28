#!/bin/sh
set -eu

application_password="$(tr -d '\r\n' < /run/secrets/postgres_app_password)"
outbox_password="$(tr -d '\r\n' < /run/secrets/postgres_outbox_password)"
evidence_password="$(tr -d '\r\n' < /run/secrets/postgres_evidence_password)"
migrator_password="$(tr -d '\r\n' < /run/secrets/postgres_migrator_password)"

psql --set=ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=application_password="$application_password" \
    --set=outbox_password="$outbox_password" \
    --set=evidence_password="$evidence_password" \
    --set=migrator_password="$migrator_password" <<'SQL'
select format('alter role laboratory_app password %L', :'application_password') \gexec
select format('alter role laboratory_outbox_worker password %L', :'outbox_password') \gexec
select format('alter role laboratory_evidence_writer password %L', :'evidence_password') \gexec
select format('alter role laboratory_migrator password %L', :'migrator_password') \gexec
SQL
