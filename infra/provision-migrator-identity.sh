#!/bin/sh
set -eu
. "${LIMS_SECRET_HELPER:-/usr/local/lib/lims/secret-files.sh}"
prepare_password_file laboratory_bootstrap postgres_password laboratory_migrator postgres_migrator_password

private_psql --file=/workspace/provision_cluster_roles.sql
{
    printf '%s\n' "set log_statement = 'none';" "set log_min_error_statement = 'panic';" \
        "set log_min_duration_statement = -1;" "set log_parameter_max_length_on_error = 0;"
    emit_secret_setting migrator_password postgres_migrator_password
    cat <<'SQL'
select pg_catalog.format(
    'alter role laboratory_migrator password %L',
    :'migrator_password'
) \gexec
SQL
} > "$_secret_workspace/input.sql"
private_psql < "$_secret_workspace/input.sql"

role_attributes="$(
    public_psql --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="select rolcanlogin::text || ':' || rolsuper::text || ':' || rolcreatedb::text || ':' || rolcreaterole::text || ':' || rolinherit::text || ':' || rolbypassrls::text from pg_catalog.pg_roles where rolname = 'laboratory_migrator'"
)"
test "$role_attributes" = "true:false:false:false:false:false"

membership_options="$(
    public_psql --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="select membership.admin_option::text || ':' || membership.inherit_option::text || ':' || membership.set_option::text from pg_catalog.pg_auth_members as membership join pg_catalog.pg_roles as granted_role on granted_role.oid = membership.roleid join pg_catalog.pg_roles as member_role on member_role.oid = membership.member where granted_role.rolname = 'laboratory_owner' and member_role.rolname = 'laboratory_migrator'"
)"
test "$membership_options" = "false:false:true"

ownership_transfer_options="$(
    public_psql --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="select membership.admin_option::text || ':' || membership.inherit_option::text || ':' || membership.set_option::text from pg_catalog.pg_auth_members as membership join pg_catalog.pg_roles as granted_role on granted_role.oid = membership.roleid join pg_catalog.pg_roles as member_role on member_role.oid = membership.member where granted_role.rolname = 'laboratory_outbox_authority' and member_role.rolname = 'laboratory_owner'"
)"
test "$ownership_transfer_options" = "false:false:true"

database_role_setting="$(
    public_psql --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="select configuration.value from pg_catalog.pg_db_role_setting as role_setting join pg_catalog.pg_roles as member_role on member_role.oid = role_setting.setrole join pg_catalog.pg_database as target_database on target_database.oid = role_setting.setdatabase cross join lateral pg_catalog.unnest(role_setting.setconfig) as configuration(value) where member_role.rolname = 'laboratory_migrator' and target_database.datname = pg_catalog.current_database() and configuration.value like 'role=%'"
)"
test "$database_role_setting" = "role=laboratory_owner"

startup_identity="$(
    public_psql \
        --username=laboratory_migrator \
        --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="select session_user || ':' || current_user || ':' || current_setting('role')"
)"
test "$startup_identity" = "laboratory_migrator:laboratory_owner:laboratory_owner"
