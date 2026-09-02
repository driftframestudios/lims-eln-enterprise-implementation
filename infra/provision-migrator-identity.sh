#!/bin/sh
set -eu

PGPASSWORD="$(tr -d '\r\n' < /run/secrets/postgres_password)"
migrator_password="$(tr -d '\r\n' < /run/secrets/postgres_migrator_password)"
export PGPASSWORD

psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --file=/workspace/provision_cluster_roles.sql

psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --set=migrator_password="$migrator_password" <<'SQL'
select pg_catalog.format(
    'alter role laboratory_migrator password %L',
    :'migrator_password'
) \gexec
SQL

role_attributes="$(
    psql --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="select rolcanlogin::text || ':' || rolsuper::text || ':' || rolcreatedb::text || ':' || rolcreaterole::text || ':' || rolinherit::text || ':' || rolbypassrls::text from pg_catalog.pg_roles where rolname = 'laboratory_migrator'"
)"
test "$role_attributes" = "true:false:false:false:false:false"

membership_options="$(
    psql --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="select membership.admin_option::text || ':' || membership.inherit_option::text || ':' || membership.set_option::text from pg_catalog.pg_auth_members as membership join pg_catalog.pg_roles as granted_role on granted_role.oid = membership.roleid join pg_catalog.pg_roles as member_role on member_role.oid = membership.member where granted_role.rolname = 'laboratory_owner' and member_role.rolname = 'laboratory_migrator'"
)"
test "$membership_options" = "false:false:true"

ownership_transfer_options="$(
    psql --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="select membership.admin_option::text || ':' || membership.inherit_option::text || ':' || membership.set_option::text from pg_catalog.pg_auth_members as membership join pg_catalog.pg_roles as granted_role on granted_role.oid = membership.roleid join pg_catalog.pg_roles as member_role on member_role.oid = membership.member where granted_role.rolname = 'laboratory_outbox_authority' and member_role.rolname = 'laboratory_owner'"
)"
test "$ownership_transfer_options" = "false:false:true"

database_role_setting="$(
    psql --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="select configuration.value from pg_catalog.pg_db_role_setting as role_setting join pg_catalog.pg_roles as member_role on member_role.oid = role_setting.setrole join pg_catalog.pg_database as target_database on target_database.oid = role_setting.setdatabase cross join lateral pg_catalog.unnest(role_setting.setconfig) as configuration(value) where member_role.rolname = 'laboratory_migrator' and target_database.datname = pg_catalog.current_database() and configuration.value like 'role=%'"
)"
test "$database_role_setting" = "role=laboratory_owner"

startup_identity="$(
    PGPASSWORD="$migrator_password" psql --no-psqlrc \
        --username=laboratory_migrator \
        --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="select session_user || ':' || current_user || ':' || current_setting('role')"
)"
test "$startup_identity" = "laboratory_migrator:laboratory_owner:laboratory_owner"
