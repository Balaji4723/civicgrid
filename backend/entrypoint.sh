#!/bin/sh
# Container start-up. Every step is idempotent; any failure stops the container (fail closed).
set -e
alembic upgrade head                 # schema, incl. CREATE EXTENSION postgis
python -m app.seed --if-empty        # seeds the 3 load scenarios + demo geodata ONLY on an empty database
python -m app.geo load-wards         # upsert ward polygons from WARD_BOUNDARY_SOURCE (refuses invalid/overlapping data)
python -m app.geo route-backfill     # routes pre-PostGIS sanitation reports that have a location but no decision
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
