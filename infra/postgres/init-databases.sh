#!/bin/bash
# Creates the second database (`new_api`) alongside the primary `shakib_core`
# database (which the postgres image creates from POSTGRES_DB).
# Runs once, on first initialisation of the data volume.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE new_api;
EOSQL

echo "Databases ready: shakib_core (primary), new_api"
