-- TARGET: PostgreSQL holds tenant-scoped canonical state and append-only evidence.
-- TARGET: optimistic revisions serialize lifecycle and custody writers.

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
    delivery_attempts integer not null default 0 check (delivery_attempts >= 0),
    available_at_utc timestamptz not null default now(),
    delivered_at_utc timestamptz,
    primary key (tenant_id, message_id)
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
    receipt_id text primary key,
    claim_id text not null,
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
    check (performer_id <> reviewer_id)
);

create table acceptance_decision (
    decision_id text primary key,
    domain text not null check (domain in ('scientific', 'quality', 'regulatory')),
    approver_id text not null,
    accountable_role text not null,
    intended_use_id text not null,
    decision text not null check (
        decision in ('approve', 'approve_with_conditions', 'return_for_evidence')
    ),
    receipt_ids jsonb not null,
    residual_risk text not null,
    decided_at_utc timestamptz not null
);

create index specimen_event_command_lookup
    on specimen_event (tenant_id, command_id);
create index outbox_delivery_queue
    on transactional_outbox (available_at_utc)
    where delivered_at_utc is null;
create index instrument_quarantine_queue
    on instrument_inbox (tenant_id, recorded_at_utc)
    where disposition = 'quarantined';

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
alter table migration_checkpoint enable row level security;

alter table tenant force row level security;
alter table specimen force row level security;
alter table specimen_event force row level security;
alter table idempotency_ledger force row level security;
alter table custody_position force row level security;
alter table instrument_inbox force row level security;
alter table transactional_outbox force row level security;
alter table vendor_projection force row level security;
alter table migration_checkpoint force row level security;

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
create policy migration_checkpoint_tenant_policy on migration_checkpoint
    using (tenant_id = current_setting('app.tenant_id', true))
    with check (tenant_id = current_setting('app.tenant_id', true));
