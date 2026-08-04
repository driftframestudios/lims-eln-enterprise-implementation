do $flyway_connection_authority$
begin
    if session_user <> 'laboratory_migrator' then
        raise exception using
            errcode = '42501',
            message = 'Flyway requires the released laboratory_migrator login';
    end if;
end;
$flyway_connection_authority$;

set role laboratory_owner;
