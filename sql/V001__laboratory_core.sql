-- TARGET: PostgreSQL holds tenant-scoped canonical state and append-only evidence.
-- TARGET: optimistic revisions serialize lifecycle and custody writers.

revoke create on schema public from public;
grant usage on schema public to laboratory_app;
grant usage on schema public to laboratory_outbox_worker;
grant usage on schema public to laboratory_evidence_writer;
grant usage on schema public to laboratory_migrator;

create table tenant (
    tenant_id text primary key,
    display_name text not null,
    created_at_utc timestamptz not null default now()
);

create table specimen (
    tenant_id text not null references tenant(tenant_id),
    specimen_id text not null,
    lifecycle_state text not null check (
        lifecycle_state in (
            'registered', 'accessioned', 'in_process', 'under_review',
            'released', 'corrected', 'voided'
        )
    ),
    aggregate_version bigint not null check (aggregate_version >= 1),
    canonical_document jsonb not null,
    canonical_sha256 text not null check (canonical_sha256 ~ '^[a-f0-9]{64}$'),
    updated_at_utc timestamptz not null,
    primary key (tenant_id, specimen_id)
);

create table specimen_event (
    tenant_id text not null,
    specimen_id text not null,
    aggregate_version bigint not null,
    event_id uuid not null,
    command_id text not null,
    command_sha256 text not null check (command_sha256 ~ '^[a-f0-9]{64}$'),
    event_type text not null,
    actor_id text not null,
    reason_code text,
    payload jsonb not null,
    occurred_at_utc timestamptz not null,
    recorded_at_utc timestamptz not null default now(),
    primary key (tenant_id, specimen_id, aggregate_version),
    unique (tenant_id, event_id),
    unique (tenant_id, command_id),
    foreign key (tenant_id, specimen_id)
        references specimen(tenant_id, specimen_id)
);

create table idempotency_ledger (
    tenant_id text not null references tenant(tenant_id),
    idempotency_key text not null,
    content_sha256 text not null check (content_sha256 ~ '^[a-f0-9]{64}$'),
    status text not null check (status in ('reserved', 'committed', 'quarantined')),
    outcome_document jsonb,
    reserved_at_utc timestamptz not null default now(),
    committed_at_utc timestamptz,
    primary key (tenant_id, idempotency_key)
);

create table custody_position (
    tenant_id text not null,
    specimen_id text not null,
    custody_version bigint not null check (custody_version >= 1),
    location_code text not null,
    custodian_id text not null,
    occurred_at_utc timestamptz not null,
    primary key (tenant_id, specimen_id),
    foreign key (tenant_id, specimen_id)
        references specimen(tenant_id, specimen_id)
);

create table instrument_inbox (
    tenant_id text not null references tenant(tenant_id),
    message_id text not null,
    instrument_id text not null,
    specimen_id text not null,
    raw_object_key text not null,
    raw_sha256 text not null check (raw_sha256 ~ '^[a-f0-9]{64}$'),
    captured_at_utc timestamptz not null,
    disposition text not null check (
        disposition in ('accepted', 'quarantined', 'replayed')
    ),
    reason_code text,
    recovery_instruction text not null,
    recorded_at_utc timestamptz not null default now(),
    primary key (tenant_id, message_id)
);

create table transactional_outbox (
    tenant_id text not null references tenant(tenant_id),
    message_id text not null,
    topic text not null,
    aggregate_id text not null,
    aggregate_version bigint not null,
    payload jsonb not null,
    payload_sha256 text not null check (payload_sha256 ~ '^[a-f0-9]{64}$'),
    delivery_state text not null default 'ready' check (
        delivery_state in ('ready', 'leased', 'delivered', 'recovery_required')
    ),
    delivery_attempts integer not null default 0 check (delivery_attempts >= 0),
    available_at_utc timestamptz not null default now(),
    lease_owner text,
    lease_token uuid,
    fencing_token bigint not null default 0 check (fencing_token >= 0),
    lease_expires_at_utc timestamptz,
    last_error_code text,
    delivered_at_utc timestamptz,
    primary key (tenant_id, message_id),
    check (
        delivery_state <> 'leased'
        or (
            lease_owner is not null
            and lease_token is not null
            and lease_expires_at_utc is not null
            and fencing_token >= 1
        )
    ),
    check (
        delivery_state <> 'delivered'
        or delivered_at_utc is not null
    ),
    check (
        delivery_state <> 'recovery_required'
        or last_error_code is not null
    )
);

create table vendor_projection (
    tenant_id text not null references tenant(tenant_id),
    vendor_name text not null,
    external_identity text not null,
    external_revision bigint not null,
    canonical_sha256 text not null check (canonical_sha256 ~ '^[a-f0-9]{64}$'),
    request_id text not null,
    trace_id text not null,
    reconciliation_state text not null check (
        reconciliation_state in ('confirmed', 'readback_confirmed', 'pending_review')
    ),
    observed_at_utc timestamptz not null,
    primary key (tenant_id, vendor_name, external_identity),
    unique (tenant_id, vendor_name, request_id)
);

create table bounded_call_invocation (
    tenant_id text not null references tenant(tenant_id),
    call_id text not null,
    invocation_sha256 text not null check (invocation_sha256 ~ '^[a-f0-9]{64}$'),
    operation_name text not null,
    operation_version text not null,
    operation_contract_sha256 text not null check (
        operation_contract_sha256 ~ '^[a-f0-9]{64}$'
    ),
    state text not null check (
        state in ('in_progress', 'completed', 'recovery_required')
    ),
    lease_token uuid not null,
    fencing_token bigint not null check (fencing_token >= 1),
    lease_expires_at_utc timestamptz not null,
    output_document jsonb,
    result_sha256 text check (
        result_sha256 is null or result_sha256 ~ '^[a-f0-9]{64}$'
    ),
    recovery_reason text,
    reserved_at_utc timestamptz not null default now(),
    completed_at_utc timestamptz,
    primary key (tenant_id, call_id),
    check (
        state <> 'completed'
        or (
            output_document is not null
            and result_sha256 is not null
            and completed_at_utc is not null
        )
    ),
    check (
        state <> 'recovery_required'
        or recovery_reason is not null
    ),
    check (
        state <> 'in_progress'
        or (
            output_document is null
            and result_sha256 is null
            and completed_at_utc is null
            and recovery_reason is null
        )
    )
);

create table bounded_call_receipt (
    receipt_id text primary key,
    call_id text not null,
    caller_id text not null,
    actor_id text not null,
    tenant_id text not null references tenant(tenant_id),
    operation_name text not null,
    operation_version text not null,
    operation_contract_sha256 text check (
        operation_contract_sha256 is null
        or operation_contract_sha256 ~ '^[a-f0-9]{64}$'
    ),
    effect_class text not null check (
        effect_class in (
            'unclassified', 'read', 'idempotent_narrow_write',
            'approval_gated_broad_write'
        )
    ),
    resource_ids jsonb not null check (
        jsonb_typeof(resource_ids) = 'array'
        and jsonb_array_length(resource_ids) between 1 and 25
    ),
    payload_sha256 text not null check (payload_sha256 ~ '^[a-f0-9]{64}$'),
    invocation_sha256 text check (
        invocation_sha256 is null or invocation_sha256 ~ '^[a-f0-9]{64}$'
    ),
    decision text not null check (
        decision in ('authorized', 'succeeded', 'replayed', 'denied', 'failed')
    ),
    reason_code text not null,
    grant_id text,
    budget_window_id text,
    approval_id text,
    result_sha256 text check (
        result_sha256 is null or result_sha256 ~ '^[a-f0-9]{64}$'
    ),
    requested_at_utc timestamptz not null,
    recorded_at_utc timestamptz not null,
    check (
        effect_class <> 'approval_gated_broad_write'
        or decision in ('denied', 'failed')
        or approval_id is not null
    ),
    check (effect_class <> 'unclassified' or decision = 'denied'),
    check (
        decision = 'denied'
        or (
            operation_contract_sha256 is not null
            and invocation_sha256 is not null
            and grant_id is not null
            and budget_window_id is not null
        )
    ),
    check (
        decision not in ('succeeded', 'replayed')
        or result_sha256 is not null
    )
);

create table migration_checkpoint (
    rehearsal_id text not null,
    tenant_id text not null references tenant(tenant_id),
    source_identity text not null,
    source_revision bigint not null,
    semantic_sha256 text not null check (semantic_sha256 ~ '^[a-f0-9]{64}$'),
    disposition text not null check (
        disposition in ('loaded', 'replayed', 'collision', 'reconciled')
    ),
    recorded_at_utc timestamptz not null default now(),
    primary key (rehearsal_id, tenant_id, source_identity)
);

create table evidence_receipt (
    tenant_id text not null references tenant(tenant_id),
    receipt_id text not null,
    claim_id text not null,
    intended_use_id text not null,
    release_claim_id text not null,
    evidence_mode text not null check (
        evidence_mode in ('planned', 'simulated', 'observed')
    ),
    assurance_stage text not null check (
        assurance_stage in ('specified', 'verified', 'qualified', 'validated', 'accepted')
    ),
    environment_id text not null,
    version_bindings jsonb not null,
    scenario_ids jsonb not null,
    artifact_digests jsonb not null,
    performer_id text not null,
    reviewer_id text not null,
    limitations jsonb not null,
    observed_at_utc timestamptz not null,
    primary key (tenant_id, receipt_id),
    unique (tenant_id, receipt_id, intended_use_id, release_claim_id),
    check (performer_id <> reviewer_id)
);

create table acceptance_decision (
    tenant_id text not null references tenant(tenant_id),
    decision_id text not null,
    domain text not null check (domain in ('scientific', 'quality', 'regulatory')),
    approver_id text not null,
    accountable_role text not null,
    intended_use_id text not null,
    release_claim_id text not null,
    decision text not null check (
        decision in ('approve', 'approve_with_conditions', 'return_for_evidence')
    ),
    residual_risk text not null,
    decided_at_utc timestamptz not null,
    primary key (tenant_id, decision_id),
    unique (tenant_id, decision_id, intended_use_id, release_claim_id)
);

create table acceptance_decision_receipt (
    tenant_id text not null references tenant(tenant_id),
    decision_id text not null,
    receipt_id text not null,
    intended_use_id text not null,
    release_claim_id text not null,
    primary key (tenant_id, decision_id, receipt_id),
    foreign key (
        tenant_id, decision_id, intended_use_id, release_claim_id
    ) references acceptance_decision (
        tenant_id, decision_id, intended_use_id, release_claim_id
    ),
    foreign key (
        tenant_id, receipt_id, intended_use_id, release_claim_id
    ) references evidence_receipt (
        tenant_id, receipt_id, intended_use_id, release_claim_id
    )
);

create index specimen_event_command_lookup
    on specimen_event (tenant_id, command_id);
create index outbox_delivery_queue
    on transactional_outbox (available_at_utc)
    where delivered_at_utc is null;
create index instrument_quarantine_queue
    on instrument_inbox (tenant_id, recorded_at_utc)
    where disposition = 'quarantined';
create index bounded_call_expired_lease
    on bounded_call_invocation (tenant_id, lease_expires_at_utc)
    where state = 'in_progress';

-- SAFETY BOUNDARY: workload transactions carry one verified tenant identity;
-- forced row policies provide the replacement state for every tenant table.
alter table tenant enable row level security;
alter table specimen enable row level security;
alter table specimen_event enable row level security;
alter table idempotency_ledger enable row level security;
alter table custody_position enable row level security;
alter table instrument_inbox enable row level security;
alter table transactional_outbox enable row level security;
alter table vendor_projection enable row level security;
alter table bounded_call_invocation enable row level security;
alter table bounded_call_receipt enable row level security;
alter table migration_checkpoint enable row level security;
alter table evidence_receipt enable row level security;
alter table acceptance_decision enable row level security;
alter table acceptance_decision_receipt enable row level security;

alter table tenant force row level security;
alter table specimen force row level security;
alter table specimen_event force row level security;
alter table idempotency_ledger force row level security;
alter table custody_position force row level security;
alter table instrument_inbox force row level security;
alter table transactional_outbox force row level security;
alter table vendor_projection force row level security;
alter table bounded_call_invocation force row level security;
alter table bounded_call_receipt force row level security;
alter table migration_checkpoint force row level security;
alter table evidence_receipt force row level security;
alter table acceptance_decision force row level security;
alter table acceptance_decision_receipt force row level security;

create policy tenant_tenant_policy on tenant
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy specimen_tenant_policy on specimen
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy specimen_event_tenant_policy on specimen_event
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy idempotency_ledger_tenant_policy on idempotency_ledger
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy custody_tenant_policy on custody_position
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy instrument_inbox_tenant_policy on instrument_inbox
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy outbox_tenant_policy on transactional_outbox
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy vendor_projection_tenant_policy on vendor_projection
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy bounded_call_invocation_tenant_policy on bounded_call_invocation
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy bounded_call_receipt_tenant_policy on bounded_call_receipt
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy migration_checkpoint_tenant_policy on migration_checkpoint
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy evidence_receipt_tenant_policy on evidence_receipt
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy acceptance_decision_tenant_policy on acceptance_decision
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
create policy acceptance_decision_receipt_tenant_policy
on acceptance_decision_receipt
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));

create function preserve_append_only_record()
returns trigger
language plpgsql
as $$
begin
    raise exception 'evidence records are append-only';
end;
$$;

create trigger bounded_call_receipt_append_only
before update or delete on bounded_call_receipt
for each row execute function preserve_append_only_record();

create trigger evidence_receipt_append_only
before update or delete on evidence_receipt
for each row execute function preserve_append_only_record();

create trigger acceptance_decision_append_only
before update or delete on acceptance_decision
for each row execute function preserve_append_only_record();

create trigger acceptance_decision_receipt_append_only
before update or delete on acceptance_decision_receipt
for each row execute function preserve_append_only_record();

create trigger specimen_event_append_only
before update or delete on specimen_event
for each row execute function preserve_append_only_record();

revoke all on all tables in schema public from public;
revoke all on all sequences in schema public from public;

grant select, insert, update on
    tenant,
    specimen,
    idempotency_ledger,
    custody_position,
    instrument_inbox,
    transactional_outbox,
    vendor_projection,
    bounded_call_invocation
to laboratory_app;
grant select, insert on
    specimen_event,
    bounded_call_receipt
to laboratory_app;

grant select, update on transactional_outbox to laboratory_outbox_worker;
grant select, insert on bounded_call_receipt to laboratory_outbox_worker;

grant select, insert on
    evidence_receipt,
    acceptance_decision,
    acceptance_decision_receipt
to laboratory_evidence_writer;

grant select, insert, update on
    tenant,
    specimen,
    specimen_event,
    idempotency_ledger,
    custody_position,
    instrument_inbox,
    vendor_projection,
    migration_checkpoint
to laboratory_migrator;

alter table tenant owner to laboratory_owner;
alter table specimen owner to laboratory_owner;
alter table specimen_event owner to laboratory_owner;
alter table idempotency_ledger owner to laboratory_owner;
alter table custody_position owner to laboratory_owner;
alter table instrument_inbox owner to laboratory_owner;
alter table transactional_outbox owner to laboratory_owner;
alter table vendor_projection owner to laboratory_owner;
alter table bounded_call_invocation owner to laboratory_owner;
alter table bounded_call_receipt owner to laboratory_owner;
alter table migration_checkpoint owner to laboratory_owner;
alter table evidence_receipt owner to laboratory_owner;
alter table acceptance_decision owner to laboratory_owner;
alter table acceptance_decision_receipt owner to laboratory_owner;
