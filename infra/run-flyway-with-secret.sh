#!/bin/sh
set -eu

FLYWAY_PASSWORD="$(tr -d '\r\n' < /run/secrets/postgres_migrator_password)"
export FLYWAY_PASSWORD

exec flyway \
    -workingDirectory=/flyway/project \
    -configFiles=/flyway/project/flyway.conf \
    "$@"
