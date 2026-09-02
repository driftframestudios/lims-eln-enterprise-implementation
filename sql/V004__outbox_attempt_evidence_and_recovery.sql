-- TARGET: each outbox transition follows one released state-machine edge.
-- TARGET: immutable attempt, outcome, and recovery facts reconstruct delivery.

set local lock_timeout = '30s';
set local statement_timeout = '5min';
set local idle_in_transaction_session_timeout = '5min';

lock table
    public.custody_event,
    public.custody_position,
    public.instrument_inbox,
    public.instrument_measurement,
    public.transactional_outbox
in access exclusive mode;

do $migration_preflight$
begin
    if exists (
        select 1
          from public.instrument_measurement as measurement
          join public.instrument_inbox as inbox
            on inbox.tenant_id = measurement.tenant_id
           and inbox.message_id = measurement.message_id
         where measurement.source_scale is distinct from
                   pg_catalog.scale(measurement.quantity)
            or measurement.specimen_id is distinct from inbox.specimen_id
            or measurement.raw_sha256 is distinct from inbox.raw_sha256
            or measurement.captured_at_utc is distinct from inbox.captured_at_utc
            or inbox.disposition not in ('accepted', 'replayed')
    ) then
        raise exception using
            errcode = '23514',
            message = 'migration 004 requires coherent measurement scale and inbox lineage';
    end if;
    if exists (
        select 1
          from public.custody_position as position
          left join public.custody_event as event
            on event.tenant_id = position.tenant_id
           and event.specimen_id = position.specimen_id
           and event.resulting_version = position.custody_version
           and event.transfer_id = position.last_transfer_id
         where event.transfer_id is null
    ) then
        raise exception using
            errcode = '23503',
            message = 'migration 004 requires custody positions bound to their complete event identity';
    end if;
    if exists (
        select 1
          from public.transactional_outbox
         where message_id !~ '^[ -~]+$'
            or pg_catalog.octet_length(message_id) > 256
            or pg_catalog.btrim(message_id) = ''
    ) then
        raise exception using
            errcode = '23514',
            message = 'migration 004 requires bounded outbox message identities';
    end if;
    if exists (
        select 1
          from public.transactional_outbox
         where delivery_state <> 'ready'
            or delivery_attempts <> 0
            or fencing_token <> 0
            or lease_owner is not null
            or lease_principal is not null
            or lease_token is not null
            or lease_expires_at_utc is not null
            or last_error_code is not null
            or delivered_at_utc is not null
    ) then
        raise exception using
            errcode = '55000',
            message = 'migration 004 requires an initial ready outbox provenance boundary';
    end if;
end;
$migration_preflight$;

alter table public.instrument_inbox
    add constraint instrument_inbox_measurement_lineage_key unique (
        tenant_id,
        message_id,
        specimen_id,
        raw_sha256,
        captured_at_utc,
        disposition
    );

alter table public.instrument_measurement
    add column source_disposition text;

update public.instrument_measurement as measurement
   set source_disposition = inbox.disposition
  from public.instrument_inbox as inbox
 where inbox.tenant_id = measurement.tenant_id
   and inbox.message_id = measurement.message_id;

alter table public.instrument_measurement
    alter column source_disposition set not null,
    add constraint instrument_measurement_source_scale_coherent check (
        source_scale = pg_catalog.scale(quantity)
    ),
    add constraint instrument_measurement_source_disposition_projectable check (
        source_disposition in ('accepted', 'replayed')
    ),
    add constraint instrument_measurement_complete_inbox_lineage_fk
        foreign key (
            tenant_id,
            message_id,
            specimen_id,
            raw_sha256,
            captured_at_utc,
            source_disposition
        )
        references public.instrument_inbox (
            tenant_id,
            message_id,
            specimen_id,
            raw_sha256,
            captured_at_utc,
            disposition
        );

create trigger instrument_inbox_append_only
before update or delete on public.instrument_inbox
for each row execute function public.preserve_append_only_record();

revoke update on public.instrument_inbox from
    laboratory_app,
    laboratory_migrator;

alter table public.custody_event
    add constraint custody_event_position_binding_key unique (
        tenant_id,
        specimen_id,
        resulting_version,
        transfer_id
    );

alter table public.custody_position
    drop constraint custody_position_last_transfer_fk,
    add constraint custody_position_complete_event_fk
        foreign key (
            tenant_id,
            specimen_id,
            custody_version,
            last_transfer_id
        )
        references public.custody_event (
            tenant_id,
            specimen_id,
            resulting_version,
            transfer_id
        );

grant usage on schema public to
    laboratory_outbox_authority,
    laboratory_outbox_recovery_operator;
grant usage on schema laboratory_security to
    laboratory_outbox_authority,
    laboratory_outbox_recovery_operator;
grant execute on function laboratory_security.authorized_tenant_id() to
    laboratory_outbox_authority,
    laboratory_outbox_recovery_operator;
grant execute on function laboratory_security.bind_tenant_context(jsonb) to
    laboratory_outbox_recovery_operator;

alter table public.transactional_outbox
    drop constraint outbox_delivery_state_coherent;
alter table public.transactional_outbox
    add constraint outbox_message_id_bounded check (
        message_id ~ '^[ -~]+$'
        and pg_catalog.octet_length(message_id) <= 256
        and pg_catalog.btrim(message_id) <> ''
    ),
    add constraint outbox_delivery_state_coherent check (
        delivery_attempts::bigint = fencing_token
        and (
            (
                delivery_state = 'ready'
                and lease_owner is null
                and lease_principal is null
                and lease_token is null
                and lease_expires_at_utc is null
                and last_error_code is null
                and delivered_at_utc is null
            )
            or (
                delivery_state = 'leased'
                and delivery_attempts >= 1
                and lease_owner is not null
                and lease_principal is not null
                and lease_token is not null
                and lease_expires_at_utc is not null
                and last_error_code is null
                and delivered_at_utc is null
            )
            or (
                delivery_state = 'delivered'
                and delivery_attempts >= 1
                and lease_owner is null
                and lease_principal is null
                and lease_token is null
                and lease_expires_at_utc is null
                and last_error_code is null
                and delivered_at_utc is not null
            )
            or (
                delivery_state = 'recovery_required'
                and delivery_attempts >= 1
                and lease_owner is null
                and lease_principal is null
                and lease_token is null
                and lease_expires_at_utc is null
                and last_error_code is not null
                and last_error_code ~ '^[A-Z0-9][A-Z0-9._:-]{0,127}$'
                and delivered_at_utc is null
            )
        )
    );

create table public.outbox_delivery_attempt (
    tenant_id text not null,
    message_id text not null,
    attempt_number integer not null check (attempt_number >= 1),
    fencing_token bigint not null check (
        fencing_token = attempt_number::bigint
    ),
    lease_token uuid not null,
    worker_instance text not null check (
        worker_instance ~ '^[ -~]{1,128}$'
        and pg_catalog.btrim(worker_instance) <> ''
    ),
    lease_principal name not null,
    opened_at_utc timestamptz not null check (pg_catalog.isfinite(opened_at_utc)),
    lease_expires_at_utc timestamptz not null check (
        pg_catalog.isfinite(lease_expires_at_utc)
        and lease_expires_at_utc > opened_at_utc
        and lease_expires_at_utc <= opened_at_utc + interval '15 minutes'
    ),
    primary key (tenant_id, message_id, attempt_number),
    unique (tenant_id, message_id, fencing_token),
    unique (tenant_id, message_id, lease_token),
    foreign key (tenant_id, message_id)
        references public.transactional_outbox(tenant_id, message_id)
);

create table public.outbox_delivery_attempt_outcome (
    tenant_id text not null,
    message_id text not null,
    attempt_number integer not null,
    outcome_kind text not null check (
        outcome_kind in ('lease_expired', 'delivery_confirmed', 'recovery_required')
    ),
    error_code text,
    transport_system text,
    transport_receipt text,
    transport_acknowledged_at_utc timestamptz,
    closed_at_utc timestamptz not null check (pg_catalog.isfinite(closed_at_utc)),
    primary key (tenant_id, message_id, attempt_number),
    unique (tenant_id, message_id, attempt_number, outcome_kind),
    unique (tenant_id, transport_system, transport_receipt),
    foreign key (tenant_id, message_id, attempt_number)
        references public.outbox_delivery_attempt(
            tenant_id, message_id, attempt_number
        ),
    check (
        (
            outcome_kind = 'lease_expired'
            and error_code is null
            and transport_system is null
            and transport_receipt is null
            and transport_acknowledged_at_utc is null
        )
        or (
            outcome_kind = 'delivery_confirmed'
            and error_code is null
            and transport_system is not null
            and transport_system ~ '^[ -~]{1,64}$'
            and pg_catalog.btrim(transport_system) <> ''
            and transport_receipt is not null
            and transport_receipt ~ '^[ -~]+$'
            and pg_catalog.octet_length(transport_receipt) <= 512
            and pg_catalog.btrim(transport_receipt) <> ''
            and transport_acknowledged_at_utc is not null
            and pg_catalog.isfinite(transport_acknowledged_at_utc)
            and transport_acknowledged_at_utc = closed_at_utc
        )
        or (
            outcome_kind = 'recovery_required'
            and error_code is not null
            and error_code ~ '^[A-Z0-9][A-Z0-9._:-]{0,127}$'
            and transport_system is null
            and transport_receipt is null
            and transport_acknowledged_at_utc is null
        )
    )
);

create table public.outbox_recovery_release (
    tenant_id text not null,
    message_id text not null,
    attempt_number integer not null,
    outcome_kind text not null default 'recovery_required' check (
        outcome_kind = 'recovery_required'
    ),
    error_code text not null check (
        error_code ~ '^[A-Z0-9][A-Z0-9._:-]{0,127}$'
    ),
    recovery_reference text not null check (
        recovery_reference ~ '^[ -~]+$'
        and pg_catalog.octet_length(recovery_reference) <= 256
        and pg_catalog.btrim(recovery_reference) <> ''
    ),
    released_by name not null,
    released_at_utc timestamptz not null check (pg_catalog.isfinite(released_at_utc)),
    available_at_utc timestamptz not null check (
        pg_catalog.isfinite(available_at_utc)
        and available_at_utc >= released_at_utc
        and available_at_utc <= released_at_utc
            + pg_catalog.make_interval(secs => 86400)
    ),
    primary key (tenant_id, message_id, attempt_number),
    foreign key (tenant_id, message_id, attempt_number, outcome_kind)
        references public.outbox_delivery_attempt_outcome(
            tenant_id, message_id, attempt_number, outcome_kind
        )
);

alter table public.outbox_delivery_attempt enable row level security;
alter table public.outbox_delivery_attempt force row level security;
alter table public.outbox_delivery_attempt_outcome enable row level security;
alter table public.outbox_delivery_attempt_outcome force row level security;
alter table public.outbox_recovery_release enable row level security;
alter table public.outbox_recovery_release force row level security;

create policy outbox_delivery_attempt_tenant_policy
on public.outbox_delivery_attempt
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy outbox_delivery_attempt_outcome_tenant_policy
on public.outbox_delivery_attempt_outcome
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());
create policy outbox_recovery_release_tenant_policy
on public.outbox_recovery_release
    using (tenant_id = laboratory_security.authorized_tenant_id())
    with check (tenant_id = laboratory_security.authorized_tenant_id());

create policy outbox_delivery_attempt_bounded_migration_policy
on public.outbox_delivery_attempt
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy outbox_delivery_attempt_outcome_bounded_migration_policy
on public.outbox_delivery_attempt_outcome
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());
create policy outbox_recovery_release_bounded_migration_policy
on public.outbox_recovery_release
    for all to laboratory_owner
    using (laboratory_security.bounded_migration_session_active())
    with check (laboratory_security.bounded_migration_session_active());

create trigger outbox_delivery_attempt_append_only
before update or delete on public.outbox_delivery_attempt
for each row execute function public.preserve_append_only_record();
create trigger outbox_delivery_attempt_outcome_append_only
before update or delete on public.outbox_delivery_attempt_outcome
for each row execute function public.preserve_append_only_record();
create trigger outbox_recovery_release_append_only
before update or delete on public.outbox_recovery_release
for each row execute function public.preserve_append_only_record();

revoke all privileges on public.transactional_outbox from laboratory_app;
grant select on public.transactional_outbox to laboratory_app;
grant insert (
    tenant_id,
    message_id,
    topic,
    aggregate_id,
    aggregate_version,
    payload,
    payload_sha256,
    payload_canonicalization,
    available_at_utc
) on public.transactional_outbox to laboratory_app;
revoke all privileges on public.transactional_outbox
    from laboratory_outbox_worker, laboratory_outbox_recovery_operator;
grant select on public.transactional_outbox to
    laboratory_outbox_worker,
    laboratory_outbox_recovery_operator;
revoke all privileges on
    public.outbox_delivery_attempt,
    public.outbox_delivery_attempt_outcome,
    public.outbox_recovery_release
from public, laboratory_app, laboratory_owner,
    laboratory_outbox_worker, laboratory_outbox_recovery_operator;
grant select on
    public.outbox_delivery_attempt,
    public.outbox_delivery_attempt_outcome
to laboratory_outbox_worker, laboratory_outbox_recovery_operator;
grant select on public.outbox_recovery_release
to laboratory_outbox_recovery_operator;

drop trigger transactional_outbox_delivery_transition
    on public.transactional_outbox;

create or replace function public.preserve_outbox_delivery_transition()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $transition_guard$
declare
    observed_value timestamptz := pg_catalog.clock_timestamp();
begin
    if tg_op = 'INSERT' then
        if new.delivery_state <> 'ready'
           or new.delivery_attempts <> 0
           or new.fencing_token <> 0
           or new.lease_owner is not null
           or new.lease_principal is not null
           or new.lease_token is not null
           or new.lease_expires_at_utc is not null
           or new.last_error_code is not null
           or new.delivered_at_utc is not null then
            raise exception 'an outbox message begins in the ready state';
        end if;
        return new;
    end if;

    if new.delivery_attempts < old.delivery_attempts then
        raise exception 'outbox delivery attempts advance monotonically';
    end if;
    if new.fencing_token < old.fencing_token then
        raise exception 'outbox fencing tokens advance monotonically';
    end if;

    if old.delivery_state = 'ready' and new.delivery_state = 'leased' then
        if old.available_at_utc > observed_value
           or new.available_at_utc is distinct from old.available_at_utc
           or new.delivery_attempts <> old.delivery_attempts + 1
           or new.fencing_token <> old.fencing_token + 1
           or new.lease_owner is null
           or new.lease_principal is null
           or new.lease_token is null
           or new.lease_expires_at_utc <= observed_value
           or new.lease_expires_at_utc > observed_value + interval '15 minutes'
           or new.last_error_code is not null
           or new.delivered_at_utc is not null
           or not exists (
                select 1
                  from public.outbox_delivery_attempt as attempt
                 where attempt.tenant_id = new.tenant_id
                   and attempt.message_id = new.message_id
                   and attempt.attempt_number = new.delivery_attempts
                   and attempt.fencing_token = new.fencing_token
                   and attempt.lease_token = new.lease_token
                   and attempt.worker_instance = new.lease_owner
                   and attempt.lease_principal = new.lease_principal
                   and attempt.lease_expires_at_utc = new.lease_expires_at_utc
                   and not exists (
                        select 1
                          from public.outbox_delivery_attempt_outcome as outcome
                         where outcome.tenant_id = attempt.tenant_id
                           and outcome.message_id = attempt.message_id
                           and outcome.attempt_number = attempt.attempt_number
                   )
           ) then
            raise exception 'ready-to-leased requires one current immutable attempt';
        end if;
    elsif old.delivery_state = 'leased' and new.delivery_state = 'leased' then
        if old.lease_expires_at_utc > observed_value
           or new.available_at_utc is distinct from old.available_at_utc
           or new.delivery_attempts <> old.delivery_attempts + 1
           or new.fencing_token <> old.fencing_token + 1
           or new.lease_token is not distinct from old.lease_token
           or new.lease_expires_at_utc <= observed_value
           or new.lease_expires_at_utc > observed_value + interval '15 minutes'
           or new.last_error_code is not null
           or new.delivered_at_utc is not null
           or not exists (
                select 1
                  from public.outbox_delivery_attempt_outcome as outcome
                 where outcome.tenant_id = old.tenant_id
                   and outcome.message_id = old.message_id
                   and outcome.attempt_number = old.delivery_attempts
                   and outcome.outcome_kind = 'lease_expired'
                   and outcome.closed_at_utc >= old.lease_expires_at_utc
           )
           or not exists (
                select 1
                  from public.outbox_delivery_attempt as attempt
                 where attempt.tenant_id = new.tenant_id
                   and attempt.message_id = new.message_id
                   and attempt.attempt_number = new.delivery_attempts
                   and attempt.fencing_token = new.fencing_token
                   and attempt.lease_token = new.lease_token
                   and attempt.worker_instance = new.lease_owner
                   and attempt.lease_principal = new.lease_principal
                   and attempt.lease_expires_at_utc = new.lease_expires_at_utc
                   and not exists (
                        select 1
                          from public.outbox_delivery_attempt_outcome as outcome
                         where outcome.tenant_id = attempt.tenant_id
                           and outcome.message_id = attempt.message_id
                           and outcome.attempt_number = attempt.attempt_number
                   )
           ) then
            raise exception 'leased-to-leased requires expiry evidence and a new immutable attempt';
        end if;
    elsif old.delivery_state = 'leased' and new.delivery_state = 'delivered' then
        if new.available_at_utc is distinct from old.available_at_utc
           or new.delivery_attempts <> old.delivery_attempts
           or new.fencing_token <> old.fencing_token
           or new.lease_owner is not null
           or new.lease_principal is not null
           or new.lease_token is not null
           or new.lease_expires_at_utc is not null
           or new.last_error_code is not null
           or new.delivered_at_utc is null
           or not exists (
                select 1
                  from public.outbox_delivery_attempt_outcome as outcome
                 where outcome.tenant_id = old.tenant_id
                   and outcome.message_id = old.message_id
                   and outcome.attempt_number = old.delivery_attempts
                   and outcome.outcome_kind = 'delivery_confirmed'
                   and outcome.transport_acknowledged_at_utc = new.delivered_at_utc
                   and outcome.closed_at_utc < old.lease_expires_at_utc
           ) then
            raise exception 'leased-to-delivered requires the current transport receipt';
        end if;
    elsif old.delivery_state = 'leased'
          and new.delivery_state = 'recovery_required' then
        if new.available_at_utc is distinct from old.available_at_utc
           or new.delivery_attempts <> old.delivery_attempts
           or new.fencing_token <> old.fencing_token
           or new.lease_owner is not null
           or new.lease_principal is not null
           or new.lease_token is not null
           or new.lease_expires_at_utc is not null
           or new.last_error_code is null
           or new.delivered_at_utc is not null
           or not exists (
                select 1
                  from public.outbox_delivery_attempt_outcome as outcome
                 where outcome.tenant_id = old.tenant_id
                   and outcome.message_id = old.message_id
                   and outcome.attempt_number = old.delivery_attempts
                   and outcome.outcome_kind = 'recovery_required'
                   and outcome.error_code = new.last_error_code
                   and outcome.closed_at_utc < old.lease_expires_at_utc
           ) then
            raise exception 'leased-to-recovery requires the current failure outcome';
        end if;
    elsif old.delivery_state = 'recovery_required'
          and new.delivery_state = 'ready' then
        if new.delivery_attempts <> old.delivery_attempts
           or new.fencing_token <> old.fencing_token
           or new.lease_owner is not null
           or new.lease_principal is not null
           or new.lease_token is not null
           or new.lease_expires_at_utc is not null
           or new.last_error_code is not null
           or new.delivered_at_utc is not null
           or not exists (
                select 1
                  from public.outbox_recovery_release as recovery
                 where recovery.tenant_id = old.tenant_id
                   and recovery.message_id = old.message_id
                   and recovery.attempt_number = old.delivery_attempts
                   and recovery.error_code = old.last_error_code
                   and recovery.available_at_utc = new.available_at_utc
           ) then
            raise exception 'recovery-to-ready requires an immutable release decision';
        end if;
    else
        raise exception 'outbox transition requires a released state-machine edge';
    end if;
    return new;
end;
$transition_guard$;

revoke all on function public.preserve_outbox_delivery_transition() from public;

create trigger transactional_outbox_delivery_transition
before insert or update on public.transactional_outbox
for each row execute function public.preserve_outbox_delivery_transition();

revoke all on function public.claim_outbox_delivery(text, interval)
    from laboratory_outbox_worker;
revoke all on function public.reclaim_outbox_delivery(text, bigint, text, interval)
    from laboratory_outbox_worker;
revoke all on function public.confirm_outbox_delivery(text, text, uuid, bigint)
    from laboratory_outbox_worker;
drop function public.claim_outbox_delivery(text, interval);
drop function public.reclaim_outbox_delivery(text, bigint, text, interval);
drop function public.confirm_outbox_delivery(text, text, uuid, bigint);

create function public.claim_outbox_delivery(
    worker_instance_value text,
    lease_duration_seconds_value integer
)
returns public.transactional_outbox
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $claim$
declare
    tenant_value text;
    pending_value public.transactional_outbox%rowtype;
    claimed_value public.transactional_outbox%rowtype;
    opened_value timestamptz;
    expires_value timestamptz;
    lease_token_value uuid;
begin
    tenant_value := laboratory_security.authorized_tenant_id();
    if worker_instance_value is null
       or worker_instance_value !~ '^[ -~]{1,128}$'
       or pg_catalog.btrim(worker_instance_value) = ''
       or lease_duration_seconds_value is null
       or lease_duration_seconds_value not between 1 and 900 then
        raise exception using
            errcode = '22023',
            message = 'outbox claim requires a bounded worker label and 1..900 lease seconds';
    end if;

    select pending.*
      into pending_value
      from public.transactional_outbox as pending
     where pending.tenant_id = tenant_value
       and pending.delivery_state = 'ready'
       and pending.available_at_utc <= pg_catalog.clock_timestamp()
     order by pending.available_at_utc, pending.message_id
     for update skip locked
     limit 1;
    if not found then
        raise exception using
            errcode = 'P0002',
            message = 'outbox claim requires one available tenant message';
    end if;

    opened_value := pg_catalog.clock_timestamp();
    expires_value := opened_value
        + pg_catalog.make_interval(secs => lease_duration_seconds_value);
    lease_token_value := pg_catalog.gen_random_uuid();
    insert into public.outbox_delivery_attempt (
        tenant_id,
        message_id,
        attempt_number,
        fencing_token,
        lease_token,
        worker_instance,
        lease_principal,
        opened_at_utc,
        lease_expires_at_utc
    ) values (
        tenant_value,
        pending_value.message_id,
        pending_value.delivery_attempts + 1,
        pending_value.fencing_token + 1,
        lease_token_value,
        worker_instance_value,
        session_user,
        opened_value,
        expires_value
    );

    update public.transactional_outbox as delivery
       set delivery_state = 'leased',
           delivery_attempts = delivery.delivery_attempts + 1,
           lease_owner = worker_instance_value,
           lease_principal = session_user,
           lease_token = lease_token_value,
           fencing_token = delivery.fencing_token + 1,
           lease_expires_at_utc = expires_value,
           last_error_code = null,
           delivered_at_utc = null
     where delivery.tenant_id = tenant_value
       and delivery.message_id = pending_value.message_id
       and delivery.delivery_state = 'ready'
    returning delivery.* into claimed_value;
    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox claim requires the locked ready coordinate';
    end if;
    return claimed_value;
end;
$claim$;

create function public.reclaim_outbox_delivery(
    message_value text,
    expected_fencing_value bigint,
    worker_instance_value text,
    lease_duration_seconds_value integer
)
returns public.transactional_outbox
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $reclaim$
declare
    tenant_value text;
    current_value public.transactional_outbox%rowtype;
    reclaimed_value public.transactional_outbox%rowtype;
    observed_value timestamptz;
    expires_value timestamptz;
    lease_token_value uuid;
begin
    tenant_value := laboratory_security.authorized_tenant_id();
    if message_value is null
       or message_value !~ '^[ -~]+$'
       or pg_catalog.octet_length(message_value) > 256
       or pg_catalog.btrim(message_value) = ''
       or expected_fencing_value is null
       or expected_fencing_value < 1
       or worker_instance_value is null
       or worker_instance_value !~ '^[ -~]{1,128}$'
       or pg_catalog.btrim(worker_instance_value) = ''
       or lease_duration_seconds_value is null
       or lease_duration_seconds_value not between 1 and 900 then
        raise exception using
            errcode = '22023',
            message = 'outbox reclaim requires bounded message, fence, worker, and 1..900 lease seconds';
    end if;

    select delivery.*
      into current_value
      from public.transactional_outbox as delivery
     where delivery.tenant_id = tenant_value
       and delivery.message_id = message_value
       and delivery.delivery_state = 'leased'
       and delivery.fencing_token = expected_fencing_value
       and delivery.lease_expires_at_utc <= pg_catalog.clock_timestamp()
     for update;
    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox reclaim requires the current expired lease fence';
    end if;

    observed_value := pg_catalog.clock_timestamp();
    insert into public.outbox_delivery_attempt_outcome (
        tenant_id, message_id, attempt_number, outcome_kind, closed_at_utc
    ) values (
        tenant_value,
        message_value,
        current_value.delivery_attempts,
        'lease_expired',
        observed_value
    );

    expires_value := observed_value
        + pg_catalog.make_interval(secs => lease_duration_seconds_value);
    lease_token_value := pg_catalog.gen_random_uuid();
    insert into public.outbox_delivery_attempt (
        tenant_id,
        message_id,
        attempt_number,
        fencing_token,
        lease_token,
        worker_instance,
        lease_principal,
        opened_at_utc,
        lease_expires_at_utc
    ) values (
        tenant_value,
        message_value,
        current_value.delivery_attempts + 1,
        current_value.fencing_token + 1,
        lease_token_value,
        worker_instance_value,
        session_user,
        observed_value,
        expires_value
    );

    update public.transactional_outbox as delivery
       set delivery_attempts = delivery.delivery_attempts + 1,
           lease_owner = worker_instance_value,
           lease_principal = session_user,
           lease_token = lease_token_value,
           fencing_token = delivery.fencing_token + 1,
           lease_expires_at_utc = expires_value,
           last_error_code = null
     where delivery.tenant_id = tenant_value
       and delivery.message_id = message_value
       and delivery.delivery_state = 'leased'
       and delivery.fencing_token = expected_fencing_value
    returning delivery.* into reclaimed_value;
    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox reclaim requires the locked expired lease coordinate';
    end if;
    return reclaimed_value;
end;
$reclaim$;

create function public.confirm_outbox_delivery(
    message_value text,
    worker_instance_value text,
    lease_token_value uuid,
    fencing_token_value bigint,
    transport_system_value text,
    transport_receipt_value text
)
returns public.transactional_outbox
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $confirm$
declare
    tenant_value text;
    current_value public.transactional_outbox%rowtype;
    confirmed_value public.transactional_outbox%rowtype;
    acknowledged_value timestamptz;
begin
    tenant_value := laboratory_security.authorized_tenant_id();
    if message_value is null
       or message_value !~ '^[ -~]+$'
       or pg_catalog.octet_length(message_value) > 256
       or pg_catalog.btrim(message_value) = ''
       or worker_instance_value is null
       or worker_instance_value !~ '^[ -~]{1,128}$'
       or pg_catalog.btrim(worker_instance_value) = ''
       or lease_token_value is null
       or fencing_token_value is null
       or fencing_token_value < 1
       or transport_system_value is null
       or transport_system_value !~ '^[ -~]{1,64}$'
       or pg_catalog.btrim(transport_system_value) = ''
       or transport_receipt_value is null
       or transport_receipt_value !~ '^[ -~]+$'
       or pg_catalog.octet_length(transport_receipt_value) > 512
       or pg_catalog.btrim(transport_receipt_value) = '' then
        raise exception using
            errcode = '22023',
            message = 'outbox confirmation requires the lease coordinate and bounded transport receipt';
    end if;

    select delivery.*
      into current_value
      from public.transactional_outbox as delivery
     where delivery.tenant_id = tenant_value
       and delivery.message_id = message_value
       and delivery.delivery_state = 'leased'
       and delivery.lease_principal = session_user
       and delivery.lease_owner = worker_instance_value
       and delivery.lease_token = lease_token_value
       and delivery.fencing_token = fencing_token_value
       and delivery.lease_expires_at_utc > pg_catalog.clock_timestamp()
     for update;
    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox confirmation requires the current unexpired lease coordinate';
    end if;

    acknowledged_value := pg_catalog.clock_timestamp();
    if acknowledged_value >= current_value.lease_expires_at_utc then
        raise exception using
            errcode = '40001',
            message = 'outbox confirmation requires acknowledgement inside the current lease';
    end if;
    insert into public.outbox_delivery_attempt_outcome (
        tenant_id,
        message_id,
        attempt_number,
        outcome_kind,
        transport_system,
        transport_receipt,
        transport_acknowledged_at_utc,
        closed_at_utc
    ) values (
        tenant_value,
        message_value,
        current_value.delivery_attempts,
        'delivery_confirmed',
        transport_system_value,
        transport_receipt_value,
        acknowledged_value,
        acknowledged_value
    );

    update public.transactional_outbox as delivery
       set delivery_state = 'delivered',
           lease_owner = null,
           lease_principal = null,
           lease_token = null,
           lease_expires_at_utc = null,
           last_error_code = null,
           delivered_at_utc = acknowledged_value
     where delivery.tenant_id = tenant_value
       and delivery.message_id = message_value
       and delivery.delivery_state = 'leased'
       and delivery.lease_principal = session_user
       and delivery.lease_owner = worker_instance_value
       and delivery.lease_token = lease_token_value
       and delivery.fencing_token = fencing_token_value
    returning delivery.* into confirmed_value;
    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox confirmation requires the locked lease coordinate';
    end if;
    return confirmed_value;
end;
$confirm$;

create function public.fail_outbox_delivery(
    message_value text,
    worker_instance_value text,
    lease_token_value uuid,
    fencing_token_value bigint,
    error_code_value text
)
returns public.transactional_outbox
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $fail$
declare
    tenant_value text;
    current_value public.transactional_outbox%rowtype;
    failed_value public.transactional_outbox%rowtype;
    closed_value timestamptz;
begin
    tenant_value := laboratory_security.authorized_tenant_id();
    if message_value is null
       or message_value !~ '^[ -~]+$'
       or pg_catalog.octet_length(message_value) > 256
       or pg_catalog.btrim(message_value) = ''
       or worker_instance_value is null
       or worker_instance_value !~ '^[ -~]{1,128}$'
       or pg_catalog.btrim(worker_instance_value) = ''
       or lease_token_value is null
       or fencing_token_value is null
       or fencing_token_value < 1
       or error_code_value is null
       or error_code_value !~ '^[A-Z0-9][A-Z0-9._:-]{0,127}$' then
        raise exception using
            errcode = '22023',
            message = 'outbox failure requires the lease coordinate and bounded error code';
    end if;

    select delivery.*
      into current_value
      from public.transactional_outbox as delivery
     where delivery.tenant_id = tenant_value
       and delivery.message_id = message_value
       and delivery.delivery_state = 'leased'
       and delivery.lease_principal = session_user
       and delivery.lease_owner = worker_instance_value
       and delivery.lease_token = lease_token_value
       and delivery.fencing_token = fencing_token_value
       and delivery.lease_expires_at_utc > pg_catalog.clock_timestamp()
     for update;
    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox failure requires the current unexpired lease coordinate';
    end if;

    closed_value := pg_catalog.clock_timestamp();
    if closed_value >= current_value.lease_expires_at_utc then
        raise exception using
            errcode = '40001',
            message = 'outbox failure requires observation inside the current lease';
    end if;
    insert into public.outbox_delivery_attempt_outcome (
        tenant_id,
        message_id,
        attempt_number,
        outcome_kind,
        error_code,
        closed_at_utc
    ) values (
        tenant_value,
        message_value,
        current_value.delivery_attempts,
        'recovery_required',
        error_code_value,
        closed_value
    );

    update public.transactional_outbox as delivery
       set delivery_state = 'recovery_required',
           lease_owner = null,
           lease_principal = null,
           lease_token = null,
           lease_expires_at_utc = null,
           last_error_code = error_code_value,
           delivered_at_utc = null
     where delivery.tenant_id = tenant_value
       and delivery.message_id = message_value
       and delivery.delivery_state = 'leased'
       and delivery.lease_principal = session_user
       and delivery.lease_owner = worker_instance_value
       and delivery.lease_token = lease_token_value
       and delivery.fencing_token = fencing_token_value
    returning delivery.* into failed_value;
    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox failure requires the locked lease coordinate';
    end if;
    return failed_value;
end;
$fail$;

create function public.release_outbox_recovery(
    message_value text,
    expected_fencing_value bigint,
    available_delay_seconds_value integer,
    recovery_reference_value text
)
returns public.transactional_outbox
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $release_recovery$
declare
    tenant_value text;
    current_value public.transactional_outbox%rowtype;
    released_value public.transactional_outbox%rowtype;
    released_at_value timestamptz;
    available_at_value timestamptz;
begin
    tenant_value := laboratory_security.authorized_tenant_id();
    if message_value is null
       or message_value !~ '^[ -~]+$'
       or pg_catalog.octet_length(message_value) > 256
       or pg_catalog.btrim(message_value) = ''
       or expected_fencing_value is null
       or expected_fencing_value < 1
       or available_delay_seconds_value is null
       or available_delay_seconds_value not between 0 and 86400
       or recovery_reference_value is null
       or recovery_reference_value !~ '^[ -~]+$'
       or pg_catalog.octet_length(recovery_reference_value) > 256
       or pg_catalog.btrim(recovery_reference_value) = '' then
        raise exception using
            errcode = '22023',
            message = 'outbox recovery release requires bounded fence, delay, and reference';
    end if;

    select delivery.*
      into current_value
      from public.transactional_outbox as delivery
     where delivery.tenant_id = tenant_value
       and delivery.message_id = message_value
       and delivery.delivery_state = 'recovery_required'
       and delivery.fencing_token = expected_fencing_value
     for update;
    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox recovery release requires the current recovery fence';
    end if;

    released_at_value := pg_catalog.clock_timestamp();
    available_at_value := released_at_value
        + pg_catalog.make_interval(secs => available_delay_seconds_value);
    insert into public.outbox_recovery_release (
        tenant_id,
        message_id,
        attempt_number,
        outcome_kind,
        error_code,
        recovery_reference,
        released_by,
        released_at_utc,
        available_at_utc
    ) values (
        tenant_value,
        message_value,
        current_value.delivery_attempts,
        'recovery_required',
        current_value.last_error_code,
        recovery_reference_value,
        session_user,
        released_at_value,
        available_at_value
    );

    update public.transactional_outbox as delivery
       set delivery_state = 'ready',
           available_at_utc = available_at_value,
           lease_owner = null,
           lease_principal = null,
           lease_token = null,
           lease_expires_at_utc = null,
           last_error_code = null,
           delivered_at_utc = null
     where delivery.tenant_id = tenant_value
       and delivery.message_id = message_value
       and delivery.delivery_state = 'recovery_required'
       and delivery.fencing_token = expected_fencing_value
    returning delivery.* into released_value;
    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox recovery release requires the locked recovery coordinate';
    end if;
    return released_value;
end;
$release_recovery$;

revoke all on function public.claim_outbox_delivery(text, integer) from public;
revoke all on function public.reclaim_outbox_delivery(text, bigint, text, integer)
    from public;
revoke all on function public.confirm_outbox_delivery(
    text, text, uuid, bigint, text, text
) from public;
revoke all on function public.fail_outbox_delivery(
    text, text, uuid, bigint, text
) from public;
revoke all on function public.release_outbox_recovery(
    text, bigint, integer, text
) from public;

grant execute on function public.claim_outbox_delivery(text, integer)
    to laboratory_outbox_worker;
grant execute on function public.reclaim_outbox_delivery(
    text, bigint, text, integer
) to laboratory_outbox_worker;
grant execute on function public.confirm_outbox_delivery(
    text, text, uuid, bigint, text, text
) to laboratory_outbox_worker;
grant execute on function public.fail_outbox_delivery(
    text, text, uuid, bigint, text
) to laboratory_outbox_worker;
grant execute on function public.release_outbox_recovery(
    text, bigint, integer, text
) to laboratory_outbox_recovery_operator;

grant create on schema public to laboratory_outbox_authority;

alter table public.outbox_delivery_attempt owner to laboratory_outbox_authority;
alter table public.outbox_delivery_attempt_outcome owner to laboratory_outbox_authority;
alter table public.outbox_recovery_release owner to laboratory_outbox_authority;
alter table public.transactional_outbox owner to laboratory_outbox_authority;

alter function public.preserve_outbox_delivery_transition()
    owner to laboratory_outbox_authority;
alter function public.claim_outbox_delivery(text, integer)
    owner to laboratory_outbox_authority;
alter function public.reclaim_outbox_delivery(text, bigint, text, integer)
    owner to laboratory_outbox_authority;
alter function public.confirm_outbox_delivery(text, text, uuid, bigint, text, text)
    owner to laboratory_outbox_authority;
alter function public.fail_outbox_delivery(text, text, uuid, bigint, text)
    owner to laboratory_outbox_authority;
alter function public.release_outbox_recovery(text, bigint, integer, text)
    owner to laboratory_outbox_authority;

set local role laboratory_outbox_authority;

revoke all privileges on public.transactional_outbox
from laboratory_outbox_authority;
grant select, insert, update on public.transactional_outbox
to laboratory_outbox_authority;
grant select, insert, update on
    public.outbox_delivery_attempt,
    public.outbox_delivery_attempt_outcome
to laboratory_outbox_authority;
grant select, insert on
    public.outbox_recovery_release
to laboratory_outbox_authority;

grant insert (
    tenant_id,
    message_id,
    topic,
    aggregate_id,
    aggregate_version,
    payload,
    payload_sha256,
    payload_canonicalization,
    available_at_utc
) on public.transactional_outbox to laboratory_owner;

set local role laboratory_owner;

revoke create on schema public from laboratory_outbox_authority;
