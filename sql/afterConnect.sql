do $flyway_connection_authority$
begin
    if session_user <> 'laboratory_migrator' then
        raise exception using
            errcode = '42501',
            message = 'Flyway requires the released laboratory_migrator login';
    end if;
    if current_user <> 'laboratory_owner' then
        raise exception using
            errcode = '42501',
            message = 'Flyway requires the released laboratory_owner migration role';
    end if;
    if not exists (
        select 1
          from pg_catalog.pg_db_role_setting as role_setting
          join pg_catalog.pg_roles as member_role
            on member_role.oid = role_setting.setrole
          join pg_catalog.pg_database as target_database
            on target_database.oid = role_setting.setdatabase
         cross join lateral pg_catalog.unnest(role_setting.setconfig)
            as configuration(value)
         where member_role.rolname = 'laboratory_migrator'
           and target_database.datname = pg_catalog.current_database()
           and configuration.value = 'role=laboratory_owner'
    ) then
        raise exception using
            errcode = '42501',
            message = 'Flyway requires the released database-scoped role setting';
    end if;
end;
$flyway_connection_authority$;
