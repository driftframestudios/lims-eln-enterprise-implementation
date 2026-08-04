\set ON_ERROR_STOP on

do $role_provisioning$
declare
    role_spec record;
    observed_role record;
begin
    for role_spec in
        select *
          from (values
              ('laboratory_owner'::name, false),
              ('laboratory_app'::name, true),
              ('laboratory_outbox_worker'::name, true),
              ('laboratory_outbox_authority'::name, false),
              ('laboratory_outbox_recovery_operator'::name, true),
              ('laboratory_evidence_writer'::name, true),
              ('laboratory_migrator'::name, true)
          ) as required_role(role_name, can_login)
    loop
        select
            rolname,
            rolcanlogin,
            rolsuper,
            rolcreatedb,
            rolcreaterole,
            rolinherit,
            rolreplication,
            rolbypassrls
          into observed_role
          from pg_catalog.pg_roles
         where rolname = role_spec.role_name;

        if not found then
            execute pg_catalog.format(
                'create role %I %s nosuperuser nocreatedb nocreaterole noinherit noreplication nobypassrls',
                role_spec.role_name,
                case when role_spec.can_login then 'login' else 'nologin' end
            );
        elsif observed_role.rolcanlogin is distinct from role_spec.can_login
           or observed_role.rolsuper
           or observed_role.rolcreatedb
           or observed_role.rolcreaterole
           or observed_role.rolinherit
           or observed_role.rolreplication
           or observed_role.rolbypassrls then
            raise exception using
                errcode = '42501',
                message = pg_catalog.format(
                    'cluster role %I requires the released least-privilege attributes',
                    role_spec.role_name
                );
        end if;
    end loop;
end;
$role_provisioning$;

grant laboratory_owner to laboratory_migrator
    with admin false, inherit false, set true;
grant laboratory_outbox_authority to laboratory_owner
    with admin false, inherit false, set true;

select pg_catalog.format(
    'alter role laboratory_migrator in database %I set role to laboratory_owner',
    pg_catalog.current_database()
) \gexec

select pg_catalog.format(
    'grant connect on database %I to laboratory_migrator',
    pg_catalog.current_database()
) \gexec
select pg_catalog.format(
    'grant create on database %I to laboratory_owner',
    pg_catalog.current_database()
) \gexec
select pg_catalog.format(
    'revoke create on database %I from public',
    pg_catalog.current_database()
) \gexec
select pg_catalog.format(
    'revoke create on database %I from laboratory_migrator',
    pg_catalog.current_database()
) \gexec

alter schema public owner to laboratory_owner;
revoke create on schema public from public;
grant usage, create on schema public to laboratory_owner;
revoke all on schema public from laboratory_migrator;
