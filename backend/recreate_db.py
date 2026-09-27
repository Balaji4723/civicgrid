import os
from pathlib import Path
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from app.db import engine

# 1. Drop all application tables and custom enum types
with engine.connect() as conn:
    tables = [r[0] for r in conn.execute(sa.text("select tablename from pg_tables where schemaname='public' and tablename <> 'spatial_ref_sys'"))]
    for t in tables:
        conn.execute(sa.text(f'DROP TABLE IF EXISTS "{t}" CASCADE'))
    enums = [r[0] for r in conn.execute(sa.text("select typname from pg_type where typtype='e'"))]
    for e in enums:
        conn.execute(sa.text(f'DROP TYPE IF EXISTS "{e}" CASCADE'))
    conn.commit()

# 2. Run Alembic upgrade head
backend_dir = Path(__file__).resolve().parent
cfg = Config(str(backend_dir / "alembic.ini"))
cfg.set_main_option("script_location", str(backend_dir / "alembic"))
command.upgrade(cfg, "head")
print("Alembic upgrade head completed successfully.")
