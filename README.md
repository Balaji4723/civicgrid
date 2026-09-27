# CivicGrid — SWM Civic Compliance & Verification (demo prototype)

Team Vision-X · SIH 2026 · SIH26195 · Theme: Clean & Green Technology · Category: Software

A demo-grade prototype with **three genuinely working subsystems** — the three mechanisms pitched in the deck:

| # | Mechanism | Where it lives |
|---|-----------|----------------|
| 1 | **Cross-Check Engine** – a mismatch is *flagged for review only*; nothing is attributed until a second, independent signal agrees | `backend/app/crosscheck.py`, triggered from `services.create_receiving_record` |
| 2 | **Discrepancy Resolution workflow** – `FLAGGED → EVIDENCE_PENDING → CORROBORATED → INVESTIGATING → RESOLVED → CLOSED`, invalid transitions rejected | `backend/app/resolution.py`, `routers/discrepancy.py` |
| 3 | **Tamper-evident audit trail** – per-load SHA-256 hash chain + `verify-integrity` | `backend/app/hashchain.py`, `routers/loads.py`, `routers/admin.py` |

Everything else (citizen screens, municipal lists/KPIs, civic credits) is real UI on **seeded, static data**.

---

## Run it

```bash
# 1. Postgres+PostGIS and the API.  The db image is built locally (postgres:16 + PostGIS, Intel and Apple Silicon).
docker compose build            # first time / after changing db/ or backend/
docker compose up               # entrypoint: migrate -> seed (first boot only) -> load wards -> route legacy reports -> serve

# 2. Frontend (new terminal)
cd frontend
cp .env.local.example .env.local
npm install
npm run dev                     # http://localhost:3000
```

API docs: http://localhost:8000/docs (Swagger — use *Authorize* with a token from `POST /auth/login`).

> **Upgrading an existing Phase-0 Docker volume?** The migration and `load-wards` run automatically and your data is kept,
> but the old volume has no household coordinates or demo tickets. For the full demo run `./demo/reset.sh` once
> (this **erases** demo data and re-seeds). To keep the data and just route old reports: nothing to do, `route-backfill` runs on start.

**Demo accounts** (password for all: `demo123`; the login page has one-click buttons):

| Username | Role | Portal |
|---|---|---|
| `worker2` (also `worker1`, `worker3`) | WORKER | `/worker` |
| `facility1` | FACILITY | `/authority` |
| `admin1` | MUNICIPAL_ADMIN | `/municipal` (and `/authority`) |
| `citizen1` | CITIZEN | `/citizen` |

**Reset between takes** (restores pristine seed, un-corrupts the chain, event IDs are deterministic again):

```bash
./demo/reset.sh        # = docker compose exec backend python -m app.seed --reset
```

**Tests** (182 as of Phase 2: 13 Phase-0 + 57 geo + 7 migration + 53 evidence + 21 independence + 31 audit-selection; real PostgreSQL **with PostGIS**). Against the compose database:

```bash
docker compose up -d db
docker compose exec db psql -U civicgrid -d civicgrid -c "CREATE DATABASE civicgrid_test"
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
DATABASE_URL=postgresql+psycopg2://civicgrid:civicgrid@localhost:5432/civicgrid_test python -m pytest -q
```

The migration tests create and drop their own scratch databases, so the DB role needs `CREATEDB` (the compose `civicgrid` role is a superuser).

---

## Seeded scenarios (exactly three)

| Load | Story | Seeded state |
|---|---|---|
| `DL-1001` | **Clean load.** Worker declared 480 kg, facility weighed 468 kg (within 10%), acceptable | Cross-check = `MATCH`, **no discrepancy** |
| `DL-1002` | **Main demo path.** Worker declared 520 kg, facility weighed 390 kg (−25%) | Discrepancy #1 `QUANTITY`, seeded at **`FLAGGED`** so it can be walked live |
| `DL-1003` | **Receiving-side rejection.** Worker declared 6/6 homes segregated, facility marks it *unacceptable* | Discrepancy #2 `STREAM`, seeded at **`INVESTIGATING`** |

All seeded events go through the same service code as the live API, so every seeded chain is genuinely hash-linked and verifies as valid.

---

## Phase 1 — PostGIS, wards, GPS ward routing, sanitation map

Status legend used below: **IMPLEMENTED** (works, tested) · **CONFIGURABLE** (behaviour set by config/data, not code) ·
**DEMO/SYNTHETIC** (fake data, labelled as such) · **NOT IMPLEMENTED** · **PRODUCTION DEPENDENCY** (needs something outside this repo).

### What it does

```
citizen report (issue + GPS) → validate → PostGIS point → point-in-polygon vs ward boundaries → ward → authority queue
        → routing decision stored → hash-chained audit event (chain SR-<id>) → ticket on the municipal map / queue
```

| Capability | Status | Notes |
|---|---|---|
| PostGIS in Docker (`postgres:16` + `postgresql-16-postgis-3`, amd64 + arm64) | IMPLEMENTED | `db/Dockerfile`. **Docker build itself: PENDING validation on your machine** (see below) |
| Spatial columns: `geography(POINT)` on households, facilities, sanitation reports; `geometry(MULTIPOLYGON)` wards; `geometry(LINESTRING)` route paths; GiST indexes on all five; GeoAlchemy2 | IMPLEMENTED | migration `0002`; tests assert types, SRID 4326, GiST, and that the planner can use each index |
| Safe migration + backfill of old `latitude`/`longitude` → geography, fully reversible | IMPLEMENTED | Aborts (touching nothing) if any legacy row has half a pair or an out-of-range value. Downgrade restores the floats |
| Ward boundary source is configurable (`WARD_BOUNDARY_SOURCE` → GeoJSON path) | CONFIGURABLE | Loader validates geometry, WGS84 range, overlap, queue + source metadata; refuses bad input |
| Wards "Demo Ward A/B/C" | **DEMO/SYNTHETIC** | Hand-drawn polygons, labelled **DEMO DATA — NOT OFFICIAL MUNICIPAL BOUNDARIES** in the DB, API, map and routing events. `is_official` is `false` |
| Point-in-polygon ward lookup; ambiguity (shared edge/overlap) and outside-all-wards → *manual triage*, never guessed | IMPLEMENTED | `ST_Covers` on the stored point |
| Authority queue per ward; routing decision stored per attempt; reroute (manual override with reason, or retry) | IMPLEMENTED | Queues are synthetic ("Demo Ward B Sanitation Team") |
| Ticket lifecycle `ROUTED → IN_PROGRESS → RESOLVED` by the municipal admin | IMPLEMENTED | |
| Every routing / status change written with the existing `append_chain_event` | IMPLEMENTED | Same table + SHA-256 chain as loads; per-ticket *Verify audit trail* in the UI |
| Offline sanitation map (Leaflet, ward polygons + report points + facilities, **no tile server**) | IMPLEMENTED | Component-level render verified in jsdom; **real-browser check: PENDING** |
| Device GPS label "Location reported by device — not independently verified." | IMPLEMENTED | A pin dropped/typed by the citizen is labelled differently ("placed by the citizen on a map") — it is not device GPS |
| Spatial APIs: nearby reports, nearby households, household clusters (`ST_ClusterDBSCAN`), nearest facility, route geometry/length, area query | IMPLEMENTED | Household endpoints are admin-only and return ids + coordinates only |
| Worker/vehicle live location | NOT IMPLEMENTED | Out of Phase 1 scope |
| Photo attached to a **sanitation report** | PARTIALLY | Only the (sanitised) file *name* is stored. Real upload exists for discrepancy/audit evidence (Phase 2) but is not yet wired to citizen reports |
| Real ward boundaries / real authority routing | PRODUCTION DEPENDENCY | Needs the municipality's own boundary file (GeoJSON, WGS84) and real team/queue mapping. No government integration exists |
| GPS accuracy / spoofing | PRODUCTION DEPENDENCY | Coordinates come from the browser or the citizen; nothing verifies them |

### Docker: exact build and validation steps (status: PENDING — Docker is not available where this was built)

```bash
docker compose build --no-cache db backend
docker compose up -d
docker compose logs backend | tail -20             # expect: alembic upgrade, "Seeded...", "Wards: ...", "Uvicorn running"
docker compose exec db psql -U civicgrid -d civicgrid -c "select postgis_full_version();"
docker compose exec db psql -U civicgrid -d civicgrid -c "\d wards"          # boundary geometry(MultiPolygon,4326) + idx_wards_boundary gist
docker compose exec backend alembic current                                   # 0002 (head)
docker compose exec backend alembic check                                     # No new upgrade operations detected.
curl -s localhost:8000/health
docker compose exec backend python -m app.geo status                          # source label must say DEMO DATA — NOT OFFICIAL ...
```

If `postgresql-16-postgis-3` cannot be installed on your platform, the fallback is `image: postgis/postgis:16-3.4` in
`docker-compose.yml` (drop the `build:` line); on Apple Silicon this needs a build that publishes arm64 — check before relying on it.

### Using your own ward boundaries (CONFIGURABLE)

```bash
WARD_BOUNDARY_SOURCE=/data/my_wards.geojson docker compose up      # or: python -m app.geo load-wards --file my_wards.geojson
```

File format: GeoJSON `FeatureCollection` in WGS84 (lng,lat), Polygon/MultiPolygon features with `properties.code`, `name`,
`queue{code,name}`, and a top-level `civicgrid_source{name,version,label,is_official}` block. See `backend/app/data/demo_wards.geojson`.
Wards are upserted by `code` (ids stay stable). `is_official` is whatever the file says — **the software cannot verify it**.
The loader refuses invalid, overlapping or out-of-range polygons and, in Docker, that stops the container starting.

### New API endpoints (Phase 1)

| Endpoint | Who | Purpose |
|---|---|---|
| `GET /geo/wards` | any user | Ward polygons (GeoJSON) + boundary source label |
| `GET /geo/ward-lookup?lat&lng` | any user | Point-in-polygon preview: which ward/queue would this route to |
| `GET /geo/reports`, `GET /geo/reports/nearby?lat&lng&radius_m` | admin | Reports as GeoJSON; reports within N metres |
| `GET /geo/households/nearby`, `GET /geo/households/clusters` | admin | Located households (ids only); DBSCAN clusters (eps in metres) |
| `GET /geo/facilities`, `GET /geo/facilities/nearest` | facility, admin | Facility points; nearest by metres, optional `kind` |
| `GET /geo/routes/{id}` | facility, admin | Route path, length (m), stops, wards crossed |
| `POST /geo/area/query` | admin | Households / reports / facilities / routes / wards inside a GeoJSON polygon |
| `POST /citizen/sanitation-reports` (extended) | citizen | `issue_type`, `latitude`, `longitude`, `accuracy_m`, `location_source`; GPS-routes and returns the decision |
| `GET /citizen/sanitation-reports` | citizen | Own reports only |
| `GET /sanitation/queues`, `GET /sanitation/tickets[?status&ward_id&queue_id]`, `GET /sanitation/tickets/{id}` | admin | Queue counts, ticket list, detail + routing history |
| `POST /sanitation/tickets/{id}/status` | admin | `IN_PROGRESS` then `RESOLVED` (note required) |
| `POST /sanitation/tickets/{id}/reroute` | admin | `ward_id` = manual override; omitted = retry point-in-polygon; reason required |
| `GET /sanitation/tickets/{id}/events`, `.../verify-integrity` | admin (verify also: report owner) | The ticket's hash chain |

### PostGIS queries used

`ST_Covers(ward.boundary, point)` (point-in-ward) · `ST_DWithin` + `ST_Distance` on `geography` (metres) · `ST_ClusterDBSCAN` over a UTM projection ·
`ST_MakeLine` (route path) · `ST_Length(geography)` · `ST_Intersects` (route ↔ ward, area query) · `ST_Covers(area, point)` · `ST_IsValid` · `ST_AsGeoJSON`.

### Phase 1 demo: sanitation ticket end to end (≈2 min)

1. Sign in as **Citizen**. In *Report a sanitation issue* choose an issue, tap the map inside a ward. The panel says
   *"Would be routed to Demo Ward B — Demo Ward B Sanitation Team"* (a live point-in-polygon query) and shows the location label.
2. Submit. The result names the ward, queue, method and the audit event number.
3. Tap far outside the ward outlines and submit again → *manual triage* (nothing is guessed).
4. Sign out → **Municipal admin** → *Sanitation Map*. The new tickets are on the map (colour = status). Click one:
   routing decision, location label, **Start work → Mark resolved**. For the manual-triage ticket use *Assign manually* with a reason.
5. **Verify audit trail** on any ticket → the `SR-<id>` chain, same mechanism as the Digital Load chains.

### Known limitations (Phase 1)

- No real-browser verification yet (no browser in the build environment): the map component was rendered in jsdom with live API data; layout/appearance need your eyes.
- Ward polygons and queues are synthetic; the default polygons lie over an arbitrary area so device GPS from your real location will land *outside* them (→ manual triage). Use the map pin, or configure your own boundaries.
- The immutable chain stores coordinates (rounded to 6 dp) and a SHA-256 of free text, not the text itself. Coordinates in a hash chain cannot be erased — decide the retention policy before real use.
- Route paths connect households in id order (a demo simplification), not real roads.
- Area/cluster queries use planar geometry for ward tests and geodesic distance for radius queries; differences are metres at city scale.

## Phase 2 — Evidence capture, audit selection, Audit Center, independence

Legend as in Phase 1: **IMPLEMENTED** · **CONFIGURABLE** · **DEMO/SYNTHETIC** · **NOT IMPLEMENTED** · **PRODUCTION DEPENDENCY** · **NOT TESTED**.

> **Principle: AI can flag. Independent evidence corroborates.** The Cross-Check Engine and the discrepancy state machine
> are unchanged; Phase 2 only changes *what* may be submitted as the second signal.

### Evidence architecture

```
upload (multipart) -> sanitise name -> identify type from the FILE'S BYTES -> name + Content-Type must agree -> stream to temp
 (byte cap by type, SHA-256 of the real bytes) -> images fully decoded (Pillow) -> duplicate check on hash
 -> EvidenceStorage.put(server-generated key) -> DB row (metadata) -> hash-chained EVIDENCE_ADDED event carrying the file hash
```

| Item | Status | Detail |
|---|---|---|
| Real multipart upload; API returns an opaque `ev_...` id, **never** a path or storage key | IMPLEMENTED | `POST /discrepancy/{id}/evidence`, `POST /audit-center/audits/{id}/evidence` |
| Types: JPEG, PNG, WebP (images); MP4, MOV, WebM (video) | IMPLEMENTED | Identified by magic bytes. Everything else (PDF, SVG, HTML, zip, executables, scripts) is refused with a reason |
| Extension / declared Content-Type must match the content; double extensions (`x.php.jpg`) refused | IMPLEMENTED | 415 with a specific error code |
| Size caps: images 10 MB, video 50 MB; pixel cap 40 M (decompression-bomb guard) | CONFIGURABLE | `EVIDENCE_MAX_IMAGE_BYTES`, `EVIDENCE_MAX_VIDEO_BYTES`, `EVIDENCE_MAX_IMAGE_PIXELS` |
| Video validation | PARTIALLY | Container signature only. Not transcoded, not scanned, not decoded: a crafted file with a valid MP4 header is accepted |
| Malware / antivirus scanning | NOT IMPLEMENTED | PRODUCTION DEPENDENCY (e.g. ClamAV in the upload path) |
| SHA-256 of the actual bytes, stored in the DB **and** written into the immutable `EVIDENCE_ADDED` event | IMPLEMENTED | `GET /evidence/{id}/verify` checks file = DB = chain; downloads are refused (`EVIDENCE_TAMPERED`) if the bytes changed |
| Metadata: uploader identity + role, timestamp, load, discrepancy/audit, category, description, side | IMPLEMENTED | Table `evidence` |
| Kinds `FILE_EVIDENCE` / `AUDIT_RESULT` / `NOTE` — a **note is never equivalent to a file** | IMPLEMENTED | DB constraint: a FILE has a stored key + hash, nothing else may |
| Side: `WORKER` / `FACILITY` / `NEUTRAL` (the uploader's classification, limited by their role; not a finding of fault) | IMPLEMENTED | A worker can only choose WORKER; a user of the receiving facility only FACILITY |
| GPS: optional, stored as PostGIS point, **always `verified=false`** (DB constraint) and labelled "UNVERIFIED" | IMPLEMENTED | EXIF metadata is neither read nor stripped; files are stored byte-for-byte |
| Duplicates: same file, same user, same load → 409. Same bytes from someone else → kept but flagged `duplicate_of`, **not independent** | IMPLEMENTED | |
| Viewing/downloading is authorised per item: admin all; uploader; facility users of the receiving facility; an auditor of that load; workers only their own | IMPLEMENTED | Citizens: none |
| **No delete or update** API (405) | IMPLEMENTED | Retention/erasure is a policy decision, not a button: see limitations |
| Storage abstraction `EvidenceStorage` (local disk backend; S3/Azure/GCS/municipal object store = implement 4 methods) | IMPLEMENTED (local) | A test runs the whole workflow on an in-memory backend. Cloud backends: NOT IMPLEMENTED |
| Files at rest | PARTIALLY | Mode 0640, atomic write, write-once keys. No encryption at rest, no backup: PRODUCTION DEPENDENCY |
| `REQUIRE_FILE_EVIDENCE` | CONFIGURABLE | **true (Docker/demo default):** FLAGGED→EVIDENCE_PENDING needs an uploaded file; corroboration needs a completed independent audit; note-only and typed-number paths are refused. **false (legacy tests, DL-1003 seed):** those paths work, are stored as `NOTE` / `LEGACY_MANUAL_ENTRY`, and are shown as **NOT EVIDENCE-BACKED** everywhere |

### Independence rules (enforced on the server, from the data, not from role names)

A party is one of: the **responsible worker** (any account linked to that worker), the **recorder** (user who recorded the facility receiving record —
new column `receiving_records.recorded_by_user_id`), the **receiving facility** (any user of that facility).

| Rule | Where enforced |
|---|---|
| Workers cannot use the Audit Center or conduct audits | role check + `ROLE_WORKER` |
| An account linked to the responsible worker cannot audit that worker's load, whatever its role | `RESPONSIBLE_WORKER` — tested with an admin-role account linked to the worker |
| The user who recorded the facility signal cannot audit it | `RECORDED_FACILITY_SIGNAL` |
| Nobody from the receiving facility may audit that load (a different user of the same facility is still not independent) | `SAME_FACILITY_ORGANISATION` — such users do not even see the audit (recusal) |
| Independence is checked when an audit is **started, given evidence, completed, and again when submitted for corroboration** | `audits.py`, `resolution.corroborate_with_audit` |
| Worker or facility evidence can never, alone, corroborate: only a **completed audit** can (evidence alone → `AUDIT_REQUIRED`) | `discrepancy` router |
| An audit's file evidence that duplicates someone else's file does not count | `REJECTED_NO_EVIDENCE` |

Corroboration outcomes (a rejection is recorded as a row **and** a hash-chained `CORROBORATION_REJECTED` event, and attributes nothing):
audit supports facility → **ACCEPTED** (→ CORROBORATED) · supports worker → `REJECTED_SUPPORTS_WORKER` · disagrees with both → `REJECTED_INCONCLUSIVE` ·
auditor not independent → `REJECTED_NOT_INDEPENDENT` · no independent file → `REJECTED_NO_EVIDENCE`. Attribution (`attributed_to`) is still possible **only** at RESOLVE.

**What "independent" cannot mean here (limitation):** the model sees accounts, workers and facilities. It cannot see relatives, shared management, or a
municipal admin who supervises both sides. `admin1` is treated as independent unless they recorded the receiving record. Demo has one user per facility
(`facility1` at facility 1, `facility2` at facility 2); real deployments need a conflict-of-interest register (PRODUCTION DEPENDENCY).
Audit results are typed in by a person: the software cannot know the auditor weighed honestly.

### Audit selection (nothing is selected without a stored reason)

Every audit stores `method` (RANDOM / RISK_BASED / MANUAL), `selection_reason` (DB constraint: ≥10 chars), `risk_score`+factors where applicable, `selected_at`,
`selected_by` (a user, or the engine), the selection **run** (config snapshot, seed, every candidate incl. non-selected), and an `AUDIT_SELECTED` event on the load's chain.
One open audit per load (partial unique index). **Eligible** = received load (VERIFIED/DISPUTED), no open audit, not audited to completion within `cooldown_days` (automatic methods only).

| Method | Algorithm |
|---|---|
| **RANDOM** (CONFIGURABLE: `random_sample_pct`, default 20) | `k = max(1, round-half-up(pct% × N))`, drawn without replacement with `random.Random(seed)`. The seed is stored, so a draw can be replayed. Uniform: ignores risk. No claim of statistical optimality |
| **RISK_BASED** (CONFIGURABLE: weights, caps, `risk_threshold` 0.30, `risk_max_selected` 5, `lookback_days` 90) | `score = Σ weightᵢ/Σweights × min(rawᵢ/capᵢ, 1)` ∈ [0,1]; select score ≥ threshold, highest first. Each factor stores raw value, cap, weight, contribution and a plain-English explanation |
| **MANUAL** | Admin picks a load and must give a reason (recorded; only its hash goes into the chain). Ignores cooldown. Risk score stored for information only |

Risk factors (default weights): quantity variance 0.40 · stream mismatch 0.20 · worker's prior corroborated discrepancies 0.20 (only those still open or resolved as *worker-attributable*; process/facility findings do **not** count) ·
adverse audit history 0.10 · repeat missed-collection complaints in the ward 0.05 (area-level, weak proxy) · segregation-pattern deviation 0.05 (needs ≥2 other loads).
Weights/caps come from `AUDIT_CONFIG_PATH` (JSON) or per-run overrides; **the weights are policy choices, not validated statistics.** A deterministic ranking can be gamed: use RANDOM as well.
"Preview" runs the engine without saving anything.

### Audit Center and API

UI: `/audits` (KPIs; risk-based / random / manual selection with preview; table with method, risk, reason, worker→facility, discrepancy status, auditor, evidence status) and `/audits/{id}`
(why selected + risk table, load inspection, "can you conduct this?", evidence upload, result form, cancel). Discrepancy page: **Workflow** and **Evidence & independence** tabs.
Worker portal: **Evidence requests**.

| Endpoint | Who |
|---|---|
| `GET /config/evidence` | any user |
| `POST /discrepancy/{id}/evidence` (multipart), `GET /discrepancy/{id}/evidence` | worker (own load) / facility (own facility) / admin; list: facility, admin |
| `GET /evidence/{id}`, `/content`, `/verify` (no PUT/PATCH/DELETE) | per-item authorisation |
| `GET /audit-center/config`, `/summary`, `/audits[?status&method]`, `/audits/{id}`, `/audits/{id}/evidence` | facility (recused from own facility's loads), admin |
| `POST /audit-center/selection-runs` (`RANDOM`/`RISK_BASED`, `dry_run`, `seed`, overrides), `GET /audit-center/selection-runs`, `POST /audit-center/audits` (manual), `POST /audit-center/audits/{id}/cancel` | admin |
| `POST /audit-center/audits/{id}/start`, `/evidence`, `/complete` | independent facility user or admin |
| `POST /discrepancy/{id}/corroborate` `{"audit_id": n}` | facility, admin (legacy typed fields only if `REQUIRE_FILE_EVIDENCE=false`) |
| `GET /worker/evidence-requests` | worker |

### Phase 2: exact local validation commands (status: PENDING — no Docker or browser was available where this was built)

What *was* verified without Docker: all 182 tests on PostgreSQL 16 + PostGIS 3.4; the API served by uvicorn on an Alembic-migrated database with `REQUIRE_FILE_EVIDENCE=true`
and real multipart uploads of the demo images (every command below except the `docker compose` lines was run this way); React components rendered in jsdom against live payloads.
What was **not**: the Docker images/compose (incl. the new `evidence_data` volume), and anything in a real browser.

```bash
# 1. build + start
docker compose build --no-cache db backend
docker compose up -d
docker compose logs backend | tail -20                       # migrate -> seed -> "Wards: ..." -> Uvicorn running
docker compose exec backend printenv REQUIRE_FILE_EVIDENCE EVIDENCE_STORAGE_DIR    # true, /data/evidence
curl -s localhost:8000/health

# 2. database verification
docker compose exec backend alembic current                  # 0003 (head)
docker compose exec backend alembic check                    # No new upgrade operations detected.
docker compose exec db psql -U civicgrid -d civicgrid -c "\d evidence"      # constraints ck_evidence_file_iff_stored, ck_evidence_gps_never_verified
docker compose exec db psql -U civicgrid -d civicgrid -c "\d audits"        # ck_audits_reason_recorded, uq_audits_one_open_per_load (partial unique)
docker compose exec db psql -U civicgrid -d civicgrid -c "select id, name, role from users order by id"     # 7 users incl. facility2

# 3. evidence upload (real multipart) + validation
python3 demo/make_sample_evidence.py                          # synthetic demo images -> demo/assets/
tok() { curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' -d "{\"username\":\"$1\",\"password\":\"demo123\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'; }
W=$(tok worker2); A=$(tok admin1); F2=$(tok facility2)
curl -s -X POST localhost:8000/discrepancy/1/evidence -H "Authorization: Bearer $W" \
  -F "file=@demo/assets/1_worker_load_photo.png;type=image/png" -F "description=my pickup photo" | python3 -m json.tool
printf 'MZ\x90\x00\x03\x00\x00\x00fake-exe-content-----------------------------------------------------------' > /tmp/fake.png
curl -s -X POST localhost:8000/discrepancy/1/evidence -H "Authorization: Bearer $W" -F "file=@/tmp/fake.png;type=image/png" -F "description=not a photo"   # 415 UNSUPPORTED_CONTENT (a Windows executable)
cp demo/assets/4_audit2_scale_385kg.png /tmp/renamed.jpg
curl -s -X POST localhost:8000/discrepancy/1/evidence -H "Authorization: Bearer $W" -F "file=@/tmp/renamed.jpg;type=image/jpeg" -F "description=renamed"     # 415 EXTENSION_CONTENT_MISMATCH

# 4. the stored file, the database hash and the immutable chain must all agree
EV=$(docker compose exec -T db psql -U civicgrid -d civicgrid -Atc "select public_id from evidence where kind='FILE_EVIDENCE' order by id limit 1")
KEY=$(docker compose exec -T db psql -U civicgrid -d civicgrid -Atc "select storage_key from evidence where public_id='$EV'")
docker compose exec -T db psql -U civicgrid -d civicgrid -Atc "select sha256 from evidence where public_id='$EV'"
docker compose exec -T backend sha256sum "/data/evidence/$KEY"                      # same hash
curl -s localhost:8000/evidence/$EV/verify -H "Authorization: Bearer $A"            # valid: true (file = DB = audit chain)
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE localhost:8000/evidence/$EV -H "Authorization: Bearer $A"     # 405: no delete

# 5. audit workflow
curl -s -X POST localhost:8000/audit-center/selection-runs -H "Authorization: Bearer $A" -H 'Content-Type: application/json' -d '{"method":"RISK_BASED","dry_run":true}' | python3 -m json.tool | head -30
AID=$(curl -s -X POST localhost:8000/audit-center/audits -H "Authorization: Bearer $A" -H 'Content-Type: application/json' -d '{"load_id":"DL-1002","reason":"Independent audit requested for the demo"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
curl -s -X POST localhost:8000/audit-center/audits/$AID/start    -H "Authorization: Bearer $F2"      # facility2 (different facility) may audit
curl -s -X POST localhost:8000/audit-center/audits/$AID/evidence -H "Authorization: Bearer $F2" -F "file=@demo/assets/4_audit2_scale_385kg.png;type=image/png" -F "description=scale 385 kg"
curl -s -X POST localhost:8000/audit-center/audits/$AID/complete -H "Authorization: Bearer $F2" -H 'Content-Type: application/json' -d '{"quantity":385,"condition":"ACCEPTABLE","observations":"Reweighed on the independent scale."}'
curl -s -X POST localhost:8000/discrepancy/1/corroborate -H "Authorization: Bearer $A" -H 'Content-Type: application/json' -d "{\"audit_id\": $AID}"   # 409 until the discrepancy is EVIDENCE_PENDING; see the UI walkthrough

# 6. browser demo
cd frontend && cp .env.local.example .env.local && npm install && npm run dev      # http://localhost:3000  -> follow "Demo Script (a)"
./demo/reset.sh        # between takes: truncates the DB AND purges uploaded evidence files
```

### Known limitations (Phase 2)

- **Not tested here:** Docker build/run, a real browser (components were rendered in jsdom against live API payloads; the multipart upload, file picker, video playback and layout are unverified in a browser), real phone cameras/HEIC, large (≈50 MB) uploads through a proxy.
- **Body-size limit:** the server checks `Content-Length` early and caps bytes while streaming, but Starlette buffers a multipart body before the handler runs. A reverse proxy (`client_max_body_size`) must enforce the hard cap.
- **Retention:** nothing can be deleted through the API, on purpose. Erasure/retention (legal hold, GDPR-style requests) needs an explicit administrative policy and tooling: PRODUCTION DEPENDENCY. `seed --reset` purges files (demo only).
- **Audit disagrees with both on a clean load:** recorded and flagged `requires_followup`, but no discrepancy is auto-created from an audit (NOT IMPLEMENTED).
- **Legacy paths** (`REQUIRE_FILE_EVIDENCE=false`) do not check independence; they exist for backward compatibility and are refused in Docker.
- **DL-1003** stays seeded through the legacy path (evidence note + typed audit) and is displayed as *NOT EVIDENCE-BACKED*.
- A `FACILITY` user of a *different* facility is the only facility-side independent auditor; there is no multi-organisation conflict register.
- Free-text (observations, reasons, notes) is stored in the database; only SHA-256 hashes go into the immutable chain.

### Phase 2 tests

`test_evidence.py` (53): valid image/video, content-type/extension/executable/corrupt/bomb/empty refusals, size limits, malicious filenames, SHA-256 correctness, integrity tamper checks,
duplicates, authorisation, side rules, no delete/update, GPS never verified, metadata persistence, REQUIRE_FILE_EVIDENCE, storage abstraction, no orphan files.
`test_independence.py` (21): worker/self-audit/recorder/same-facility recusal, outcomes (accepted / supports worker / inconclusive / not independent / duplicate evidence), state preconditions, the full demo scenario.
`test_audit_selection.py` (31): config validation, eligibility, random sizes + seeded reproducibility, risk scoring + explanation + reproduction, each factor, manual, cancel, DB constraints, listing/recusal.
`test_migrations.py` (+1): 0003 backfill of `recorded_by_user_id` from real chain events, downgrade.

## Demo Script

Before recording: `docker compose up`, `npm run dev`, run `./demo/reset.sh`.

### (a) Walk a discrepancy from FLAGGED to CLOSED — with real evidence and an independent audit (Phase 2, ≈4 min)

Setup: `python3 demo/make_sample_evidence.py` once (creates `demo/assets/*.png`, labelled *SYNTHETIC DEMO IMAGE*), then `./demo/reset.sh`.
Docker runs with `REQUIRE_FILE_EVIDENCE=true`, so notes and typed numbers are refused. Use four browser windows/profiles or sign in and out.

1. **Worker (`worker2`)** → *Evidence requests* → **Add evidence** → upload `1_worker_load_photo.png`. It is recorded as *Supports worker*.
2. **Facility (`facility1`)** → `#1 · DL-1002` (520 kg declared vs 390 kg received, **FLAGGED**). Open the **Evidence & independence** tab: two signals, each marked *Cannot confirm itself*; the worker's photo is *Not independent*.
3. Back on **Workflow**: upload `2_facility_weighbridge_390kg.png` (optionally *Add device GPS*: shown as UNVERIFIED), then **Submit evidence & advance** → **EVIDENCE PENDING**. Try it without a file first: *"A note on its own is not evidence."*
4. **Municipal admin (`admin1`)** → **Audit Center** → *Risk-based* → **Preview** (DL-1002 scores 0.33 ≥ 0.30, others do not) → **Run selection**. Open **AU-1**: the risk table explains every factor. Show *Random sample* preview with a seed too.
5. Independence in action: sign in as `facility1` → Audit Center is **empty** (recused: it recorded DL-1002's receiving record). As `worker2` the Audit Center is refused.
6. As `admin1`: open AU-1 → **Start audit** → attach `3_audit1_scale_515kg.png` → record **515 kg**, *Acceptable* → **Submit audit result** (*supports the worker's declaration*).
7. Discrepancy #1 → *Corroborate* → **Submit for corroboration** on AU-1 → **Blocked**: *Rejected: the independent audit agrees with the worker's declaration… nothing is attributed to anyone.* Status stays EVIDENCE PENDING.
8. Audit Center → *Manual* → `DL-1002`, reason *"Second audit by an auditor from a different facility"* → **AU-2**. Sign in as **`facility2`** (a different facility) → AU-2 → **Start** → attach `4_audit2_scale_385kg.png` → **385 kg** → submit.
9. As `admin1` or `facility2`: discrepancy #1 → **Submit for corroboration** on AU-2 → **CORROBORATED** (*Independent audit agrees with the facility record*).
10. **Start investigation → Record resolution** (*Attributed to* appears only now) **→ Close** → **CLOSED**.
11. Evidence tab: 4 files + 2 audit results, each with uploader, time, SHA-256, GPS label, side and independence. Click **Verify file integrity**. Then **Municipal → Verify Chain** on DL-1002: 26 events, valid.

Original Phase 0 click-path (notes + typed audit numbers) still exists **only** with `REQUIRE_FILE_EVIDENCE=false`, where it is labelled *LEGACY — NOT EVIDENCE-BACKED*.

### (b) Tamper detection — corrupt an event, then Verify Chain — Municipal dashboard

1. Sign out → **Municipal admin** (or use a second browser window).
2. **Audit-trail integrity** panel → `DL-1002` is selected → click **Verify Chain** → green **"Chain intact: N events verified"** (10 on a fresh seed; 26 after the full part (a) above). Note that each row shows its **event id**.
3. In a terminal, corrupt the facility's receiving record (event id **19**, index 8):
   ```bash
   ./demo/corrupt.sh DL-1002 19
   ```
   Output shows `quantity` changed **390 → 507** (quietly hiding the shortfall) and `"hash_recomputed": false`.
   *(Equivalent: `POST /admin/loads/DL-1002/corrupt-event/19` as `admin1`.)*
4. Back in the dashboard click **Verify Chain** again → red **"Tampering detected at event index 8 (event id 19)"**. Events 0–7 stay green, event 8 turns red, later events are greyed "not checked".
5. Run `./demo/reset.sh` before the next take.

Event id 19 is the receiving record whenever the DB was freshly seeded (`--reset` restarts identities). If in doubt, read the event id shown on any row of the timeline.

---

## What is real vs. simplified

**Real (working backend logic, tested):**
- Cross-check on every receiving record; single signal → `FLAGGED` only; corroboration requires an independent source that agrees with the first signal.
- State machine with explicit endpoints, valid-transition enforcement, clear 409 errors, role checks.
- SHA-256 hash chain per load, written by *every* state-changing action (`append_event`), row-locked to avoid forked chains; `GET /loads/{id}/verify-integrity`; the demo-only corrupt endpoint.
- JWT auth with 4 roles; real Postgres schema via Alembic.
- Live end-to-end path: Worker portal (marks households → creates a Digital Load → declares weight) → Facility receiving form → Cross-Check → discrepancy. (First mark on a route with no open load creates a new load, e.g. `DL-1004`; this is runtime data, not a fourth seeded scenario.)

**Seeded / simplified:** household, worker, route and facility records; civic credits balance (static number, no earning logic); municipal KPIs/lists (read-only); citizen collection history (read from seeded collection events); audit results are typed in by an auditor (the system cannot observe the physical world); DL-1003's evidence/corroboration are legacy note/manual entries and are labelled as such; sanitation reports are GPS-routed (Phase 1) but their photo is still a file *name*; auth hardening (fixed `demo123` passwords, no rate limiting/refresh tokens).

## Assumptions and judgement calls (please review)

1. **Seed states.** The brief lists scenario 2 as "flagged → … → closed" *and* asks that it be walkable live. Both can't hold, so it is seeded at `FLAGGED`. Scenario 3 is seeded at `INVESTIGATING` so the status filter shows two different states.
2. **`compare_records` signature.** The spec gives two arguments, but "corroborated" only has meaning relative to the first mismatching signal, so it takes optional `flagged_against=` and `dimension=`. Without them it can only return `MATCH`/`FLAGGED`. A corroborating source must differ from both the worker and the first signal (`IndependenceError` otherwise).
3. **What "declaration" and "mismatch" mean.** Declaration = the worker's collection events for the load + a declared load weight (kg). `QUANTITY` mismatch: >10% difference. `STREAM` mismatch: worker's load counts as *segregated* (≥75% of homes segregated) but the facility marks it *unacceptable*. A mostly-unsegregated load rejected by a facility is consistent with the declaration and is **not** flagged.
4. **Corroboration rule.** The simulated audit must (a) itself differ from the declaration and (b) agree with the facility figure (within 10% for quantity; same condition for stream). An audit that sides with the worker, or disagrees with both, is refused with 409, the discrepancy stays `EVIDENCE_PENDING`, and a `CORROBORATION_REJECTED` event is logged. Attribution (`attributed_to`) can only be entered at *Resolve*, which is only reachable through `CORROBORATED`.
5. **Schema additions beyond the spec** (needed to make the flows work): tables `users`, `facilities`, `sanitation_reports`; columns `households.owner_name/civic_credits`, `digital_loads.declared_quantity_kg`, `collection_events.load_id` (so a collection event can be written to its load's chain), `discrepancy_events.details_json` (signal snapshots, evidence, audit, resolution). `digital_loads.id` is a string (`DL-1002`); `digital_loads.status` ∈ `COLLECTING, DECLARED, VERIFIED, DISPUTED, SETTLED`. `workers.assigned_route_id` has no FK (avoids a circular FK; `routes.worker_id` carries it). *(Superseded in Phase 1: PostGIS is now used — see below.)*
6. **Chains are per entity.** Load chains are unchanged. Since Phase 1 a sanitation ticket has its own chain (`SR-<id>`) in the *same* `event_log` table with the same hash function (`event_log.chain_id`).
7. **What the hash covers.** `sha256(json.dumps(payload, sort_keys=True) + prev_hash)` exactly as specified. Every payload carries `event_type`, `ts` and `actor`, so those are covered; `verify` also checks the `event_type` column against the hashed payload and each `prev_hash` link. The `created_at`/`load_id` columns are not covered.
8. **Not an SLA system.** "Nothing stays under investigation indefinitely" is enforced structurally (finite forward-only states, a terminal `CLOSED`); there are no timers or escalations. The dashboard only shows the discrepancy's age.

## Limits of the tamper-evidence claim (know before a judge asks)

- This is a **linked-hash log** in the spirit of Schneier & Kelsey (1998). We do **not** implement their forward-secure MAC keys, so someone with full write access to the database could recompute every later hash and produce a valid-looking chain. What it reliably catches is an edit *without* recomputation, a removed or reordered middle event, or a modified `event_type`.
- Deleting the **last** event(s) is not detectable from the chain alone. The fix (not built) is anchoring the head hash somewhere the DB admin can't rewrite — the integrity panel already displays it.
- Not a blockchain and not presented as one.

## Keep the deck and the demo consistent

Things on the slides that this prototype does **not** do yet (PostGIS, GPS ward routing and the sanitation map ARE now built — see Phase 1), so don't drive or claim them on camera: computer-vision waste classification (slide 3/6); automatic Civic Credit earning and the worker Reliability Score; (random/risk-based audit selection and real evidence upload ARE now built — see Phase 2); the "disposal exception → alternative destination" workflow (scenario 3 shows the *discrepancy* flow for a rejection, not re-routing the load).
