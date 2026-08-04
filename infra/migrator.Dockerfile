FROM postgres:17.10-alpine

RUN apk add --no-cache python3

WORKDIR /workspace
COPY database ./database
COPY sql ./sql
COPY scripts/apply_database_migrations.py ./scripts/apply_database_migrations.py
COPY infra/postgres-init/010_application_password.sh ./infra/postgres-init/010_application_password.sh

ENTRYPOINT ["/bin/sh", "-eu", "-c"]
CMD ["export PGPASSWORD=\"$(cat /run/secrets/postgres_password)\"; python3 scripts/apply_database_migrations.py --dsn \"host=$PGHOST dbname=$POSTGRES_DB user=$POSTGRES_USER\"; infra/postgres-init/010_application_password.sh"]
