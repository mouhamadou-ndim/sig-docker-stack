#!/bin/bash
# Exécuté une seule fois, à la création du volume de données.
# Crée les rôles applicatifs selon le principe du moindre privilège.
set -e

if [ -z "$ETL_DB_PASSWORD" ] || [ -z "$GEOSERVER_DB_PASSWORD" ]; then
    echo "ETL_DB_PASSWORD et GEOSERVER_DB_PASSWORD doivent être définis" >&2
    exit 1
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v db="$POSTGRES_DB" \
    -v etl_password="$ETL_DB_PASSWORD" \
    -v gs_password="$GEOSERVER_DB_PASSWORD" <<'EOSQL'
CREATE ROLE etl_writer   LOGIN PASSWORD :'etl_password';
CREATE ROLE geoserver_ro LOGIN PASSWORD :'gs_password';

REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO etl_writer, geoserver_ro;
EOSQL
