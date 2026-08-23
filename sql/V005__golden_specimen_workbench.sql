-- TARGET: instrument review resolves through one tenant-and-specimen-bound evidence path.
-- TARGET: workbench projections derive from canonical lifecycle, custody, and measurement facts.

set local lock_timeout = '30s';
set local statement_timeout = '5min';
set local idle_in_transaction_session_timeout = '5min';

lock table
    public.specimen,
    public.instrument_inbox
in access exclusive mode;

do $workbench_preflight$
begin
    if exists (
        select 1
          from public.instrument_inbox as inbox
          left join public.specimen as specimen
            on specimen.tenant_id = inbox.tenant_id
           and specimen.specimen_id = inbox.specimen_id
         where specimen.specimen_id is null
    ) then
        raise exception using
            errcode = '23503',
            message = 'migration 005 requires every instrument inbox fact to reference its specimen';
    end if;
end;
$workbench_preflight$;

alter table public.instrument_inbox
    add constraint instrument_inbox_specimen_fk
        foreign key (tenant_id, specimen_id)
        references public.specimen(tenant_id, specimen_id),
    add constraint instrument_inbox_review_lineage_key unique (
        tenant_id,
        message_id,
        specimen_id,
        disposition
    );

create table public.instrument_review_resolution (
    tenant_id text not null,
    quarantine_message_id text not null,
    quarantine_disposition text not null default 'quarantined' check (
        quarantine_disposition = 'quarantined'
    ),
    specimen_id text not null,
    resolution_id text not null check (
        resolution_id ~ '^[ -~]+$'
        and pg_catalog.octet_length(resolution_id) <= 256
        and pg_catalog.btrim(resolution_id) <> ''
    ),
    disposition text not null check (
        disposition in ('accepted_replacement', 'closed_as_source_error')
    ),
    replacement_message_id text,
    replacement_disposition text,
    resolved_by text not null check (
        resolved_by ~ '^[ -~]+$'
        and pg_catalog.octet_length(resolved_by) <= 256
        and pg_catalog.btrim(resolved_by) <> ''
    ),
    rationale text not null check (
        rationale ~ '^[ -~]+$'
        and pg_catalog.octet_length(rationale) <= 4096
        and pg_catalog.btrim(rationale) <> ''
    ),
    resolved_at_utc timestamptz not null check (
        pg_catalog.isfinite(resolved_at_utc)
    ),
    recorded_at_utc timestamptz not null default pg_catalog.clock_timestamp() check (
        pg_catalog.isfinite(recorded_at_utc)
    ),
    primary key (tenant_id, quarantine_message_id),
    unique (tenant_id, resolution_id),
    foreign key (
        tenant_id,
        quarantine_message_id,
        specimen_id,
        quarantine_disposition
    ) references public.instrument_inbox(
        tenant_id,
        message_id,
        specimen_id,
        disposition
    ),
    foreign key (
        tenant_id,
        replacement_message_id,
        specimen_id,
        replacement_disposition
    ) references public.instrument_inbox(
        tenant_id,
        message_id,
        specimen_id,
        disposition
    ),
    check (
        (
            disposition = 'accepted_replacement'
            and replacement_message_id is not null
            and replacement_message_id <> quarantine_message_id
            and replacement_disposition in ('accepted', 'replayed')
        )
        or (
            disposition = 'closed_as_source_error'
            and replacement_message_id is null
            and replacement_disposition is null
        )
    )
);

create index instrument_review_resolution_specimen_timeline
    on public.instrument_review_resolution (
        tenant_id,
        specimen_id,
        resolved_at_utc,
        resolution_id
    );
create index instrument_measurement_workbench_timeline
    on public.instrument_measurement (
        tenant_id,
        specimen_id,
        captured_at_utc desc,
        message_id desc,
        analyte_code desc
    );
create index instrument_quarantine_specimen_queue
    on public.instrument_inbox (
        tenant_id,
        specimen_id,
        recorded_at_utc desc,
        message_id
    ) where disposition = 'quarantined';
create index vendor_projection_workbench_timeline
    on public.vendor_projection (
        tenant_id,
        external_identity,
        observed_at_utc desc,
        vendor_name
    );

alter table public.instrument_review_resolution enable row level security;
alter table public.instrument_review_resolution force row level security;

create policy instrument_review_resolution_tenant_policy
on public.instrument_review_resolution
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy instrument_review_resolution_bounded_migration_policy
on public.instrument_review_resolution
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());

create trigger instrument_review_resolution_append_only
before update or delete on public.instrument_review_resolution
for each row execute function public.preserve_append_only_record();

create function public.record_instrument_review_resolution(
    quarantine_message_value text,
    resolution_value text,
    disposition_value text,
    replacement_message_value text,
    resolved_by_value text,
    rationale_value text,
    resolved_at_value timestamptz
)
returns public.instrument_review_resolution
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $$
declare
    tenant_value text := laboratory_security.authorized_tenant_id();
    original_inbox public.instrument_inbox%rowtype;
    replacement_inbox public.instrument_inbox%rowtype;
    recorded_resolution public.instrument_review_resolution%rowtype;
begin
    select inbox.*
      into original_inbox
      from public.instrument_inbox as inbox
     where inbox.tenant_id = tenant_value
       and inbox.message_id = quarantine_message_value
       for key share;
    if not found then
        raise exception using
            errcode = 'P0002',
            message = 'instrument review requires the tenant-scoped source message';
    end if;
    if original_inbox.disposition <> 'quarantined' then
        raise exception using
            errcode = '23514',
            message = 'instrument review requires a quarantined source message';
    end if;

    if disposition_value = 'accepted_replacement' then
        if replacement_message_value is null
           or replacement_message_value = quarantine_message_value then
            raise exception using
                errcode = '23514',
                message = 'accepted replacement requires a distinct message identity';
        end if;
        select inbox.*
          into replacement_inbox
          from public.instrument_inbox as inbox
         where inbox.tenant_id = tenant_value
           and inbox.message_id = replacement_message_value
           for key share;
        if not found then
            raise exception using
                errcode = 'P0002',
                message = 'instrument review requires the tenant-scoped replacement message';
        end if;
        if replacement_inbox.specimen_id <> original_inbox.specimen_id then
            raise exception using
                errcode = '23503',
                message = 'instrument replacement requires the quarantined specimen identity';
        end if;
        if replacement_inbox.disposition not in ('accepted', 'replayed') then
            raise exception using
                errcode = '23514',
                message = 'instrument replacement requires an accepted or replayed message';
        end if;
    elsif disposition_value = 'closed_as_source_error' then
        if replacement_message_value is not null then
            raise exception using
                errcode = '23514',
                message = 'source-error closure records the replacement state as absent';
        end if;
    else
        raise exception using
            errcode = '23514',
            message = 'instrument review requires a released disposition';
    end if;

    insert into public.instrument_review_resolution (
        tenant_id,
        quarantine_message_id,
        specimen_id,
        resolution_id,
        disposition,
        replacement_message_id,
        replacement_disposition,
        resolved_by,
        rationale,
        resolved_at_utc
    ) values (
        tenant_value,
        quarantine_message_value,
        original_inbox.specimen_id,
        resolution_value,
        disposition_value,
        replacement_message_value,
        case
            when replacement_message_value is null then null
            else replacement_inbox.disposition
        end,
        resolved_by_value,
        rationale_value,
        resolved_at_value
    ) returning * into recorded_resolution;

    return recorded_resolution;
end;
$$;

create view public.normalized_observation
with (security_invoker = true, security_barrier = true)
as
select
    measurement.tenant_id,
    measurement.message_id,
    measurement.measurement_id,
    measurement.specimen_id,
    inbox.instrument_id,
    measurement.analyte_code,
    measurement.quantity as observed_value,
    measurement.quantity::text as observed_value_text,
    measurement.source_precision,
    measurement.source_scale,
    measurement.unit_code,
    measurement.unit_system,
    measurement.normalized_sha256,
    measurement.raw_sha256,
    measurement.source_disposition,
    measurement.captured_at_utc,
    measurement.recorded_at_utc
from public.instrument_measurement as measurement
join public.instrument_inbox as inbox
  on inbox.tenant_id = measurement.tenant_id
 and inbox.message_id = measurement.message_id
 and inbox.specimen_id = measurement.specimen_id
 and inbox.raw_sha256 = measurement.raw_sha256
 and inbox.captured_at_utc = measurement.captured_at_utc
 and inbox.disposition = measurement.source_disposition;

-- V004 keeps outbox state with its dedicated authority. Open only the view
-- definition capability to the migration owner, then close it in this transaction.
set local role laboratory_outbox_authority;
grant select on public.transactional_outbox to laboratory_owner;
set local role laboratory_owner;

create view public.specimen_workbench_snapshot
with (security_invoker = true, security_barrier = true)
as
select
    specimen.tenant_id,
    specimen.specimen_id,
    specimen.lifecycle_state,
    specimen.aggregate_version,
    specimen.canonical_document,
    specimen.updated_at_utc,
    custody.location_code,
    custody.custodian_id,
    custody.custody_version,
    custody.last_transfer_id,
    observation.measurement_id as latest_measurement_id,
    observation.message_id as latest_instrument_message_id,
    observation.instrument_id as latest_instrument_id,
    observation.analyte_code as latest_analyte_code,
    observation.observed_value_text as latest_observed_value_text,
    observation.unit_code as latest_unit_code,
    observation.normalized_sha256 as latest_observation_sha256,
    observation.raw_sha256 as latest_raw_sha256,
    projection.vendor_name,
    projection.external_revision,
    projection.reconciliation_state,
    coalesce(instrument_review.open_count, 0::bigint) as open_instrument_review_count,
    coalesce(instrument_review.history_count, 0::bigint) as quarantine_history_count,
    coalesce(outbox.pending_count, 0::bigint) as pending_outbox_count
from public.specimen
left join public.custody_position as custody
  on custody.tenant_id = specimen.tenant_id
 and custody.specimen_id = specimen.specimen_id
left join lateral (
    select normalized.*
      from public.normalized_observation as normalized
     where normalized.tenant_id = specimen.tenant_id
       and normalized.specimen_id = specimen.specimen_id
     order by normalized.captured_at_utc desc, normalized.message_id desc
     limit 1
) as observation on true
left join lateral (
    select vendor.*
      from public.vendor_projection as vendor
     where vendor.tenant_id = specimen.tenant_id
       and vendor.external_identity = specimen.specimen_id
     order by vendor.observed_at_utc desc, vendor.vendor_name
     limit 1
) as projection on true
left join lateral (
    select
        pg_catalog.count(*) filter (
            where resolution.quarantine_message_id is null
        ) as open_count,
        pg_catalog.count(*) as history_count
      from public.instrument_inbox as inbox
      left join public.instrument_review_resolution as resolution
        on resolution.tenant_id = inbox.tenant_id
       and resolution.quarantine_message_id = inbox.message_id
     where inbox.tenant_id = specimen.tenant_id
       and inbox.specimen_id = specimen.specimen_id
       and inbox.disposition = 'quarantined'
) as instrument_review on true
left join lateral (
    select pg_catalog.count(*) as pending_count
      from public.transactional_outbox as pending
     where pending.tenant_id = specimen.tenant_id
       and pending.aggregate_id = specimen.specimen_id
       and pending.delivery_state <> 'delivered'
) as outbox on true;

set local role laboratory_outbox_authority;
revoke select on public.transactional_outbox from laboratory_owner;
set local role laboratory_owner;

alter table public.instrument_review_resolution owner to laboratory_owner;
alter function public.record_instrument_review_resolution(
    text, text, text, text, text, text, timestamptz
) owner to laboratory_owner;
alter view public.normalized_observation owner to laboratory_owner;
alter view public.specimen_workbench_snapshot owner to laboratory_owner;

revoke all privileges on public.instrument_review_resolution from public;
revoke all on function public.record_instrument_review_resolution(
    text, text, text, text, text, text, timestamptz
) from public;
revoke all privileges on public.normalized_observation from public;
revoke all privileges on public.specimen_workbench_snapshot from public;

grant select on public.instrument_review_resolution to
    laboratory_app,
    laboratory_migrator;
grant execute on function public.record_instrument_review_resolution(
    text, text, text, text, text, text, timestamptz
) to laboratory_app;
grant select on public.normalized_observation, public.specimen_workbench_snapshot to
    laboratory_app,
    laboratory_migrator;
