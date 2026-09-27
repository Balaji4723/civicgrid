"""Phase 3 (schema only): processing records, handoffs, final dispositions, disposal exceptions.

Revision ID: 0004
Revises: 0003

Adds four new tables and 7 new enum types. digital_loads.status (LoadStatus) is NOT touched - see the
architecture note above the Phase 3 models in app/models.py. Nothing existing is altered or dropped, so
existing hash chains, the Phase 1/2 lifecycle and all 182 existing tests are unaffected.

No data migration/backfill: these are brand-new tables with no Phase 1/2 equivalent to backfill from.
No services/routers/frontend wiring in this migration - schema only, per the Phase 3 Step 1 scope.

Table creation order matters here: disposal_exceptions references both processing_records and handoffs
(as the ONE triggering stage) and handoffs (as the resulting rerouted handoff), so it is created after
both. final_dispositions references handoffs and processing_records only (never disposal_exceptions - see
the model docstring), so it can be created any time after those two. There is no circular FK dependency
between handoffs and disposal_exceptions: the link is one-directional (disposal_exceptions.resulting_
handoff_id -> handoffs.id), so no ALTER TABLE-after-the-fact trick is needed.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


ENUMS = {
    'processing_status': ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'),
    'waste_stream': ('ORGANIC', 'RECYCLABLE', 'MIXED', 'RESIDUAL', 'RECOVERED', 'HAZARDOUS', 'OTHER'),
    'processing_method': ('COMPOSTING', 'RECYCLING', 'MATERIAL_RECOVERY', 'INCINERATION', 'LANDFILL', 'OTHER'),
    'handoff_status': ('PENDING', 'IN_TRANSIT', 'COMPLETED', 'CANCELLED'),
    'disposition_type': ('LANDFILL', 'RECYCLING', 'COMPOSTING', 'INCINERATION', 'WASTE_TO_ENERGY', 'OTHER'),
    'disposition_status': ('RECORDED', 'VERIFIED', 'CANCELLED'),
    'disposal_exception_status': ('RAISED', 'PENDING_AUTHORIZATION', 'AUTHORIZED', 'REJECTED', 'RESOLVED', 'CANCELLED'),
}


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    def enum_col(name):
        # create_type=False: the type was already created above (waste_stream is used by two tables -
        # letting SQLAlchemy create it a second time is the exact "type already exists" bug 0003 avoided).
        return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)

    op.create_table('processing_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('digital_load_id', sa.String(length=20), nullable=False),
        sa.Column('facility_id', sa.Integer(), nullable=False),
        sa.Column('waste_stream', enum_col('waste_stream'), nullable=False),
        sa.Column('processing_method', enum_col('processing_method'), nullable=False),
        sa.Column('processed_quantity_kg', sa.Integer(), nullable=False),
        sa.Column('recovered_quantity_kg', sa.Integer(), server_default='0', nullable=False),
        sa.Column('residual_quantity_kg', sa.Integer(), server_default='0', nullable=False),
        sa.Column('status', enum_col('processing_status'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recorded_by_user_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.CheckConstraint('processed_quantity_kg > 0', name='ck_processing_records_processed_qty_positive'),
        sa.CheckConstraint('recovered_quantity_kg >= 0', name='ck_processing_records_recovered_qty_non_negative'),
        sa.CheckConstraint('residual_quantity_kg >= 0', name='ck_processing_records_residual_qty_non_negative'),
        sa.CheckConstraint('recovered_quantity_kg + residual_quantity_kg <= processed_quantity_kg',
                            name='ck_processing_records_output_within_input'),
        sa.CheckConstraint("status <> 'COMPLETED' OR completed_at IS NOT NULL",
                            name='ck_processing_records_completed_has_timestamp'),
        sa.ForeignKeyConstraint(['digital_load_id'], ['digital_loads.id'], ),
        sa.ForeignKeyConstraint(['event_id'], ['event_log.id'], ),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['recorded_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_processing_records_facility_id', 'processing_records', ['facility_id'], unique=False)
    op.create_index('ix_processing_records_load_id', 'processing_records', ['digital_load_id'], unique=False)
    op.create_index('ix_processing_records_status', 'processing_records', ['status'], unique=False)
    op.create_index('uq_processing_records_one_open_per_load', 'processing_records', ['digital_load_id'],
                     unique=True, postgresql_where=sa.text("status IN ('PENDING','IN_PROGRESS')"))

    op.create_table('handoffs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('digital_load_id', sa.String(length=20), nullable=False),
        sa.Column('processing_record_id', sa.Integer(), nullable=True),
        sa.Column('source_facility_id', sa.Integer(), nullable=False),
        sa.Column('destination_facility_id', sa.Integer(), nullable=False),
        sa.Column('quantity_kg', sa.Integer(), nullable=False),
        sa.Column('waste_stream', enum_col('waste_stream'), nullable=False),
        sa.Column('status', enum_col('handoff_status'), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_by_user_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.CheckConstraint('quantity_kg > 0', name='ck_handoffs_qty_positive'),
        sa.CheckConstraint('source_facility_id <> destination_facility_id', name='ck_handoffs_source_ne_destination'),
        sa.ForeignKeyConstraint(['destination_facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['digital_load_id'], ['digital_loads.id'], ),
        sa.ForeignKeyConstraint(['event_id'], ['event_log.id'], ),
        sa.ForeignKeyConstraint(['processing_record_id'], ['processing_records.id'], ),
        sa.ForeignKeyConstraint(['recorded_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['source_facility_id'], ['facilities.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_handoffs_load_id', 'handoffs', ['digital_load_id'], unique=False)
    op.create_index('ix_handoffs_processing_record_id', 'handoffs', ['processing_record_id'], unique=False)
    op.create_index('ix_handoffs_status', 'handoffs', ['status'], unique=False)
    op.create_index('uq_handoffs_one_open_per_load', 'handoffs', ['digital_load_id'],
                     unique=True, postgresql_where=sa.text("status IN ('PENDING','IN_TRANSIT')"))

    op.create_table('disposal_exceptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('digital_load_id', sa.String(length=20), nullable=False),
        sa.Column('source_processing_record_id', sa.Integer(), nullable=True),
        sa.Column('source_handoff_id', sa.Integer(), nullable=True),
        sa.Column('original_destination_facility_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', enum_col('disposal_exception_status'), nullable=False),
        sa.Column('alternative_destination_facility_id', sa.Integer(), nullable=True),
        sa.Column('resulting_handoff_id', sa.Integer(), nullable=True),
        sa.Column('raised_by_user_id', sa.Integer(), nullable=True),
        sa.Column('authorized_by_user_id', sa.Integer(), nullable=True),
        sa.Column('authorized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_reason', sa.Text(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.CheckConstraint('length(reason) >= 10', name='ck_disposal_exceptions_reason_recorded'),
        sa.CheckConstraint(
            '(CASE WHEN source_processing_record_id IS NOT NULL THEN 1 ELSE 0 END) '
            '+ (CASE WHEN source_handoff_id IS NOT NULL THEN 1 ELSE 0 END) = 1',
            name='ck_disposal_exceptions_one_source'),
        sa.CheckConstraint(
            'alternative_destination_facility_id IS NULL OR alternative_destination_facility_id <> original_destination_facility_id',
            name='ck_disposal_exceptions_alt_ne_original'),
        sa.CheckConstraint(
            "status NOT IN ('AUTHORIZED','RESOLVED') OR alternative_destination_facility_id IS NOT NULL",
            name='ck_disposal_exceptions_authorized_has_alt_destination'),
        sa.ForeignKeyConstraint(['alternative_destination_facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['authorized_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['digital_load_id'], ['digital_loads.id'], ),
        sa.ForeignKeyConstraint(['event_id'], ['event_log.id'], ),
        sa.ForeignKeyConstraint(['original_destination_facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['raised_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['resulting_handoff_id'], ['handoffs.id'], ),
        sa.ForeignKeyConstraint(['source_handoff_id'], ['handoffs.id'], ),
        sa.ForeignKeyConstraint(['source_processing_record_id'], ['processing_records.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('resulting_handoff_id', name='uq_disposal_exceptions_resulting_handoff'),
    )
    op.create_index('ix_disposal_exceptions_load_id', 'disposal_exceptions', ['digital_load_id'], unique=False)
    op.create_index('ix_disposal_exceptions_status', 'disposal_exceptions', ['status'], unique=False)
    op.create_index('uq_disposal_exceptions_one_open_per_load', 'disposal_exceptions', ['digital_load_id'],
                     unique=True, postgresql_where=sa.text("status IN ('RAISED','PENDING_AUTHORIZATION')"))

    op.create_table('final_dispositions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('digital_load_id', sa.String(length=20), nullable=False),
        sa.Column('handoff_id', sa.Integer(), nullable=True),
        sa.Column('processing_record_id', sa.Integer(), nullable=True),
        sa.Column('disposition_type', enum_col('disposition_type'), nullable=False),
        sa.Column('destination_facility_id', sa.Integer(), nullable=False),
        sa.Column('quantity_kg', sa.Integer(), nullable=False),
        sa.Column('status', enum_col('disposition_status'), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_by_user_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.CheckConstraint('quantity_kg > 0', name='ck_final_dispositions_qty_positive'),
        sa.ForeignKeyConstraint(['destination_facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['digital_load_id'], ['digital_loads.id'], ),
        sa.ForeignKeyConstraint(['event_id'], ['event_log.id'], ),
        sa.ForeignKeyConstraint(['handoff_id'], ['handoffs.id'], ),
        sa.ForeignKeyConstraint(['processing_record_id'], ['processing_records.id'], ),
        sa.ForeignKeyConstraint(['recorded_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_final_dispositions_handoff_id', 'final_dispositions', ['handoff_id'], unique=False)
    op.create_index('ix_final_dispositions_load_id', 'final_dispositions', ['digital_load_id'], unique=False)
    op.create_index('ix_final_dispositions_processing_record_id', 'final_dispositions', ['processing_record_id'], unique=False)
    op.create_index('ix_final_dispositions_status', 'final_dispositions', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_final_dispositions_status', table_name='final_dispositions')
    op.drop_index('ix_final_dispositions_processing_record_id', table_name='final_dispositions')
    op.drop_index('ix_final_dispositions_load_id', table_name='final_dispositions')
    op.drop_index('ix_final_dispositions_handoff_id', table_name='final_dispositions')
    op.drop_table('final_dispositions')

    op.drop_index('uq_disposal_exceptions_one_open_per_load', table_name='disposal_exceptions',
                   postgresql_where=sa.text("status IN ('RAISED','PENDING_AUTHORIZATION')"))
    op.drop_index('ix_disposal_exceptions_status', table_name='disposal_exceptions')
    op.drop_index('ix_disposal_exceptions_load_id', table_name='disposal_exceptions')
    op.drop_table('disposal_exceptions')

    op.drop_index('uq_handoffs_one_open_per_load', table_name='handoffs',
                   postgresql_where=sa.text("status IN ('PENDING','IN_TRANSIT')"))
    op.drop_index('ix_handoffs_status', table_name='handoffs')
    op.drop_index('ix_handoffs_processing_record_id', table_name='handoffs')
    op.drop_index('ix_handoffs_load_id', table_name='handoffs')
    op.drop_table('handoffs')

    op.drop_index('uq_processing_records_one_open_per_load', table_name='processing_records',
                   postgresql_where=sa.text("status IN ('PENDING','IN_PROGRESS')"))
    op.drop_index('ix_processing_records_status', table_name='processing_records')
    op.drop_index('ix_processing_records_load_id', table_name='processing_records')
    op.drop_index('ix_processing_records_facility_id', table_name='processing_records')
    op.drop_table('processing_records')

    # autogenerate never drops PostgreSQL ENUM types; leaving them behind breaks upgrade-after-downgrade
    for name in ENUMS:
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
