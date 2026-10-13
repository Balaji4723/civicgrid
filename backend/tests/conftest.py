import os

# Must be set before the app is imported. Uses a throwaway database.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://civicgrid:civicgrid@localhost:5432/civicgrid_test")
# Phase 0/1 tests use the LEGACY note-only evidence and manual-audit paths, which exist only when this is false.
# Phase 2 tests switch it to true with the `file_evidence_required` fixture (that is the Docker/demo setting).
os.environ.setdefault("REQUIRE_FILE_EVIDENCE", "false")
import tempfile as _tempfile
_cg_parent = _tempfile.mkdtemp(prefix="cg_root_")
_cg_storage = os.path.join(_cg_parent, "storage")
os.makedirs(_cg_storage, exist_ok=True)
os.environ.setdefault("EVIDENCE_STORAGE_DIR", _cg_storage)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import seed
from app.db import SessionLocal, engine
from app.main import app
from app.models import Base


@pytest.fixture(autouse=True)
def fresh_db():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text("DO $$ BEGIN CREATE TYPE audit_target_type AS ENUM ('COLLECTION_EVENT', 'DIGITAL_LOAD'); EXCEPTION WHEN duplicate_object THEN null; END $$;"))
        conn.execute(text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS capability VARCHAR(60)"))
        conn.execute(text("ALTER TABLE IF EXISTS audits ADD COLUMN IF NOT EXISTS target_type audit_target_type NOT NULL DEFAULT 'DIGITAL_LOAD'"))
        conn.execute(text("ALTER TABLE IF EXISTS audits ADD COLUMN IF NOT EXISTS collection_event_id INTEGER REFERENCES collection_events(id)"))
        conn.execute(text("ALTER TABLE IF EXISTS audits ADD COLUMN IF NOT EXISTS household_id INTEGER REFERENCES households(id)"))
        conn.execute(text("ALTER TABLE IF EXISTS audits ADD COLUMN IF NOT EXISTS actor_user_id INTEGER REFERENCES users(id)"))
        conn.execute(text("ALTER TABLE IF EXISTS evidence ADD COLUMN IF NOT EXISTS provenance VARCHAR(40)"))
        conn.execute(text("ALTER TABLE IF EXISTS evidence ADD COLUMN IF NOT EXISTS collection_event_id INTEGER REFERENCES collection_events(id)"))
        conn.execute(text("ALTER TABLE IF EXISTS evidence ADD COLUMN IF NOT EXISTS household_id INTEGER REFERENCES households(id)"))
    try:
        Base.metadata.create_all(engine)
    except Exception:
        pass
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text("SET search_path TO public"))
        conn.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    from app.sessions import reset_session_schemas
    reset_session_schemas(engine)
    with SessionLocal() as db:
        db.execute(text("SET search_path TO public"))
        workers = seed.seed_reference_data(db)
        seed.seed_scenarios(db, workers)
    yield


@pytest.fixture(autouse=True)
def clean_evidence_storage():
    from app.evidence_storage import get_storage
    store = get_storage()
    store.purge_all()
    yield


@pytest.fixture()
def file_evidence_required(monkeypatch):
    """The Docker/demo setting: real files required, legacy paths refused."""
    monkeypatch.setenv("REQUIRE_FILE_EVIDENCE", "true")


@pytest.fixture()
def client():
    return TestClient(app)


def login(client, username):
    r = client.post("/auth/login", json={"username": username, "password": seed.PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    return login(client, "admin1")


@pytest.fixture()
def facility(client):
    return login(client, "facility1")
