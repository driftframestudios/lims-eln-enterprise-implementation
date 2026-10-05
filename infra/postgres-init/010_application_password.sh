#!/bin/sh
set -eu
. "${LIMS_SECRET_HELPER:-/usr/local/lib/lims/secret-files.sh}"
prepare_password_file laboratory_bootstrap postgres_password
read_secret postgres_tenant_hmac_key
test "${#_secret_value}" -eq 64 || secret_failure
case "$_secret_value" in *[!a-f0-9]*) secret_failure ;; esac
unset _secret_value

{
    printf '%s\n' "set log_statement = 'none';" "set log_min_error_statement = 'panic';" \
        "set log_min_duration_statement = -1;" "set log_parameter_max_length_on_error = 0;"
    emit_secret_setting application_password postgres_app_password
    emit_secret_setting outbox_password postgres_outbox_password
    emit_secret_setting recovery_password postgres_recovery_password
    emit_secret_setting evidence_password postgres_evidence_password
    emit_secret_setting tenant_hmac_key postgres_tenant_hmac_key
    cat <<'SQL'
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
insert into public.tenant (tenant_id, display_name)
values ('SYN-TENANT-A', 'Local Golden Specimen tenant')
on conflict (tenant_id) do nothing;
commit;
SQL
} > "$_secret_workspace/input.sql"
private_psql < "$_secret_workspace/input.sql" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"
