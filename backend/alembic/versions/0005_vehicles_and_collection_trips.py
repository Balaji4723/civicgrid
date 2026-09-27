"""Vehicles, collection trips, trip crews, and digital load links.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-24 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('vehicles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('registration_number', sa.String(length=40), nullable=False),
        sa.Column('vehicle_type', sa.String(length=60), nullable=False),
        sa.Column('capacity_kg', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('assigned_ward', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('registration_number')
    )

    op.create_table('collection_trips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_code', sa.String(length=40), nullable=False),
        sa.Column('route_id', sa.Integer(), nullable=False),
        sa.Column('vehicle_id', sa.Integer(), nullable=True),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('verification_triggered', sa.Boolean(), nullable=False),
        sa.Column('verification_acknowledged', sa.Boolean(), nullable=False),
        sa.Column('verification_paused_at_count', sa.Integer(), nullable=True),
        sa.Column('receiving_facility_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['receiving_facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['route_id'], ['routes.id'], ),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trip_code')
    )

    op.create_table('trip_crews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('role_in_crew', sa.String(length=60), nullable=False),
        sa.ForeignKeyConstraint(['trip_id'], ['collection_trips.id'], ),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.add_column('digital_loads', sa.Column('trip_id', sa.Integer(), nullable=True))
    op.add_column('digital_loads', sa.Column('vehicle_id', sa.Integer(), nullable=True))
    op.add_column('digital_loads', sa.Column('receiving_facility_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_digital_loads_trip_id', 'digital_loads', 'collection_trips', ['trip_id'], ['id'])
    op.create_foreign_key('fk_digital_loads_vehicle_id', 'digital_loads', 'vehicles', ['vehicle_id'], ['id'])
    op.create_foreign_key('fk_digital_loads_receiving_facility_id', 'digital_loads', 'facilities', ['receiving_facility_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_digital_loads_receiving_facility_id', 'digital_loads', type_='foreignkey')
    op.drop_constraint('fk_digital_loads_vehicle_id', 'digital_loads', type_='foreignkey')
    op.drop_constraint('fk_digital_loads_trip_id', 'digital_loads', type_='foreignkey')
    op.drop_column('digital_loads', 'receiving_facility_id')
    op.drop_column('digital_loads', 'vehicle_id')
    op.drop_column('digital_loads', 'trip_id')

    op.drop_table('trip_crews')
    op.drop_table('collection_trips')
    op.drop_table('vehicles')
