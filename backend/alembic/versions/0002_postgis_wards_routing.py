"""PostGIS foundation: wards, spatial columns, GPS routing tables, generalised event chains.

Revision ID: 0002
Revises: 0001

Upgrade
  * enables the PostGIS extension (needs a superuser / trusted role; the Docker image's POSTGRES_USER is one)
  * creates authority_queues, wards (MULTIPOLYGON), sanitation_routing_decisions
  * adds geography(POINT) location columns to households / facilities / sanitation_reports,
    ward_id FKs, and a routes.path LINESTRING - all with GiST spatial indexes
  * BACKFILL: sanitation_reports.latitude/longitude -> location, then the two float columns are dropped.
    The migration ABORTS (no data is touched) if any legacy row has a half-filled or out-of-range pair.
  * event_log gets chain_id (backfilled = load_id) so non-load entities can have their own hash chain;
    load_id becomes nullable. Existing hashes are unchanged, so existing chains still verify.

Downgrade restores latitude/longitude from the geography points, drops everything added here and the enum
types it created. The PostGIS *extension* is intentionally left installed (it may be used by other objects).
Ticket events (load_id IS NULL) are deleted on downgrade because their tickets no longer exist.
"""
import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ISSUE_TYPES = ("OVERFLOWING_BIN", "ILLEGAL_DUMPING", "BLOCKED_DRAIN", "MISSED_COLLECTION", "OTHER")
TICKET_STATUSES = ("SUBMITTED", "ROUTED", "UNROUTABLE", "IN_PROGRESS", "RESOLVED")
ROUTING_OUTCOMES = ("ROUTED", "UNROUTABLE")


def _enum(name, values):
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # ---- pre-flight: refuse to drop legacy lat/lng if they cannot all be converted losslessly
    bad = bind.execute(sa.text(
        "SELECT id FROM sanitation_reports WHERE "
        "((latitude IS NULL) <> (longitude IS NULL)) "
        "OR latitude NOT BETWEEN -90 AND 90 OR longitude NOT BETWEEN -180 AND 180 ORDER BY id"
    )).scalars().all()
    if bad:
        raise RuntimeError(
            f"Cannot migrate sanitation_reports {bad}: latitude/longitude are half-filled or out of range. "
            "Fix or NULL both columns for these rows, then re-run the migration. No changes were made."
        )

    for name, values in (("issue_type", ISSUE_TYPES), ("ticket_status", TICKET_STATUSES), ("routing_outcome", ROUTING_OUTCOMES)):
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    # ---- authority queues + wards
    op.create_table(
        "authority_queues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "wards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("boundary", geoalchemy2.types.Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False, from_text="ST_GeomFromEWKT", name="geometry"), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=True),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("source_label", sa.String(length=255), nullable=False),
        sa.Column("source_version", sa.String(length=60), nullable=False),
        sa.Column("is_official", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["queue_id"], ["authority_queues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("idx_wards_boundary", "wards", ["boundary"], postgresql_using="gist")

    # ---- spatial columns on existing tables
    point = lambda: geoalchemy2.types.Geography(geometry_type="POINT", srid=4326, spatial_index=False, from_text="ST_GeogFromText", name="geography")

    op.add_column("facilities", sa.Column("location", point(), nullable=True))
    op.create_index("idx_facilities_location", "facilities", ["location"], postgresql_using="gist")

    op.add_column("households", sa.Column("ward_id", sa.Integer(), nullable=True))
    op.add_column("households", sa.Column("location", point(), nullable=True))
    op.create_foreign_key("fk_households_ward_id", "households", "wards", ["ward_id"], ["id"])
    op.create_index("ix_households_ward_id", "households", ["ward_id"])
    op.create_index("idx_households_location", "households", ["location"], postgresql_using="gist")

    op.add_column("routes", sa.Column("ward_id", sa.Integer(), nullable=True))
    op.add_column("routes", sa.Column("path", geoalchemy2.types.Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False, from_text="ST_GeomFromEWKT", name="geometry"), nullable=True))
    op.create_foreign_key("fk_routes_ward_id", "routes", "wards", ["ward_id"], ["id"])
    op.create_index("ix_routes_ward_id", "routes", ["ward_id"])
    op.create_index("idx_routes_path", "routes", ["path"], postgresql_using="gist")

    # ---- sanitation_reports -> routed ticket with a PostGIS point (BACKFILL from lat/lng)
    op.add_column("sanitation_reports", sa.Column("location", point(), nullable=True))
    op.execute(
        "UPDATE sanitation_reports SET location = "
        "ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography "
        "WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    )
    op.drop_column("sanitation_reports", "latitude")
    op.drop_column("sanitation_reports", "longitude")
    op.alter_column("sanitation_reports", "ward", new_column_name="legacy_ward_label", existing_type=sa.String(64), nullable=True)
    op.add_column("sanitation_reports", sa.Column("issue_type", _enum("issue_type", ISSUE_TYPES), server_default="OTHER", nullable=False))
    op.add_column("sanitation_reports", sa.Column("location_source", sa.String(length=30), server_default="DEVICE_REPORTED", nullable=False))
    op.add_column("sanitation_reports", sa.Column("location_verified", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("sanitation_reports", sa.Column("location_accuracy_m", sa.Float(), nullable=True))
    op.add_column("sanitation_reports", sa.Column("status", _enum("ticket_status", TICKET_STATUSES), server_default="SUBMITTED", nullable=False))
    op.add_column("sanitation_reports", sa.Column("ward_id", sa.Integer(), nullable=True))
    op.add_column("sanitation_reports", sa.Column("queue_id", sa.Integer(), nullable=True))
    op.add_column("sanitation_reports", sa.Column("resolution_note", sa.Text(), nullable=True))
    op.add_column("sanitation_reports", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_sanitation_reports_ward_id", "sanitation_reports", "wards", ["ward_id"], ["id"])
    op.create_foreign_key("fk_sanitation_reports_queue_id", "sanitation_reports", "authority_queues", ["queue_id"], ["id"])
    op.create_index("idx_sanitation_reports_location", "sanitation_reports", ["location"], postgresql_using="gist")
    op.create_index("ix_sanitation_reports_ward_status", "sanitation_reports", ["ward_id", "status"])

    # ---- event_log: chain_id (existing chains keep their hashes; chain_id = load_id)
    op.add_column("event_log", sa.Column("chain_id", sa.String(length=40), nullable=True))
    op.execute("UPDATE event_log SET chain_id = load_id")
    op.alter_column("event_log", "chain_id", nullable=False)
    op.alter_column("event_log", "load_id", existing_type=sa.String(length=20), nullable=True)
    op.create_index("ix_event_log_chain_id_id", "event_log", ["chain_id", "id"])
    op.create_check_constraint("ck_event_log_chain_matches_load", "event_log", "load_id IS NULL OR chain_id = load_id")

    # ---- routing decisions (after event_log changes; references event_log.id)
    op.create_table(
        "sanitation_routing_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("outcome", _enum("routing_outcome", ROUTING_OUTCOMES), nullable=False),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("ward_id", sa.Integer(), nullable=True),
        sa.Column("queue_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("boundary_source", sa.String(length=120), nullable=True),
        sa.Column("boundary_is_official", sa.Boolean(), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["sanitation_reports.id"]),
        sa.ForeignKeyConstraint(["ward_id"], ["wards.id"]),
        sa.ForeignKeyConstraint(["queue_id"], ["authority_queues.id"]),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["event_log.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sanitation_routing_decisions_report_id", "sanitation_routing_decisions", ["report_id"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_sanitation_routing_decisions_report_id", table_name="sanitation_routing_decisions")
    op.drop_table("sanitation_routing_decisions")

    # event_log back to load-only chains (ticket events belong to tickets that are about to disappear)
    op.execute("DELETE FROM event_log WHERE load_id IS NULL")
    op.drop_constraint("ck_event_log_chain_matches_load", "event_log", type_="check")
    op.drop_index("ix_event_log_chain_id_id", table_name="event_log")
    op.alter_column("event_log", "load_id", existing_type=sa.String(length=20), nullable=False)
    op.drop_column("event_log", "chain_id")

    # sanitation_reports: restore latitude/longitude from the geography point, restore the NOT NULL ward label
    op.add_column("sanitation_reports", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("sanitation_reports", sa.Column("longitude", sa.Float(), nullable=True))
    op.execute(
        "UPDATE sanitation_reports SET latitude = ST_Y(location::geometry), longitude = ST_X(location::geometry) "
        "WHERE location IS NOT NULL"
    )
    op.execute(
        "UPDATE sanitation_reports SET legacy_ward_label = COALESCE(legacy_ward_label, "
        "(SELECT name FROM wards WHERE wards.id = sanitation_reports.ward_id), 'UNKNOWN')"
    )
    op.drop_index("ix_sanitation_reports_ward_status", table_name="sanitation_reports")
    op.drop_index("idx_sanitation_reports_location", table_name="sanitation_reports")
    op.drop_constraint("fk_sanitation_reports_queue_id", "sanitation_reports", type_="foreignkey")
    op.drop_constraint("fk_sanitation_reports_ward_id", "sanitation_reports", type_="foreignkey")
    for col in ("updated_at", "resolution_note", "queue_id", "ward_id", "status", "location_accuracy_m",
                "location_verified", "location_source", "issue_type", "location"):
        op.drop_column("sanitation_reports", col)
    op.alter_column("sanitation_reports", "legacy_ward_label", new_column_name="ward", existing_type=sa.String(64), nullable=False)

    op.drop_index("idx_routes_path", table_name="routes")
    op.drop_index("ix_routes_ward_id", table_name="routes")
    op.drop_constraint("fk_routes_ward_id", "routes", type_="foreignkey")
    op.drop_column("routes", "path")
    op.drop_column("routes", "ward_id")

    op.drop_index("idx_households_location", table_name="households")
    op.drop_index("ix_households_ward_id", table_name="households")
    op.drop_constraint("fk_households_ward_id", "households", type_="foreignkey")
    op.drop_column("households", "location")
    op.drop_column("households", "ward_id")

    op.drop_index("idx_facilities_location", table_name="facilities")
    op.drop_column("facilities", "location")

    op.drop_index("idx_wards_boundary", table_name="wards")
    op.drop_table("wards")
    op.drop_table("authority_queues")

    for name in ("routing_outcome", "ticket_status", "issue_type"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
    # NOTE: the postgis extension is deliberately not dropped.
