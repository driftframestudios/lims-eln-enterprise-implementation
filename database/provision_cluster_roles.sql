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
