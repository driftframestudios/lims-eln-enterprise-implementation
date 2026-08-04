do $flyway_connection$
begin
    if session_user <> 'laboratory_migrator'
       or current_user <> 'laboratory_owner'
       or pg_catalog.current_setting('role', true) <> 'laboratory_owner' then
        raise exception using
            errcode = '42501',
            message = 'Flyway requires the configured migrator and owner roles';
    end if;
end;
$flyway_connection$;
