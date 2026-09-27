import sys, os
sys.path.insert(0, os.path.abspath("backend"))
from app.db import engine
from sqlalchemy import text

statements = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS capability VARCHAR(60);",
    "ALTER TABLE audits ADD COLUMN IF NOT EXISTS target_type VARCHAR(40) DEFAULT 'DIGITAL_LOAD';",
    "ALTER TABLE audits ADD COLUMN IF NOT EXISTS collection_event_id INTEGER REFERENCES collection_events(id);",
    "ALTER TABLE audits ADD COLUMN IF NOT EXISTS household_id INTEGER REFERENCES households(id);",
    "ALTER TABLE audits ADD COLUMN IF NOT EXISTS actor_user_id INTEGER REFERENCES users(id);",
    "ALTER TABLE evidence ADD COLUMN IF NOT EXISTS provenance VARCHAR(40);",
    "ALTER TABLE evidence ADD COLUMN IF NOT EXISTS collection_event_id INTEGER REFERENCES collection_events(id);",
    "ALTER TABLE evidence ADD COLUMN IF NOT EXISTS household_id INTEGER REFERENCES households(id);"
]

with engine.begin() as conn:
    for stmt in statements:
        try:
            conn.execute(text(stmt))
            print(f"Executed: {stmt}")
        except Exception as e:
            print(f"Error executing {stmt}: {e}")

print("PostgreSQL migration applied successfully.")
