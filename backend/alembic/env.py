from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import create_engine

from app.config import DATABASE_URL
from app.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    # `sqlalchemy.url` can be injected (tests do this to migrate a scratch database);
    # otherwise the app's DATABASE_URL is used.
    url = config.get_main_option("sqlalchemy.url") or DATABASE_URL
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # GeoAlchemy2: ignore PostGIS' own tables (spatial_ref_sys), render geometry types/indexes correctly
            include_object=alembic_helpers.include_object,
            process_revision_directives=alembic_helpers.writer,
            render_item=alembic_helpers.render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
