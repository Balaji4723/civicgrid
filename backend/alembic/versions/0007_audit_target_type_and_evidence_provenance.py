"""Audit target type and evidence provenance.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-25 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM('COLLECTION_EVENT', 'DIGITAL_LOAD', name='audit_target_type').create(bind, checkfirst=True)

    op.add_column('audits', sa.Column('target_type', postgresql.ENUM('COLLECTION_EVENT', 'DIGITAL_LOAD', name='audit_target_type', create_type=False), server_default='DIGITAL_LOAD', nullable=False))
    op.add_column('audits', sa.Column('collection_event_id', sa.Integer(), nullable=True))
    op.add_column('audits', sa.Column('household_id', sa.Integer(), nullable=True))
    op.add_column('audits', sa.Column('actor_user_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_audits_collection_event_id', 'audits', 'collection_events', ['collection_event_id'], ['id'])
    op.create_foreign_key('fk_audits_household_id', 'audits', 'households', ['household_id'], ['id'])
    op.create_foreign_key('fk_audits_actor_user_id', 'audits', 'users', ['actor_user_id'], ['id'])

    op.add_column('evidence', sa.Column('provenance', sa.String(length=40), nullable=True))
    op.add_column('evidence', sa.Column('collection_event_id', sa.Integer(), nullable=True))
    op.add_column('evidence', sa.Column('household_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_evidence_collection_event_id', 'evidence', 'collection_events', ['collection_event_id'], ['id'])
    op.create_foreign_key('fk_evidence_household_id', 'evidence', 'households', ['household_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_evidence_household_id', 'evidence', type_='foreignkey')
    op.drop_constraint('fk_evidence_collection_event_id', 'evidence', type_='foreignkey')
    op.drop_column('evidence', 'household_id')
    op.drop_column('evidence', 'collection_event_id')
    op.drop_column('evidence', 'provenance')

    op.drop_constraint('fk_audits_actor_user_id', 'audits', type_='foreignkey')
    op.drop_constraint('fk_audits_household_id', 'audits', type_='foreignkey')
    op.drop_constraint('fk_audits_collection_event_id', 'audits', type_='foreignkey')
    op.drop_column('audits', 'actor_user_id')
    op.drop_column('audits', 'household_id')
    op.drop_column('audits', 'collection_event_id')
    op.drop_column('audits', 'target_type')

    bind = op.get_bind()
    postgresql.ENUM(name='audit_target_type').drop(bind, checkfirst=True)
