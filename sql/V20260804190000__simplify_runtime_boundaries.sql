-- TARGET: canonical laboratory data remains the runtime center.
-- TARGET: cross-service events use one append-only outbox captured by Debezium.

drop table if exists public.acceptance_decision_receipt;
drop table if exists public.acceptance_decision;
drop table if exists public.evidence_receipt;
drop table if exists public.bounded_call_receipt;
drop table if exists public.bounded_call_invocation;
drop table if exists public.migration_checkpoint;

set local role laboratory_outbox_authority;

drop function if exists public.release_outbox_recovery(
    text, bigint, integer, text
);
drop function if exists public.fail_outbox_delivery(
    text, text, uuid, bigint, text
);
drop function if exists public.confirm_outbox_delivery(
    text, text, uuid, bigint, text, text
);
drop function if exists public.confirm_outbox_delivery(
    text, text, uuid, bigint
);
drop function if exists public.reclaim_outbox_delivery(
    text, bigint, text, integer
);
drop function if exists public.reclaim_outbox_delivery(
    text, bigint, text, interval
);
drop function if exists public.claim_outbox_delivery(text, integer);
drop function if exists public.claim_outbox_delivery(text, interval);

drop trigger if exists transactional_outbox_delivery_transition
    on public.transactional_outbox;
drop function if exists public.preserve_outbox_delivery_transition();

drop table if exists public.outbox_recovery_release;
drop table if exists public.outbox_delivery_attempt_outcome;
drop table if exists public.outbox_delivery_attempt;

alter table public.transactional_outbox
    drop column if exists delivery_state,
    drop column if exists delivery_attempts,
    drop column if exists available_at_utc,
    drop column if exists lease_owner,
    drop column if exists lease_principal,
    drop column if exists lease_token,
    drop column if exists fencing_token,
    drop column if exists lease_expires_at_utc,
    drop column if exists last_error_code,
    drop column if exists delivered_at_utc;

revoke all privileges on public.transactional_outbox from
    laboratory_app,
    laboratory_outbox_worker,
    laboratory_outbox_recovery_operator;
grant select on public.transactional_outbox to laboratory_app;
grant insert (
    tenant_id,
    message_id,
    topic,
    aggregate_id,
    aggregate_version,
    payload,
    payload_sha256,
    payload_canonicalization
) on public.transactional_outbox to laboratory_app;
grant select on public.transactional_outbox to laboratory_outbox_worker;

set local role laboratory_owner;

reassign owned by laboratory_outbox_authority to laboratory_owner;

-- Forced RLS remains active for tenant tables. The schema owner receives the
-- ordinary all-row access needed by Flyway without a custom session protocol.
alter policy tenant_bounded_migration_policy on public.tenant
    rename to tenant_owner_maintenance_policy;
alter policy tenant_owner_maintenance_policy on public.tenant
    using (true) with check (true);
alter policy specimen_bounded_migration_policy on public.specimen
    rename to specimen_owner_maintenance_policy;
alter policy specimen_owner_maintenance_policy on public.specimen
    using (true) with check (true);
alter policy specimen_event_bounded_migration_policy on public.specimen_event
    rename to specimen_event_owner_maintenance_policy;
alter policy specimen_event_owner_maintenance_policy on public.specimen_event
    using (true) with check (true);
alter policy idempotency_ledger_bounded_migration_policy
    on public.idempotency_ledger
    rename to idempotency_ledger_owner_maintenance_policy;
alter policy idempotency_ledger_owner_maintenance_policy
    on public.idempotency_ledger using (true) with check (true);
alter policy custody_position_bounded_migration_policy
    on public.custody_position
    rename to custody_position_owner_maintenance_policy;
alter policy custody_position_owner_maintenance_policy
    on public.custody_position using (true) with check (true);
alter policy instrument_inbox_bounded_migration_policy
    on public.instrument_inbox
    rename to instrument_inbox_owner_maintenance_policy;
alter policy instrument_inbox_owner_maintenance_policy
    on public.instrument_inbox using (true) with check (true);
alter policy transactional_outbox_bounded_migration_policy
    on public.transactional_outbox
    rename to transactional_outbox_owner_maintenance_policy;
alter policy transactional_outbox_owner_maintenance_policy
    on public.transactional_outbox using (true) with check (true);
alter policy vendor_projection_bounded_migration_policy
    on public.vendor_projection
    rename to vendor_projection_owner_maintenance_policy;
alter policy vendor_projection_owner_maintenance_policy
    on public.vendor_projection using (true) with check (true);
alter policy custody_event_bounded_migration_policy on public.custody_event
    rename to custody_event_owner_maintenance_policy;
alter policy custody_event_owner_maintenance_policy on public.custody_event
    using (true) with check (true);
alter policy instrument_measurement_bounded_migration_policy
    on public.instrument_measurement
    rename to instrument_measurement_owner_maintenance_policy;
alter policy instrument_measurement_owner_maintenance_policy
    on public.instrument_measurement using (true) with check (true);

-- The Debezium connector reads committed events for every tenant. Its database
-- identity stays read-only; replication attributes are configured by hosting.
create policy outbox_connector_read_policy on public.transactional_outbox
    for select to laboratory_outbox_worker using (true);

drop function if exists laboratory_security.bind_tenant_context(jsonb);

create or replace function laboratory_security.authorized_tenant_id()
returns text
language sql
stable
security invoker
set search_path = pg_catalog
as $$
select nullif(
    pg_catalog.current_setting('app.tenant_id', true),
    ''
);
$$;

drop function if exists laboratory_security.constant_time_equal(bytea, bytea);
drop table if exists laboratory_security.tenant_context_key;
drop function if exists laboratory_security.bounded_migration_session_active();

revoke all on function laboratory_security.authorized_tenant_id() from public;
grant execute on function laboratory_security.authorized_tenant_id() to
    laboratory_app;
revoke all privileges on all tables in schema public from
    laboratory_outbox_authority,
    laboratory_outbox_recovery_operator,
    laboratory_evidence_writer;
revoke all privileges on all sequences in schema public from
    laboratory_outbox_authority,
    laboratory_outbox_recovery_operator,
    laboratory_evidence_writer;
revoke execute on all functions in schema public from
    laboratory_outbox_authority,
    laboratory_outbox_recovery_operator,
    laboratory_evidence_writer;
revoke usage on schema public from
    laboratory_outbox_authority,
    laboratory_outbox_recovery_operator,
    laboratory_evidence_writer;
revoke all on schema laboratory_security from
    laboratory_outbox_authority,
    laboratory_evidence_writer,
    laboratory_outbox_recovery_operator;

revoke all on public.preserve_append_only_record() from public;
revoke update, delete on public.specimen_event from laboratory_app;
revoke update, delete on public.custody_event from laboratory_app;
revoke update, delete on public.instrument_inbox from laboratory_app;
