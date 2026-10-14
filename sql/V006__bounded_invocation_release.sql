-- TARGET: ordinary callers release only their currently owned pre-effect reservation.

create function public.release_bounded_call_invocation(
    tenant_value text,
    call_value text,
    invocation_digest_value text,
    lease_value uuid,
    fence_value bigint
)
returns table (released_call_id text)
language sql
security definer
set search_path = pg_catalog, pg_temp
as $$
    delete from public.bounded_call_invocation as invocation
     where invocation.tenant_id = tenant_value
       and invocation.tenant_id = laboratory_security.authorized_tenant_id()
       and invocation.call_id = call_value
       and invocation.invocation_sha256 = invocation_digest_value
       and invocation.state = 'in_progress'
       and invocation.lease_expires_at_utc > pg_catalog.clock_timestamp()
       and invocation.lease_token = lease_value
       and invocation.fencing_token = fence_value
    returning invocation.call_id;
$$;

alter function public.release_bounded_call_invocation(text, text, text, uuid, bigint)
    owner to laboratory_owner;
revoke all on function public.release_bounded_call_invocation(
    text, text, text, uuid, bigint
) from public;
grant execute on function public.release_bounded_call_invocation(
    text, text, text, uuid, bigint
) to laboratory_app;
