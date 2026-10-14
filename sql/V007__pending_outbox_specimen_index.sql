-- TARGET: each specimen counts pending delivery through its tenant and aggregate key.

set local lock_timeout = '30s';
set local statement_timeout = '5min';

grant create on schema public to laboratory_outbox_authority;
set local role laboratory_outbox_authority;
create index transactional_outbox_pending_specimen_idx
    on public.transactional_outbox (tenant_id, aggregate_id)
    where delivery_state <> 'delivered';
set local role laboratory_owner;
revoke create on schema public from laboratory_outbox_authority;
