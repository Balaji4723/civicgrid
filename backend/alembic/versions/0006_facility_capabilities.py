"""Facility capabilities on users table.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-25 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('capability', sa.String(length=60), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'capability')
