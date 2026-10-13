from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    if engine.dialect.name == "postgresql":
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("SET search_path TO public")
            cursor.close()
        except Exception:
            pass


@event.listens_for(SessionLocal, "after_begin")
def receive_after_begin(session, transaction, connection):
    if engine.dialect.name == "postgresql":
        from .sessions import current_session_id, ensure_session_schema
        sid = current_session_id.get()
        if sid:
            schema = ensure_session_schema(engine, sid)
            if schema:
                connection.execute(text(f'SET search_path TO "{schema}", public'))
            else:
                connection.execute(text("SET search_path TO public"))
        else:
            connection.execute(text("SET search_path TO public"))


def get_db():
    db = SessionLocal()
    from .sessions import current_session_id, ensure_session_schema
    sid = current_session_id.get()
    if sid:
        schema = ensure_session_schema(engine, sid)
        if schema:
            db.execute(text(f'SET search_path TO "{schema}", public'))
        else:
            db.execute(text("SET search_path TO public"))
    else:
        db.execute(text("SET search_path TO public"))
    try:
        yield db
    finally:
        db.close()
