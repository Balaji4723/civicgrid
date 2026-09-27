#!/usr/bin/env bash
# Restore the pristine 3-scenario seed (also un-corrupts the chain). Run between takes.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec backend python -m app.seed --reset
