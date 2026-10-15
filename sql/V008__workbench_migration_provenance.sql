-- TARGET: each new workbench result retains its execution-time migration head.
-- Deployment completes Flyway migration and validation before workbench admission.

set local lock_timeout = '30s';
set local statement_timeout = '5min';

create function laboratory_security.workbench_migration_head()
returns text
language plpgsql
stable
security definer
set search_path = pg_catalog, pg_temp
as $function$
declare
    row_count bigint;
    distinct_versions bigint;
    first_version text;
    last_version text;
    complete_sql_history boolean;
begin
    perform laboratory_security.authorized_tenant_id();
    if pg_catalog.to_regclass('public.flyway_schema_history') is null then
        raise exception using errcode = '55000',
            message = 'workbench provenance requires validated Flyway history';
    end if;

    select count(*), count(distinct version), min(version), max(version),
           bool_and((success and type = 'SQL' and checksum is not null
                     and version ~ '^[0-9]{3}$'
                     and script like 'V' || version || '__%.sql') is true)
      into row_count, distinct_versions, first_version, last_version,
           complete_sql_history
      from public.flyway_schema_history;

    if complete_sql_history is distinct from true
       or row_count < 8 or row_count > 999
       or row_count <> distinct_versions or first_version <> '001' then
        raise exception using errcode = '55000',
            message = 'workbench provenance requires a complete successful SQL history';
    end if;
    if row_count <> last_version::integer then
        raise exception using errcode = '55000',
            message = 'workbench provenance requires a contiguous migration history';
    end if;
    return last_version;
end;
$function$;

alter function laboratory_security.workbench_migration_head()
    owner to laboratory_owner;
revoke all on function laboratory_security.workbench_migration_head() from public;
grant execute on function laboratory_security.workbench_migration_head()
    to laboratory_app;
