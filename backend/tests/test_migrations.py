"""Migration-level tests: every test here builds a brand-new scratch database and drives Alembic.

These are deliberately separate from the create_all-based fixtures in conftest.py, which never touch Alembic.
"""
import os
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]


def _base_url():
    return make_url(os.environ["DATABASE_URL"])


@pytest.fixture()
def scratch_db():
    """Create an empty database, yield (url, engine), drop it afterwards."""
    base = _base_url()
    name = f"civicgrid_mig_{uuid.uuid4().hex[:10]}"
    admin = sa.create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name)
    engine = sa.create_engine(url)
    try:
        yield url, engine
    finally:
        engine.dispose()
        with admin.connect() as c:
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def alembic_cfg(url) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
    return cfg


def app_objects(engine):
    """Tables and enum types that belong to the application (excludes PostGIS' own objects)."""
    with engine.connect() as c:
        tables = {r[0] for r in c.execute(sa.text(
            "select tablename from pg_tables where schemaname='public' and tablename <> 'spatial_ref_sys'"))}
        enums = {r[0] for r in c.execute(sa.text("select typname from pg_type where typtype='e'"))}
    return tables, enums


def test_upgrade_downgrade_upgrade_cycle(scratch_db):
    url, engine = scratch_db
    cfg = alembic_cfg(url)

    command.upgrade(cfg, "head")
    tables_up, enums_up = app_objects(engine)
    assert {"digital_loads", "event_log", "discrepancy_events"} <= tables_up

    command.downgrade(cfg, "base")
    tables_down, enums_down = app_objects(engine)
    assert tables_down <= {"alembic_version"}, f"tables left behind: {tables_down}"
    assert enums_down == set(), f"enum types left behind: {enums_down}"

    command.upgrade(cfg, "head")            # this is the step that used to fail with "type already exists"
    tables_again, enums_again = app_objects(engine)
    assert tables_again == tables_up and enums_again == enums_up


# ============================================================ Phase 1 (0002) migration tests
import subprocess
import sys
from datetime import datetime, timezone

from app import geo
from app.hashchain import compute_hash, verify_chain
from sqlalchemy.orm import Session

GEO_INDEXES = {"idx_wards_boundary", "idx_households_location", "idx_facilities_location", "idx_routes_path",
               "idx_sanitation_reports_location", "idx_evidence_location"}
# (table, column) -> (view, type, srid)
GEO_COLUMNS = {
    ("wards", "boundary"): ("geometry_columns", "MULTIPOLYGON", 4326),
    ("routes", "path"): ("geometry_columns", "LINESTRING", 4326),
    ("households", "location"): ("geography_columns", "Point", 4326),
    ("facilities", "location"): ("geography_columns", "Point", 4326),
    ("sanitation_reports", "location"): ("geography_columns", "Point", 4326),
    ("evidence", "location"): ("geography_columns", "Point", 4326),
}


def test_schema_after_upgrade(scratch_db):
    """Clean DB -> alembic upgrade head -> verify the schema PostGIS actually holds, then alembic check (no drift)."""
    url, engine = scratch_db
    cfg = alembic_cfg(url)
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert c.execute(sa.text("select count(*) from pg_extension where extname='postgis'")).scalar() == 1
        for (table, col), (view, gtype, srid) in GEO_COLUMNS.items():
            name_col = "f_geometry_column" if view == "geometry_columns" else "f_geography_column"
            tbl_col = "f_table_name" if view == "geometry_columns" else "f_table_name"
            row = c.execute(sa.text(f"select type, srid from {view} where {tbl_col}=:t and {name_col}=:c"), {"t": table, "c": col}).one()
            assert (row[0].upper(), row[1]) == (gtype.upper(), srid), (table, col, row)
        idx = {r[0]: r[1] for r in c.execute(sa.text("select indexname, indexdef from pg_indexes where schemaname='public'"))}
        for name in GEO_INDEXES:
            assert name in idx and "USING gist" in idx[name], f"{name} missing or not GiST"
        assert "ix_event_log_chain_id_id" in idx
        # Phase 2 (0003): tables, integrity constraints and the partial unique index
        tables = {r[0] for r in c.execute(sa.text("select tablename from pg_tables where schemaname='public'"))}
        assert {"evidence", "audits", "audit_selection_runs", "audit_corroborations"} <= tables
        cons = {r[0] for r in c.execute(sa.text("select conname from pg_constraint"))}
        assert {"ck_audits_reason_recorded", "ck_evidence_file_iff_stored", "ck_evidence_gps_never_verified", "uq_audit_corroborations_pair"} <= cons
        assert "WHERE" in idx["uq_audits_one_open_per_load"].upper() and "UNIQUE" in idx["uq_audits_one_open_per_load"].upper()
        assert "recorded_by_user_id" in {r[0] for r in c.execute(sa.text("select column_name from information_schema.columns where table_name='receiving_records'"))}
        cols = {r[0] for r in c.execute(sa.text("select column_name from information_schema.columns where table_name='sanitation_reports'"))}
        assert {"location", "issue_type", "status", "ward_id", "queue_id", "location_verified", "legacy_ward_label"} <= cols
        assert not ({"latitude", "longitude", "ward"} & cols), "legacy plain-number coordinates must be gone"
    command.check(cfg)  # raises if models and migrations disagree


def _insert_phase0_data(engine):
    """Rows exactly as the Phase-0 schema (0001) would hold them, incl. a valid hash chain."""
    ts = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    with engine.begin() as c:
        c.execute(sa.text("insert into workers (id, name) values (1, 'W')"))
        c.execute(sa.text("insert into routes (id, ward, worker_id) values (1, 'K/East - Andheri East', 1)"))
        c.execute(sa.text("insert into users (id, username, password_hash, role, name) values (1, 'c', 'x$y', 'CITIZEN', 'C')"))
        c.execute(sa.text("insert into digital_loads (id, route_id, generated_at, status) values ('DL-9001', 1, :t, 'COLLECTING')"), {"t": ts})
        prev = "0" * 64
        for i, et in enumerate(["LOAD_CREATED", "COLLECTION_RECORDED", "LOAD_DECLARED"]):
            payload = {"event_type": et, "ts": ts.isoformat(), "actor": "worker:1", "n": i}
            h = compute_hash(payload, prev)
            c.execute(sa.text("insert into event_log (load_id, event_type, payload_json, prev_hash, hash, created_at) "
                              "values ('DL-9001', :e, cast(:p as json), :ph, :h, :t)"),
                      {"e": et, "p": __import__("json").dumps(payload), "ph": prev, "h": h, "t": ts})
            prev = h
        c.execute(sa.text("insert into sanitation_reports (id, user_id, ward, description, latitude, longitude, photo_name, created_at) values "
                          "(1, 1, 'K/East - Andheri East', 'legacy with gps', 19.075, 72.865, 'a.jpg', :t),"
                          "(2, 1, 'K/East - Andheri East', 'legacy without gps', NULL, NULL, NULL, :t)"), {"t": ts})


def test_upgrade_preserves_phase0_data_and_backfills(scratch_db):
    url, engine = scratch_db
    cfg = alembic_cfg(url)
    command.upgrade(cfg, "0001")
    _insert_phase0_data(engine)
    command.upgrade(cfg, "head")

    with Session(engine) as db:
        # 1. hash chain of an existing load still verifies (hashes untouched, chain_id backfilled)
        v = verify_chain(db, "DL-9001")
        assert v["valid"] and v["total_events"] == 3
        assert db.execute(sa.text("select count(*) from event_log where chain_id <> load_id")).scalar() == 0
        # 2. lat/lng became a PostGIS point at the same place; the legacy label survived; the float columns are gone
        r = db.execute(sa.text("select ST_Y(location::geometry), ST_X(location::geometry), legacy_ward_label, status, issue_type "
                               "from sanitation_reports where id=1")).one()
        assert (round(r[0], 6), round(r[1], 6)) == (19.075, 72.865) and r[2] == "K/East - Andheri East"
        assert (r[3], r[4]) == ("SUBMITTED", "OTHER")
        assert db.execute(sa.text("select location is null from sanitation_reports where id=2")).scalar() is True

        # 3. load wards + route legacy reports through the real routing code (the documented post-migration steps)
        geo.load_wards(db)
        from app.sanitation import route_backfill
        out = route_backfill(db)
        assert out == {"reports_processed": 2, "routed": 1, "unroutable": 1}
        rows = {i: (s, w) for i, s, w in db.execute(sa.text(
            "select r.id, r.status, w.code from sanitation_reports r left join wards w on w.id=r.ward_id"))}
        assert rows[1] == ("ROUTED", "DEMO-A") and rows[2][0] == "UNROUTABLE"
        assert verify_chain(db, "SR-1")["valid"] and verify_chain(db, "SR-2")["valid"]
        assert verify_chain(db, "DL-9001")["valid"]
    command.check(cfg)


def test_downgrade_restores_latlng_and_ward_label(scratch_db):
    url, engine = scratch_db
    cfg = alembic_cfg(url)
    command.upgrade(cfg, "0001")
    _insert_phase0_data(engine)
    command.upgrade(cfg, "head")
    with Session(engine) as db:  # add ticket events that the downgrade must discard
        geo.load_wards(db)
        from app.sanitation import route_backfill
        route_backfill(db)
    command.downgrade(cfg, "0001")
    with engine.connect() as c:
        r = c.execute(sa.text("select latitude, longitude, ward from sanitation_reports where id=1")).one()
        assert (round(r[0], 6), round(r[1], 6), r[2]) == (19.075, 72.865, "K/East - Andheri East")
        assert c.execute(sa.text("select latitude from sanitation_reports where id=2")).scalar() is None
        assert c.execute(sa.text("select count(*) from event_log")).scalar() == 3, "only the 3 load events should remain"
        cols = {x[0] for x in c.execute(sa.text("select column_name from information_schema.columns where table_name='event_log'"))}
        assert "chain_id" not in cols
    command.upgrade(cfg, "head")   # and it can go up again with the restored data
    with Session(engine) as db:
        assert verify_chain(db, "DL-9001")["valid"]


def test_migration_aborts_without_touching_data_on_half_filled_coordinates(scratch_db):
    url, engine = scratch_db
    cfg = alembic_cfg(url)
    command.upgrade(cfg, "0001")
    _insert_phase0_data(engine)
    with engine.begin() as c:
        c.execute(sa.text("update sanitation_reports set longitude = NULL where id = 1"))  # lat set, lng missing
    with pytest.raises(RuntimeError, match=r"half-filled or out of range"):
        command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert c.execute(sa.text("select version_num from alembic_version")).scalar() == "0001"
        assert c.execute(sa.text("select latitude from sanitation_reports where id=1")).scalar() == 19.075  # untouched


def test_0003_backfills_who_recorded_the_receiving_record_from_the_chain(scratch_db):
    """recorded_by_user_id is filled from the RECEIVING_RECORDED event's actor when it names a real user; otherwise it stays NULL."""
    import json as _json
    url, engine = scratch_db
    cfg = alembic_cfg(url)
    command.upgrade(cfg, "0002")
    ts = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    with engine.begin() as c:
        c.execute(sa.text("insert into workers (id, name) values (1, 'W')"))
        c.execute(sa.text("insert into routes (id, ward, worker_id) values (1, 'Demo Ward A', 1)"))
        c.execute(sa.text("insert into facilities (id, name, kind) values (1, 'F1', 'x')"))
        c.execute(sa.text("insert into users (id, username, password_hash, role, name, facility_id) values "
                          "(5, 'fac', 'x$y', 'FACILITY', 'F', 1), (6, 'adm', 'x$y', 'MUNICIPAL_ADMIN', 'A', NULL)"))
        cases = {"DL-9101": ("facility:5", 5), "DL-9102": ("municipal_admin:6", 6), "DL-9103": ("facility:seed", None), "DL-9104": ("facility:99", None)}
        for n, (lid, (actor, _)) in enumerate(cases.items(), start=1):
            c.execute(sa.text("insert into digital_loads (id, route_id, generated_at, status) values (:l, 1, :t, 'DECLARED')"), {"l": lid, "t": ts})
            c.execute(sa.text("insert into receiving_records (id, load_id, facility_id, quantity, condition, timestamp) values (:i, :l, 1, 100, 'ACCEPTABLE', :t)"),
                      {"i": n, "l": lid, "t": ts})
            payload = {"event_type": "RECEIVING_RECORDED", "ts": ts.isoformat(), "actor": actor, "receiving_record_id": n}
            h = compute_hash(payload, "0" * 64)
            c.execute(sa.text("insert into event_log (chain_id, load_id, event_type, payload_json, prev_hash, hash, created_at) "
                              "values (:l, :l, 'RECEIVING_RECORDED', cast(:p as json), :ph, :h, :t)"),
                      {"l": lid, "p": _json.dumps(payload), "ph": "0" * 64, "h": h, "t": ts})
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        got = dict(c.execute(sa.text("select load_id, recorded_by_user_id from receiving_records order by id")).all())
    assert got == {lid: expect for lid, (_, expect) in cases.items()}, got
    with Session(engine) as db:
        assert all(verify_chain(db, lid)["valid"] for lid in cases), "existing chains must be untouched by the migration"
    command.check(cfg)
    command.downgrade(cfg, "0002")            # and back: the column and Phase 2 tables disappear, the data stays
    with engine.connect() as c:
        assert c.execute(sa.text("select count(*) from receiving_records")).scalar() == 4
        assert "recorded_by_user_id" not in {r[0] for r in c.execute(sa.text("select column_name from information_schema.columns where table_name='receiving_records'"))}
        assert "evidence" not in {r[0] for r in c.execute(sa.text("select tablename from pg_tables where schemaname='public'"))}


def test_application_tests_pass_on_the_migrated_schema(scratch_db):
    """Migrate a clean DB with Alembic, then run the app test-suites against THAT schema (not create_all's)."""
    url, engine = scratch_db
    command.upgrade(alembic_cfg(url), "head")
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False), "TEST_SCHEMA": "alembic", "PYTHONDONTWRITEBYTECODE": "1"}
    res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                          str(BACKEND / "tests" / "test_core.py"), str(BACKEND / "tests" / "test_geo.py"),
                          str(BACKEND / "tests" / "test_evidence.py"), str(BACKEND / "tests" / "test_independence.py"),
                          str(BACKEND / "tests" / "test_audit_selection.py")],
                         cwd=BACKEND, env=env, capture_output=True, text=True, timeout=600)
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-1500:]
    command.check(alembic_cfg(url))
