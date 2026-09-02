#!/bin/sh
set -eu

application_password="$(tr -d '\r\n' < /run/secrets/postgres_app_password)"
PGPASSWORD="$(tr -d '\r\n' < /run/secrets/postgres_password)"
outbox_password="$(tr -d '\r\n' < /run/secrets/postgres_outbox_password)"
recovery_password="$(tr -d '\r\n' < /run/secrets/postgres_recovery_password)"
evidence_password="$(tr -d '\r\n' < /run/secrets/postgres_evidence_password)"
tenant_hmac_key="$(tr -d '\r\n' < /run/secrets/postgres_tenant_hmac_key)"
export PGPASSWORD

psql --set=ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=application_password="$application_password" \
    --set=outbox_password="$outbox_password" \
    --set=recovery_password="$recovery_password" \
    --set=evidence_password="$evidence_password" \
    --set=tenant_hmac_key="$tenant_hmac_key" <<'SQL'
begin;
select format('alter role laboratory_app password %L', :'application_password') \gexec
select format('alter role laboratory_outbox_worker password %L', :'outbox_password') \gexec
select format(
    'alter role laboratory_outbox_recovery_operator password %L',
    :'recovery_password'
) \gexec
select format('alter role laboratory_evidence_writer password %L', :'evidence_password') \gexec
select count(*) as tenant_key_matches
  from laboratory_security.tenant_context_key
 where key_id = 'local-compose-v1'
   and secret_material = decode(:'tenant_hmac_key', 'hex')
\gset
\if :tenant_key_matches
\echo 'tenant verification key already matches local-compose-v1'
\else
insert into laboratory_security.tenant_context_key (
    key_id,
    secret_material,
    valid_from_utc,
    valid_until_utc
) values (
    'local-compose-v1',
    decode(:'tenant_hmac_key', 'hex'),
    '2025-01-01T00:00:00Z',
    '2036-01-01T00:00:00Z'
);
\endif
commit;
SQL
