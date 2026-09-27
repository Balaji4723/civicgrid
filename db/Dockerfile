# PostgreSQL 16 + PostGIS, built from the official postgres image so it works on BOTH Intel/AMD (amd64)
# and Apple Silicon (arm64): the PGDG apt repository that the official image already uses ships
# postgresql-16-postgis-3 for both architectures.
# Same major version (16) as the Phase-0 image, so an existing `pgdata` volume keeps working.
# The extension itself is created by the Alembic migration (CREATE EXTENSION IF NOT EXISTS postgis),
# which also works on an existing volume - /docker-entrypoint-initdb.d would only run on a brand-new one.
FROM postgres:16
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-postgis-3 \
 && rm -rf /var/lib/apt/lists/*
