-- TARGET: signed, short-lived tenant assertions form the row-policy authority.
-- TARGET: custody history and outbox content retain immutable transaction evidence.

create extension if not exists pgcrypto;

create schema laboratory_security authorization laboratory_owner;
revoke all on schema laboratory_security from public;
grant usage on schema laboratory_security to
    laboratory_app,
    laboratory_outbox_worker,
    laboratory_evidence_writer,
    laboratory_migrator;

create table laboratory_security.tenant_context_key (
    key_id text primary key check (
        key_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
    ),
    secret_material bytea not null check (octet_length(secret_material) >= 32),
    valid_from_utc timestamptz not null,
    valid_until_utc timestamptz not null,
    revoked_at_utc timestamptz,
    created_at_utc timestamptz not null default clock_timestamp(),
    check (valid_until_utc > valid_from_utc),
    check (revoked_at_utc is null or revoked_at_utc >= valid_from_utc)
);
alter table laboratory_security.tenant_context_key owner to laboratory_owner;
revoke all on laboratory_security.tenant_context_key from public;
revoke all on laboratory_security.tenant_context_key from
    laboratory_app,
    laboratory_outbox_worker,
    laboratory_evidence_writer,
    laboratory_migrator;

create function laboratory_security.constant_time_equal(
    left_value bytea,
    right_value bytea
)
returns boolean
language plpgsql
immutable
strict
set search_path = pg_catalog
as $$
declare
    difference integer := 0;
    byte_offset integer;
begin
    if octet_length(left_value) <> octet_length(right_value) then
        return false;
    end if;
    for byte_offset in 0..octet_length(left_value) - 1 loop
        difference := difference | (
            get_byte(left_value, byte_offset) # get_byte(right_value, byte_offset)
        );
    end loop;
    return difference = 0;
end;
$$;
alter function laboratory_security.constant_time_equal(bytea, bytea)
    owner to laboratory_owner;
revoke all on function laboratory_security.constant_time_equal(bytea, bytea)
    from public;

create function laboratory_security.bounded_migration_session_active()
returns boolean
language sql
stable
security invoker
set search_path = pg_catalog
as $$
select
    session_user = 'laboratory_migrator'
    and current_user = 'laboratory_owner'
    and pg_catalog.current_setting('role', true) = 'laboratory_owner'
    and exists (
        select 1
          from pg_catalog.pg_roles as login_role
         where login_role.rolname = 'laboratory_migrator'
           and login_role.rolcanlogin
           and not login_role.rolsuper
           and not login_role.rolcreatedb
           and not login_role.rolcreaterole
           and not login_role.rolinherit
           and not login_role.rolreplication
           and not login_role.rolbypassrls
    )
    and exists (
        select 1
          from pg_catalog.pg_roles as owner_role
         where owner_role.rolname = 'laboratory_owner'
           and not owner_role.rolcanlogin
           and not owner_role.rolsuper
           and not owner_role.rolcreatedb
           and not owner_role.rolcreaterole
           and not owner_role.rolinherit
           and not owner_role.rolreplication
           and not owner_role.rolbypassrls
    )
    and exists (
        select 1
          from pg_catalog.pg_auth_members as membership
          join pg_catalog.pg_roles as granted_role
            on granted_role.oid = membership.roleid
          join pg_catalog.pg_roles as member_role
            on member_role.oid = membership.member
         where granted_role.rolname = 'laboratory_owner'
           and member_role.rolname = 'laboratory_migrator'
           and not membership.admin_option
           and not membership.inherit_option
           and membership.set_option
    )
    and exists (
        select 1
          from pg_catalog.pg_auth_members as membership
          join pg_catalog.pg_roles as granted_role
            on granted_role.oid = membership.roleid
          join pg_catalog.pg_roles as member_role
            on member_role.oid = membership.member
         where granted_role.rolname = 'laboratory_outbox_authority'
           and member_role.rolname = 'laboratory_owner'
           and not membership.admin_option
           and not membership.inherit_option
           and membership.set_option
    )
    and (
        select pg_catalog.count(*) = 1
           and pg_catalog.bool_and(
               configuration.value = 'role=laboratory_owner'
           )
          from pg_catalog.pg_db_role_setting as role_setting
          join pg_catalog.pg_roles as member_role
            on member_role.oid = role_setting.setrole
          join pg_catalog.pg_database as target_database
            on target_database.oid = role_setting.setdatabase
         cross join lateral pg_catalog.unnest(role_setting.setconfig)
            as configuration(value)
         where member_role.rolname = 'laboratory_migrator'
           and target_database.datname = pg_catalog.current_database()
           and configuration.value like 'role=%'
    )
    and (
        select pg_catalog.count(*) = 1
           and pg_catalog.bool_and(
               database_acl.privilege_type = 'CONNECT'
               and not database_acl.is_grantable
           )
          from pg_catalog.pg_database as target_database
         cross join lateral pg_catalog.aclexplode(
             coalesce(
                 target_database.datacl,
                 pg_catalog.acldefault('d', target_database.datdba)
             )
         ) as database_acl
          join pg_catalog.pg_roles as grantee_role
            on grantee_role.oid = database_acl.grantee
         where target_database.datname = pg_catalog.current_database()
           and grantee_role.rolname = 'laboratory_migrator'
    );
$$;

create function laboratory_security.authorized_tenant_id()
returns text
language plpgsql
stable
security definer
set search_path = pg_catalog
as $$
declare
    context_text text;
    context_document jsonb;
    tenant_value text;
    subject_value text;
    key_value text;
    issued_text text;
    expires_text text;
    nonce_value text;
    signature_value text;
    issued_epoch bigint;
    expires_epoch bigint;
    observed_epoch bigint;
    signing_key bytea;
    signed_content text;
    expected_signature bytea;
begin
    if laboratory_security.bounded_migration_session_active() then
        return null;
    end if;
    context_text := current_setting('app.tenant_context', true);
    if context_text is null or context_text = '' then
        raise exception using
            errcode = '28000',
            message = 'transaction requires a verified tenant context';
    end if;

    begin
        context_document := context_text::jsonb;
    exception when others then
        raise exception using
            errcode = '28000',
            message = 'tenant context requires a valid signed document';
    end;

    if jsonb_typeof(context_document) <> 'object'
       or not context_document ?& array[
           'tenant_id', 'subject_id', 'key_id', 'issued_at_epoch',
           'expires_at_epoch', 'nonce', 'signature_hex'
       ]
       or (select count(*) from jsonb_object_keys(context_document)) <> 7 then
        raise exception using
            errcode = '28000',
            message = 'tenant context requires the released field set';
    end if;

    tenant_value := context_document ->> 'tenant_id';
    subject_value := context_document ->> 'subject_id';
    key_value := context_document ->> 'key_id';
    issued_text := context_document ->> 'issued_at_epoch';
    expires_text := context_document ->> 'expires_at_epoch';
    nonce_value := context_document ->> 'nonce';
    signature_value := context_document ->> 'signature_hex';

    if tenant_value !~ '^[ -~]{1,128}$'
       or btrim(tenant_value) = ''
       or subject_value !~ '^[ -~]{1,128}$'
       or btrim(subject_value) = ''
       or key_value !~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
       or issued_text !~ '^[0-9]{1,12}$'
       or expires_text !~ '^[0-9]{1,12}$'
       or nonce_value !~ '^[A-Za-z0-9_-]{16,128}$'
       or signature_value !~ '^[a-f0-9]{64}$' then
        raise exception using
            errcode = '28000',
            message = 'tenant context fields require their released formats';
    end if;

    issued_epoch := issued_text::bigint;
    expires_epoch := expires_text::bigint;
    observed_epoch := floor(extract(epoch from clock_timestamp()))::bigint;
    if expires_epoch <= issued_epoch
       or expires_epoch - issued_epoch > 900
       or issued_epoch > observed_epoch + 30
       or expires_epoch < observed_epoch then
        raise exception using
            errcode = '28000',
            message = 'tenant context requires a current validity window';
    end if;

    select secret_material
      into signing_key
      from laboratory_security.tenant_context_key
     where key_id = key_value
       and valid_from_utc <= clock_timestamp()
       and valid_until_utc > clock_timestamp()
       and revoked_at_utc is null;
    if signing_key is null then
        raise exception using
            errcode = '28000',
            message = 'tenant context requires an active verification key';
    end if;

    signed_content := concat_ws(
        chr(10),
        tenant_value,
        subject_value,
        key_value,
        issued_text,
        expires_text,
        nonce_value
    );
    expected_signature := public.hmac(
        convert_to(signed_content, 'UTF8'),
        signing_key,
        'sha256'
    );
    if not laboratory_security.constant_time_equal(
        expected_signature,
        decode(signature_value, 'hex')
    ) then
        raise exception using
            errcode = '28000',
            message = 'tenant context requires a verified signature';
    end if;
    return tenant_value;
end;
$$;
alter function laboratory_security.authorized_tenant_id() owner to laboratory_owner;

create function laboratory_security.bind_tenant_context(context_document jsonb)
returns text
language plpgsql
volatile
security invoker
set search_path = pg_catalog
as $$
declare
    authorized_tenant text;
begin
    perform set_config('app.tenant_context', context_document::text, true);
    authorized_tenant := laboratory_security.authorized_tenant_id();
    return authorized_tenant;
end;
$$;

revoke all on function laboratory_security.authorized_tenant_id() from public;
revoke all on function laboratory_security.bind_tenant_context(jsonb) from public;
revoke all on function laboratory_security.bounded_migration_session_active()
    from public;
grant execute on function laboratory_security.authorized_tenant_id() to
    laboratory_app,
    laboratory_outbox_worker,
    laboratory_evidence_writer,
    laboratory_migrator;
grant execute on function laboratory_security.bind_tenant_context(jsonb) to
    laboratory_app,
    laboratory_outbox_worker,
    laboratory_evidence_writer,
    laboratory_migrator;

drop policy tenant_tenant_policy on tenant;
drop policy specimen_tenant_policy on specimen;
drop policy specimen_event_tenant_policy on specimen_event;
drop policy idempotency_ledger_tenant_policy on idempotency_ledger;
drop policy custody_tenant_policy on custody_position;
drop policy instrument_inbox_tenant_policy on instrument_inbox;
drop policy outbox_tenant_policy on transactional_outbox;
drop policy vendor_projection_tenant_policy on vendor_projection;
drop policy bounded_call_invocation_tenant_policy on bounded_call_invocation;
drop policy bounded_call_receipt_tenant_policy on bounded_call_receipt;
drop policy migration_checkpoint_tenant_policy on migration_checkpoint;
drop policy evidence_receipt_tenant_policy on evidence_receipt;
drop policy acceptance_decision_tenant_policy on acceptance_decision;
drop policy acceptance_decision_receipt_tenant_policy on acceptance_decision_receipt;

create policy tenant_tenant_policy on tenant
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy specimen_tenant_policy on specimen
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy specimen_event_tenant_policy on specimen_event
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy idempotency_ledger_tenant_policy on idempotency_ledger
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy custody_tenant_policy on custody_position
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy instrument_inbox_tenant_policy on instrument_inbox
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy outbox_tenant_policy on transactional_outbox
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy vendor_projection_tenant_policy on vendor_projection
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy bounded_call_invocation_tenant_policy on bounded_call_invocation
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy bounded_call_receipt_tenant_policy on bounded_call_receipt
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy migration_checkpoint_tenant_policy on migration_checkpoint
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy evidence_receipt_tenant_policy on evidence_receipt
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy acceptance_decision_tenant_policy on acceptance_decision
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy acceptance_decision_receipt_tenant_policy
on acceptance_decision_receipt
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());

create policy tenant_bounded_migration_policy on tenant
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy specimen_bounded_migration_policy on specimen
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy specimen_event_bounded_migration_policy on specimen_event
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy idempotency_ledger_bounded_migration_policy on idempotency_ledger
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy custody_position_bounded_migration_policy on custody_position
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy instrument_inbox_bounded_migration_policy on instrument_inbox
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy transactional_outbox_bounded_migration_policy
on transactional_outbox
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy vendor_projection_bounded_migration_policy on vendor_projection
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy bounded_call_invocation_bounded_migration_policy
on bounded_call_invocation
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy bounded_call_receipt_bounded_migration_policy
on bounded_call_receipt
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy migration_checkpoint_bounded_migration_policy
on migration_checkpoint
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy evidence_receipt_bounded_migration_policy on evidence_receipt
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy acceptance_decision_bounded_migration_policy
on acceptance_decision
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy acceptance_decision_receipt_bounded_migration_policy
on acceptance_decision_receipt
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());

alter table tenant
    add constraint tenant_created_at_finite check (isfinite(created_at_utc));
alter table specimen
    add constraint specimen_updated_at_finite check (isfinite(updated_at_utc)),
    add constraint specimen_document_object check (
        jsonb_typeof(canonical_document) = 'object'
    );
alter table specimen_event
    add constraint specimen_event_times_finite check (
        isfinite(occurred_at_utc) and isfinite(recorded_at_utc)
    ),
    add constraint specimen_event_payload_object check (
        jsonb_typeof(payload) = 'object'
    );
alter table idempotency_ledger
    add constraint idempotency_times_finite check (
        isfinite(reserved_at_utc)
        and (committed_at_utc is null or isfinite(committed_at_utc))
    ),
    add constraint idempotency_state_coherent check (
        (
            status = 'reserved'
            and outcome_document is null
            and committed_at_utc is null
        )
        or (
            status in ('committed', 'quarantined')
            and outcome_document is not null
            and committed_at_utc is not null
            and committed_at_utc >= reserved_at_utc
        )
    );
alter table instrument_inbox
    add constraint instrument_times_finite check (
        isfinite(captured_at_utc) and isfinite(recorded_at_utc)
    ),
    add constraint instrument_disposition_coherent check (
        (
            disposition in ('accepted', 'replayed')
            and reason_code is null
        )
        or (
            disposition = 'quarantined'
            and reason_code is not null
        )
    );
alter table transactional_outbox
    add constraint outbox_times_finite check (
        isfinite(available_at_utc)
        and (lease_expires_at_utc is null or isfinite(lease_expires_at_utc))
        and (delivered_at_utc is null or isfinite(delivered_at_utc))
    );
alter table vendor_projection
    add constraint vendor_observed_at_finite check (isfinite(observed_at_utc));
alter table bounded_call_invocation
    add constraint bounded_invocation_times_finite check (
        isfinite(lease_expires_at_utc)
        and isfinite(reserved_at_utc)
        and (completed_at_utc is null or isfinite(completed_at_utc))
    );
alter table bounded_call_receipt
    add constraint bounded_receipt_times_finite check (
        isfinite(requested_at_utc) and isfinite(recorded_at_utc)
    );
alter table migration_checkpoint
    add constraint migration_recorded_at_finite check (isfinite(recorded_at_utc));
alter table evidence_receipt
    add constraint evidence_observed_at_finite check (isfinite(observed_at_utc)),
    add constraint evidence_document_shapes check (
        jsonb_typeof(version_bindings) = 'object'
        and jsonb_typeof(scenario_ids) = 'array'
        and jsonb_typeof(artifact_digests) = 'array'
        and jsonb_typeof(limitations) = 'array'
    );
alter table acceptance_decision
    add constraint acceptance_decided_at_finite check (isfinite(decided_at_utc));
alter table laboratory_security.tenant_context_key
    add constraint tenant_context_key_times_finite check (
        isfinite(valid_from_utc)
        and isfinite(valid_until_utc)
        and isfinite(created_at_utc)
        and (revoked_at_utc is null or isfinite(revoked_at_utc))
    );

alter table custody_position
    add column last_transfer_id text,
    add column recorded_at_utc timestamptz not null default clock_timestamp();

update custody_position
   set last_transfer_id = 'MIGRATED-' || encode(
       digest(tenant_id || chr(10) || specimen_id || chr(10) || custody_version::text, 'sha256'),
       'hex'
   );

alter table custody_position
    alter column last_transfer_id set not null;

create table custody_event (
    tenant_id text not null,
    specimen_id text not null,
    transfer_id text not null,
    expected_version bigint not null check (expected_version >= 0),
    resulting_version bigint not null check (resulting_version = expected_version + 1),
    from_location_code text,
    to_location_code text not null,
    custodian_id text not null,
    occurred_at_utc timestamptz not null,
    recorded_at_utc timestamptz not null default clock_timestamp(),
    event_kind text not null default 'transfer' check (
        event_kind in ('transfer', 'migration_baseline')
    ),
    primary key (tenant_id, specimen_id, resulting_version),
    unique (tenant_id, transfer_id),
    foreign key (tenant_id, specimen_id)
        references specimen(tenant_id, specimen_id)
);

insert into custody_event (
    tenant_id,
    specimen_id,
    transfer_id,
    expected_version,
    resulting_version,
    from_location_code,
    to_location_code,
    custodian_id,
    occurred_at_utc,
    recorded_at_utc,
    event_kind
)
select
    tenant_id,
    specimen_id,
    last_transfer_id,
    custody_version - 1,
    custody_version,
    null,
    location_code,
    custodian_id,
    occurred_at_utc,
    recorded_at_utc,
    'migration_baseline'
from custody_position;

alter table custody_position
    add constraint custody_position_last_transfer_fk
    foreign key (tenant_id, last_transfer_id)
    references custody_event(tenant_id, transfer_id);

alter table custody_event enable row level security;
alter table custody_event force row level security;
create policy custody_event_tenant_policy on custody_event
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy custody_event_bounded_migration_policy on custody_event
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create trigger custody_event_append_only
before update or delete on custody_event
for each row execute function preserve_append_only_record();

alter table custody_position
    add constraint custody_position_times_finite check (
        isfinite(occurred_at_utc) and isfinite(recorded_at_utc)
    );
alter table custody_event
    add constraint custody_event_times_finite check (
        isfinite(occurred_at_utc) and isfinite(recorded_at_utc)
    );

create table instrument_measurement (
    tenant_id text not null,
    measurement_id text not null,
    message_id text not null,
    specimen_id text not null,
    analyte_code text not null check (
        analyte_code ~ '^[ -~]{1,128}$' and btrim(analyte_code) <> ''
    ),
    quantity numeric not null check (
        case
            when quantity::text in ('NaN', 'Infinity', '-Infinity') then false
            else
                scale(quantity) between 0 and 18
                and quantity > -100000000000000000000
                and quantity < 100000000000000000000
        end
    ),
    source_precision smallint not null check (source_precision between 1 and 38),
    source_scale smallint not null check (source_scale between 0 and 18),
    unit_code text not null check (unit_code in ('ng/uL', '{copies}/uL')),
    unit_system text not null check (unit_system = 'http://unitsofmeasure.org'),
    captured_at_utc timestamptz not null check (isfinite(captured_at_utc)),
    raw_sha256 text not null check (raw_sha256 ~ '^[a-f0-9]{64}$'),
    normalized_sha256 text not null check (normalized_sha256 ~ '^[a-f0-9]{64}$'),
    recorded_at_utc timestamptz not null default clock_timestamp() check (
        isfinite(recorded_at_utc)
    ),
    primary key (tenant_id, measurement_id),
    unique (tenant_id, message_id, analyte_code),
    foreign key (tenant_id, message_id)
        references instrument_inbox(tenant_id, message_id),
    foreign key (tenant_id, specimen_id)
        references specimen(tenant_id, specimen_id)
);
alter table instrument_measurement enable row level security;
alter table instrument_measurement force row level security;
create policy instrument_measurement_tenant_policy on instrument_measurement
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy instrument_measurement_bounded_migration_policy
on instrument_measurement
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create trigger instrument_measurement_append_only
before update or delete on instrument_measurement
for each row execute function preserve_append_only_record();
grant select, insert on instrument_measurement to laboratory_app;
grant select, insert on instrument_measurement to laboratory_migrator;
alter table instrument_measurement owner to laboratory_owner;

alter table transactional_outbox
    add column payload_canonicalization text not null default 'postgresql-jsonb-text-v1',
    add column created_at_utc timestamptz not null default clock_timestamp();
alter table transactional_outbox
    add constraint outbox_created_at_finite check (isfinite(created_at_utc));
update transactional_outbox
   set payload_sha256 = encode(
       public.digest(convert_to(payload::text, 'UTF8'), 'sha256'),
       'hex'
   );
alter table transactional_outbox
    add constraint outbox_payload_object check (jsonb_typeof(payload) = 'object'),
    add constraint outbox_aggregate_version_positive check (aggregate_version >= 1),
    add constraint outbox_canonicalization_released check (
        payload_canonicalization = 'postgresql-jsonb-text-v1'
    ),
    add constraint outbox_delivery_state_coherent check (
        (
            delivery_state = 'ready'
            and lease_owner is null
            and lease_token is null
            and lease_expires_at_utc is null
            and delivered_at_utc is null
        )
        or (
            delivery_state = 'leased'
            and lease_owner is not null
            and lease_token is not null
            and lease_expires_at_utc is not null
            and delivered_at_utc is null
            and fencing_token >= 1
        )
        or (
            delivery_state = 'delivered'
            and lease_owner is null
            and lease_token is null
            and lease_expires_at_utc is null
            and delivered_at_utc is not null
        )
        or (
            delivery_state = 'recovery_required'
            and last_error_code is not null
            and delivered_at_utc is null
        )
    );

create function preserve_outbox_content()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    if new.payload_sha256 <> encode(
        public.digest(convert_to(new.payload::text, 'UTF8'), 'sha256'),
        'hex'
    ) then
        raise exception 'outbox payload digest requires canonical payload content';
    end if;
    if tg_op = 'UPDATE' and (
       new.tenant_id is distinct from old.tenant_id
       or new.message_id is distinct from old.message_id
       or new.topic is distinct from old.topic
       or new.aggregate_id is distinct from old.aggregate_id
       or new.aggregate_version is distinct from old.aggregate_version
       or new.payload is distinct from old.payload
       or new.payload_sha256 is distinct from old.payload_sha256
       or new.payload_canonicalization is distinct from old.payload_canonicalization
       or new.created_at_utc is distinct from old.created_at_utc
    ) then
        raise exception 'outbox identity and content are immutable';
    end if;
    return new;
end;
$$;

create trigger transactional_outbox_content_immutable
before insert or update on transactional_outbox
for each row execute function preserve_outbox_content();

drop index outbox_delivery_queue;
create index outbox_delivery_queue
    on transactional_outbox (tenant_id, available_at_utc, message_id)
    where delivery_state = 'ready';

revoke insert, update on custody_position from laboratory_app;
grant select on custody_position, custody_event to laboratory_app;
revoke update on transactional_outbox from laboratory_app;
grant select, insert on transactional_outbox to laboratory_app;
revoke update on transactional_outbox from laboratory_outbox_worker;
grant select on transactional_outbox to laboratory_outbox_worker;
grant update (
    delivery_state,
    delivery_attempts,
    available_at_utc,
    lease_owner,
    lease_token,
    fencing_token,
    lease_expires_at_utc,
    last_error_code,
    delivered_at_utc
) on transactional_outbox to laboratory_outbox_worker;

create function record_custody_transfer(
    specimen_value text,
    destination_value text,
    custodian_value text,
    expected_version_value bigint,
    transfer_value text,
    occurred_value timestamptz
)
returns custody_position
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    tenant_value text;
    current_position custody_position%rowtype;
    prior_event custody_event%rowtype;
    next_position custody_position%rowtype;
    recorded_value timestamptz;
    payload_value jsonb;
    payload_digest_value text;
begin
    tenant_value := laboratory_security.authorized_tenant_id();
    if specimen_value !~ '^[ -~]+$'
       or char_length(specimen_value) > 256
       or btrim(specimen_value) = ''
       or destination_value !~ '^[ -~]+$'
       or char_length(destination_value) > 256
       or btrim(destination_value) = ''
       or custodian_value !~ '^[ -~]+$'
       or char_length(custodian_value) > 256
       or btrim(custodian_value) = ''
       or transfer_value !~ '^[ -~]+$'
       or char_length(transfer_value) > 256
       or btrim(transfer_value) = ''
       or expected_version_value < 0 then
        raise exception using
            errcode = '22023',
            message = 'custody transfer requires released identity and revision formats';
    end if;

    select *
      into prior_event
      from custody_event
     where tenant_id = tenant_value
       and transfer_id = transfer_value;
    if found then
        if prior_event.specimen_id is distinct from specimen_value
           or prior_event.expected_version is distinct from expected_version_value
           or prior_event.to_location_code is distinct from destination_value
           or prior_event.custodian_id is distinct from custodian_value
           or prior_event.occurred_at_utc is distinct from occurred_value then
            raise exception using
                errcode = '23505',
                message = 'custody transfer identity already binds to different content';
        end if;
        return (
            prior_event.tenant_id,
            prior_event.specimen_id,
            prior_event.resulting_version,
            prior_event.to_location_code,
            prior_event.custodian_id,
            prior_event.occurred_at_utc,
            prior_event.transfer_id,
            prior_event.recorded_at_utc
        )::custody_position;
    end if;

    select *
      into current_position
      from custody_position
     where tenant_id = tenant_value
       and specimen_id = specimen_value
     for update;
    if coalesce(current_position.custody_version, 0) <> expected_version_value then
        raise exception using
            errcode = '40001',
            message = format(
                'custody revision is %s; reload and plan from the stored revision',
                coalesce(current_position.custody_version, 0)
            );
    end if;

    recorded_value := clock_timestamp();
    insert into custody_event (
        tenant_id,
        specimen_id,
        transfer_id,
        expected_version,
        resulting_version,
        from_location_code,
        to_location_code,
        custodian_id,
        occurred_at_utc,
        recorded_at_utc,
        event_kind
    ) values (
        tenant_value,
        specimen_value,
        transfer_value,
        expected_version_value,
        expected_version_value + 1,
        current_position.location_code,
        destination_value,
        custodian_value,
        occurred_value,
        recorded_value,
        'transfer'
    );

    if expected_version_value = 0 then
        insert into custody_position (
            tenant_id,
            specimen_id,
            custody_version,
            location_code,
            custodian_id,
            occurred_at_utc,
            last_transfer_id,
            recorded_at_utc
        ) values (
            tenant_value,
            specimen_value,
            1,
            destination_value,
            custodian_value,
            occurred_value,
            transfer_value,
            recorded_value
        )
        returning * into next_position;
    else
        update custody_position
           set custody_version = expected_version_value + 1,
               location_code = destination_value,
               custodian_id = custodian_value,
               occurred_at_utc = occurred_value,
               last_transfer_id = transfer_value,
               recorded_at_utc = recorded_value
         where tenant_id = tenant_value
           and specimen_id = specimen_value
           and custody_version = expected_version_value
        returning * into next_position;
        if not found then
            raise exception using
                errcode = '40001',
                message = 'custody compare-and-set requires the stored revision';
        end if;
    end if;

    payload_value := jsonb_build_object(
        'custodian_id', custodian_value,
        'from_location', current_position.location_code,
        'occurred_at_utc', occurred_value,
        'specimen_id', specimen_value,
        'to_location', destination_value,
        'transfer_id', transfer_value,
        'version', expected_version_value + 1
    );
    payload_digest_value := encode(
        digest(convert_to(payload_value::text, 'UTF8'), 'sha256'),
        'hex'
    );
    insert into transactional_outbox (
        tenant_id,
        message_id,
        topic,
        aggregate_id,
        aggregate_version,
        payload,
        payload_sha256,
        payload_canonicalization
    ) values (
        tenant_value,
        transfer_value,
        'custody.position.changed',
        specimen_value,
        expected_version_value + 1,
        payload_value,
        payload_digest_value,
        'postgresql-jsonb-text-v1'
    );
    return next_position;
end;
$$;
alter function record_custody_transfer(text, text, text, bigint, text, timestamptz)
    owner to laboratory_owner;
revoke all on function record_custody_transfer(
    text, text, text, bigint, text, timestamptz
) from public;
grant execute on function record_custody_transfer(
    text, text, text, bigint, text, timestamptz
) to laboratory_app;

alter table custody_event owner to laboratory_owner;
alter function preserve_outbox_content() owner to laboratory_owner;
alter function preserve_append_only_record() owner to laboratory_owner;
alter function preserve_append_only_record() set search_path to pg_catalog;
