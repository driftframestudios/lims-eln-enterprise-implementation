-- TARGET: privileged routines resolve every data object through its released schema.
-- TARGET: outbox delivery advances only through tenant-bound lease coordinates.

do $migration_preflight$
begin
    if exists (
        select 1
          from public.transactional_outbox
         where delivery_state = 'leased'
    ) then
        raise exception using
            errcode = '55000',
            message = 'migration 003 requires a drained outbox lease set';
    end if;
end;
$migration_preflight$;

alter table public.transactional_outbox
    add column lease_principal name;

alter table public.transactional_outbox
    drop constraint outbox_delivery_state_coherent;

alter table public.transactional_outbox
    add constraint outbox_delivery_state_coherent check (
        (
            delivery_state = 'ready'
            and lease_owner is null
            and lease_principal is null
            and lease_token is null
            and lease_expires_at_utc is null
            and delivered_at_utc is null
        )
        or (
            delivery_state = 'leased'
            and lease_owner is not null
            and lease_principal is not null
            and lease_token is not null
            and lease_expires_at_utc is not null
            and delivered_at_utc is null
            and fencing_token >= 1
        )
        or (
            delivery_state = 'delivered'
            and lease_owner is null
            and lease_principal is null
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

create function public.preserve_outbox_delivery_transition()
returns trigger
language plpgsql
set search_path = pg_catalog, pg_temp
as $transition_guard$
begin
    if new.delivery_attempts < old.delivery_attempts then
        raise exception 'outbox delivery attempts advance monotonically';
    end if;
    if new.fencing_token < old.fencing_token then
        raise exception 'outbox fencing tokens advance monotonically';
    end if;
    if old.delivery_state = 'delivered' and (
        new.delivery_state is distinct from old.delivery_state
        or new.delivery_attempts is distinct from old.delivery_attempts
        or new.available_at_utc is distinct from old.available_at_utc
        or new.lease_owner is distinct from old.lease_owner
        or new.lease_principal is distinct from old.lease_principal
        or new.lease_token is distinct from old.lease_token
        or new.fencing_token is distinct from old.fencing_token
        or new.lease_expires_at_utc is distinct from old.lease_expires_at_utc
        or new.last_error_code is distinct from old.last_error_code
        or new.delivered_at_utc is distinct from old.delivered_at_utc
    ) then
        raise exception 'delivered outbox coordinates are terminal evidence';
    end if;
    if new.delivery_state = 'leased' then
        if old.delivery_state = 'ready' then
            if new.delivery_attempts <> old.delivery_attempts + 1
               or new.fencing_token <> old.fencing_token + 1 then
                raise exception 'an initial outbox lease advances attempt and fence once';
            end if;
        elsif old.delivery_state = 'leased' then
            if old.lease_expires_at_utc > pg_catalog.clock_timestamp()
               or new.delivery_attempts <> old.delivery_attempts + 1
               or new.fencing_token <> old.fencing_token + 1
               or new.lease_token is not distinct from old.lease_token then
                raise exception 'outbox reclaim rotates an expired lease and advances its fence';
            end if;
        else
            raise exception 'outbox leasing begins from ready or expired leased state';
        end if;
        if new.lease_expires_at_utc <= pg_catalog.clock_timestamp() then
            raise exception 'outbox lease expiry requires a future database time';
        end if;
    elsif new.delivery_state = 'delivered' then
        if old.delivery_state <> 'leased'
           or new.delivery_attempts <> old.delivery_attempts
           or new.fencing_token <> old.fencing_token then
            raise exception 'outbox delivery completes the current leased attempt';
        end if;
    end if;
    return new;
end;
$transition_guard$;

alter function public.preserve_outbox_delivery_transition()
    owner to laboratory_owner;
revoke all on function public.preserve_outbox_delivery_transition() from public;

create trigger transactional_outbox_delivery_transition
before update on public.transactional_outbox
for each row execute function public.preserve_outbox_delivery_transition();

revoke update (
    delivery_state,
    delivery_attempts,
    available_at_utc,
    lease_owner,
    lease_token,
    fencing_token,
    lease_expires_at_utc,
    last_error_code,
    delivered_at_utc
) on public.transactional_outbox from laboratory_outbox_worker;
revoke all privileges on public.transactional_outbox from laboratory_outbox_worker;
grant select on public.transactional_outbox to laboratory_outbox_worker;

create function public.claim_outbox_delivery(
    worker_instance_value text,
    lease_duration_value interval
)
returns public.transactional_outbox
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $claim$
declare
    tenant_value text;
    claimed public.transactional_outbox%rowtype;
begin
    tenant_value := laboratory_security.authorized_tenant_id();
    if worker_instance_value is null
       or worker_instance_value !~ '^[ -~]{1,128}$'
       or pg_catalog.btrim(worker_instance_value) = ''
       or lease_duration_value is null
       or lease_duration_value <= interval '0 seconds'
       or lease_duration_value > interval '15 minutes' then
        raise exception using
            errcode = '22023',
            message = 'outbox claim requires a bounded worker label and lease duration';
    end if;

    with candidate as (
        select pending.tenant_id, pending.message_id
          from public.transactional_outbox as pending
         where pending.tenant_id = tenant_value
           and pending.delivery_state = 'ready'
           and pending.available_at_utc <= pg_catalog.clock_timestamp()
         order by pending.available_at_utc, pending.message_id
         for update skip locked
         limit 1
    )
    update public.transactional_outbox as delivery
       set delivery_state = 'leased',
           delivery_attempts = delivery.delivery_attempts + 1,
           lease_owner = worker_instance_value,
           lease_principal = session_user,
           lease_token = pg_catalog.gen_random_uuid(),
           fencing_token = delivery.fencing_token + 1,
           lease_expires_at_utc = pg_catalog.clock_timestamp() + lease_duration_value,
           last_error_code = null,
           delivered_at_utc = null
      from candidate
     where delivery.tenant_id = tenant_value
       and delivery.tenant_id = candidate.tenant_id
       and delivery.message_id = candidate.message_id
    returning delivery.* into claimed;

    if not found then
        raise exception using
            errcode = 'P0002',
            message = 'outbox claim requires one available tenant message';
    end if;
    return claimed;
end;
$claim$;

create function public.reclaim_outbox_delivery(
    message_value text,
    expected_fencing_value bigint,
    worker_instance_value text,
    lease_duration_value interval
)
returns public.transactional_outbox
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $reclaim$
declare
    tenant_value text;
    reclaimed public.transactional_outbox%rowtype;
begin
    tenant_value := laboratory_security.authorized_tenant_id();
    if message_value is null
       or expected_fencing_value is null
       or expected_fencing_value < 1
       or worker_instance_value is null
       or worker_instance_value !~ '^[ -~]{1,128}$'
       or pg_catalog.btrim(worker_instance_value) = ''
       or lease_duration_value is null
       or lease_duration_value <= interval '0 seconds'
       or lease_duration_value > interval '15 minutes' then
        raise exception using
            errcode = '22023',
            message = 'outbox reclaim requires a bounded message, fence, worker, and lease duration';
    end if;

    update public.transactional_outbox as delivery
       set delivery_attempts = delivery.delivery_attempts + 1,
           lease_owner = worker_instance_value,
           lease_principal = session_user,
           lease_token = pg_catalog.gen_random_uuid(),
           fencing_token = delivery.fencing_token + 1,
           lease_expires_at_utc = pg_catalog.clock_timestamp() + lease_duration_value,
           last_error_code = null
     where delivery.tenant_id = tenant_value
       and delivery.message_id = message_value
       and delivery.delivery_state = 'leased'
       and delivery.fencing_token = expected_fencing_value
       and delivery.lease_expires_at_utc <= pg_catalog.clock_timestamp()
    returning delivery.* into reclaimed;

    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox reclaim requires the current expired lease fence';
    end if;
    return reclaimed;
end;
$reclaim$;

create function public.confirm_outbox_delivery(
    message_value text,
    worker_instance_value text,
    lease_token_value uuid,
    fencing_token_value bigint
)
returns public.transactional_outbox
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $confirm$
declare
    tenant_value text;
    confirmed public.transactional_outbox%rowtype;
begin
    tenant_value := laboratory_security.authorized_tenant_id();
    if message_value is null
       or worker_instance_value is null
       or worker_instance_value !~ '^[ -~]{1,128}$'
       or pg_catalog.btrim(worker_instance_value) = ''
       or lease_token_value is null
       or fencing_token_value is null
       or fencing_token_value < 1 then
        raise exception using
            errcode = '22023',
            message = 'outbox confirmation requires the complete lease coordinate';
    end if;

    update public.transactional_outbox as delivery
       set delivery_state = 'delivered',
           lease_owner = null,
           lease_principal = null,
           lease_token = null,
           lease_expires_at_utc = null,
           last_error_code = null,
           delivered_at_utc = pg_catalog.clock_timestamp()
     where delivery.tenant_id = tenant_value
       and delivery.message_id = message_value
       and delivery.delivery_state = 'leased'
       and delivery.lease_principal = session_user
       and delivery.lease_owner = worker_instance_value
       and delivery.lease_token = lease_token_value
       and delivery.fencing_token = fencing_token_value
       and delivery.lease_expires_at_utc > pg_catalog.clock_timestamp()
    returning delivery.* into confirmed;

    if not found then
        raise exception using
            errcode = '40001',
            message = 'outbox confirmation requires the current unexpired lease coordinate';
    end if;
    return confirmed;
end;
$confirm$;

alter function public.claim_outbox_delivery(text, interval)
    owner to laboratory_owner;
alter function public.reclaim_outbox_delivery(text, bigint, text, interval)
    owner to laboratory_owner;
alter function public.confirm_outbox_delivery(text, text, uuid, bigint)
    owner to laboratory_owner;
revoke all on function public.claim_outbox_delivery(text, interval) from public;
revoke all on function public.reclaim_outbox_delivery(
    text, bigint, text, interval
) from public;
revoke all on function public.confirm_outbox_delivery(
    text, text, uuid, bigint
) from public;
grant execute on function public.claim_outbox_delivery(text, interval)
    to laboratory_outbox_worker;
grant execute on function public.reclaim_outbox_delivery(
    text, bigint, text, interval
) to laboratory_outbox_worker;
grant execute on function public.confirm_outbox_delivery(
    text, text, uuid, bigint
) to laboratory_outbox_worker;

create or replace function public.record_custody_transfer(
    specimen_value text,
    destination_value text,
    custodian_value text,
    expected_version_value bigint,
    transfer_value text,
    occurred_value timestamptz
)
returns public.custody_position
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $custody_transfer$
declare
    tenant_value text;
    current_position public.custody_position%rowtype;
    prior_event public.custody_event%rowtype;
    next_position public.custody_position%rowtype;
    recorded_value timestamptz;
    payload_value jsonb;
    payload_digest_value text;
begin
    tenant_value := laboratory_security.authorized_tenant_id();
    if specimen_value !~ '^[ -~]+$'
       or pg_catalog.char_length(specimen_value) > 256
       or pg_catalog.btrim(specimen_value) = ''
       or destination_value !~ '^[ -~]+$'
       or pg_catalog.char_length(destination_value) > 256
       or pg_catalog.btrim(destination_value) = ''
       or custodian_value !~ '^[ -~]+$'
       or pg_catalog.char_length(custodian_value) > 256
       or pg_catalog.btrim(custodian_value) = ''
       or transfer_value !~ '^[ -~]+$'
       or pg_catalog.char_length(transfer_value) > 256
       or pg_catalog.btrim(transfer_value) = ''
       or expected_version_value < 0 then
        raise exception using
            errcode = '22023',
            message = 'custody transfer requires released identity and revision formats';
    end if;

    select *
      into prior_event
      from public.custody_event
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
        )::public.custody_position;
    end if;

    select *
      into current_position
      from public.custody_position
     where tenant_id = tenant_value
       and specimen_id = specimen_value
     for update;
    if coalesce(current_position.custody_version, 0)
       <> expected_version_value then
        raise exception using
            errcode = '40001',
            message = pg_catalog.format(
                'custody revision is %s; reload and plan from the stored revision',
                coalesce(current_position.custody_version, 0)
            );
    end if;

    recorded_value := pg_catalog.clock_timestamp();
    insert into public.custody_event (
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
        insert into public.custody_position (
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
        update public.custody_position
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

    payload_value := pg_catalog.jsonb_build_object(
        'custodian_id', custodian_value,
        'from_location', current_position.location_code,
        'occurred_at_utc', occurred_value,
        'specimen_id', specimen_value,
        'to_location', destination_value,
        'transfer_id', transfer_value,
        'version', expected_version_value + 1
    );
    payload_digest_value := pg_catalog.encode(
        public.digest(
            pg_catalog.convert_to(payload_value::text, 'UTF8'),
            'sha256'
        ),
        'hex'
    );
    insert into public.transactional_outbox (
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
$custody_transfer$;

alter function public.record_custody_transfer(
    text, text, text, bigint, text, timestamptz
) owner to laboratory_owner;
alter function public.record_custody_transfer(
    text, text, text, bigint, text, timestamptz
) set search_path to pg_catalog, pg_temp;
revoke all on function public.record_custody_transfer(
    text, text, text, bigint, text, timestamptz
) from public;
grant execute on function public.record_custody_transfer(
    text, text, text, bigint, text, timestamptz
) to laboratory_app;
