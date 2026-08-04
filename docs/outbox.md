# Cross-service events

Custody changes and their outbox rows commit in the same PostgreSQL transaction.
The outbox carries only producer facts: tenant, event identity, topic, aggregate
identity and revision, JSON payload, payload digest, canonicalization profile,
and database timestamp. The application receives tenant-scoped insert and read
privileges. It receives no update or delete privileges.

Debezium owns change capture, routing, offsets, retry interaction with Kafka,
and connector recovery. The checked-in Event Router fragment maps the existing
column names to Debezium's Outbox Event Router. A deployment supplies the
PostgreSQL connector, logical replication, Kafka, credentials, TLS, topic
policy, schema history, and monitoring through its platform configuration. The
connector uses the read-only `laboratory_outbox_worker` identity, whose outbox
policy spans tenants solely for committed event capture; hosting grants the
connector's required replication attributes.

Consumers deduplicate on `message_id`. `aggregate_id` supplies the Kafka key,
and `topic` supplies the destination. Tenant, aggregate revision, payload
digest, and canonicalization profile travel as headers. The connector captures
inserts from `public.transactional_outbox` only.

Reference: [Debezium Outbox Event Router](https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html).
