-- TARGET: accountable acceptance advances through one append-only decision
-- lineage for each tenant, intended use, release claim, and acceptance domain.
-- TARGET: conditional decisions remain release-pending until a later observed,
-- evidence-bound approval supersedes them.

set local lock_timeout = '30s';
set local statement_timeout = '5min';

alter table public.acceptance_decision
    add column condition_summary text,
    add column condition_owner_id text,
    add column condition_due_at_utc timestamptz,
    add column supersedes_decision_id text,
    add column expires_at_utc timestamptz;

-- Existing conditional decisions need accountable condition data. The
-- configured-environment preflight resolves those rows before this successor
-- advances, preserving their meaning instead of synthesizing condition facts.
do $migration_preflight$
begin
    if exists (
        select 1
        from public.acceptance_decision
        where decision = 'approve_with_conditions'
    ) then
        raise exception using
            errcode = '23514',
            message = 'acceptance_condition_backfill_required',
            hint = 'Reissue each conditional decision with condition, owner, due instant, and evidence-bound successor lineage.';
    end if;
end;
$migration_preflight$;

alter table public.acceptance_decision
    add constraint acceptance_decision_condition_coherent check (
        (
            decision = 'approve_with_conditions'
            and condition_summary is not null
            and btrim(condition_summary) <> ''
            and condition_owner_id is not null
            and btrim(condition_owner_id) <> ''
            and condition_due_at_utc is not null
            and isfinite(condition_due_at_utc)
            and condition_due_at_utc > decided_at_utc
        )
        or (
            decision <> 'approve_with_conditions'
            and condition_summary is null
            and condition_owner_id is null
            and condition_due_at_utc is null
        )
    ),
    add constraint acceptance_decision_expiry_coherent check (
        expires_at_utc is null
        or (
            isfinite(expires_at_utc)
            and expires_at_utc > decided_at_utc
        )
    ),
    add constraint acceptance_decision_supersession_distinct check (
        supersedes_decision_id is null
        or supersedes_decision_id <> decision_id
    ),
    add constraint acceptance_decision_domain_coordinate unique (
        tenant_id,
        decision_id,
        intended_use_id,
        release_claim_id,
        domain
    ),
    add constraint acceptance_decision_supersession_fk foreign key (
        tenant_id,
        supersedes_decision_id,
        intended_use_id,
        release_claim_id,
        domain
    ) references public.acceptance_decision (
        tenant_id,
        decision_id,
        intended_use_id,
        release_claim_id,
        domain
    );

create unique index acceptance_decision_one_direct_successor
    on public.acceptance_decision (
        tenant_id,
        intended_use_id,
        release_claim_id,
        domain,
        supersedes_decision_id
    )
    where supersedes_decision_id is not null;

create function public.enforce_acceptance_supersession_order()
returns trigger
language plpgsql
set search_path = pg_catalog, pg_temp
as $function$
declare
    prior_decided_at timestamptz;
begin
    if new.supersedes_decision_id is null then
        return new;
    end if;

    select prior.decided_at_utc
      into prior_decided_at
      from public.acceptance_decision as prior
     where prior.tenant_id = new.tenant_id
       and prior.decision_id = new.supersedes_decision_id
       and prior.intended_use_id = new.intended_use_id
       and prior.release_claim_id = new.release_claim_id
       and prior.domain = new.domain;

    if prior_decided_at is null then
        raise exception using
            errcode = '23503',
            message = 'acceptance_supersession_prior_required';
    end if;
    if prior_decided_at >= new.decided_at_utc then
        raise exception using
            errcode = '23514',
            message = 'acceptance_supersession_later_instant_required';
    end if;
    return new;
end;
$function$;

revoke all on function public.enforce_acceptance_supersession_order() from public;

create trigger acceptance_decision_supersession_order
before insert on public.acceptance_decision
for each row execute function public.enforce_acceptance_supersession_order();

alter function public.enforce_acceptance_supersession_order()
    owner to laboratory_owner;
