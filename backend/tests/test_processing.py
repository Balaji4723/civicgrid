"""Phase 3, Step 2 - processing service tests. Pure service-layer tests: no HTTP client, no router (none exists
yet for this step) - calls app.processing directly against a real SessionLocal, exactly like test_audit_selection.py
and test_independence.py call their service modules directly.

Seeded loads used here (see app/seed.py):
    DL-1001  VERIFIED  - clean load, no discrepancy -> directly processable
    DL-1002  DISPUTED  - seeded FLAGGED; `settle_dl1002()` below drives it to CLOSED/SETTLED via resolution.py,
                        the same sequence test_core.py's test_full_walk_flagged_to_closed exercises over HTTP
    DL-1003  DISPUTED  - seeded INVESTIGATING (never closed here) -> stays DISPUTED, used for the "blocked" case
"""
import pytest
from sqlalchemy import select

from app import processing as svc
from app import resolution
from app.db import SessionLocal
from app.errors import ServiceError
from app.hashchain import list_events, verify_chain
from app.models import DiscrepancyEvent, DigitalLoad, LoadStatus, ProcessingMethod, ProcessingRecord, ProcessingStatus, User, WasteStream


def get_user(db, username):
    return db.execute(select(User).where(User.username == username)).scalar_one()


def settle_dl1002(db):
    """FLAGGED -> ... -> CLOSED on DL-1002's discrepancy, so the load becomes SETTLED. Same values as
    test_core.py's test_full_walk_flagged_to_closed (already proven to work end to end)."""
    d = db.execute(select(DiscrepancyEvent).where(DiscrepancyEvent.load_id == "DL-1002")).scalar_one()
    resolution.add_evidence(db, d.id, "facility:test", "Weighbridge slip shows 390 kg", "slip.jpg")
    resolution.corroborate(db, d.id, "facility:test", 385, None, "AUD-07")
    resolution.investigate(db, d.id, "facility:test", "Check transfer point")
    resolution.resolve(db, d.id, "facility:test", "Spillage at transfer point", "PROCESS")
    resolution.close(db, d.id, "facility:test", "Closed")
    db.commit()


# ================================================================ 1. valid creation / preconditions
def test_valid_processing_creation():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        p = svc.start_processing(
            db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED, processing_method=ProcessingMethod.MATERIAL_RECOVERY,
            processed_quantity_kg=468, recovered_quantity_kg=300, residual_quantity_kg=100,
        )
        db.commit()
        assert p.id is not None
        assert p.digital_load_id == "DL-1001" and p.facility_id == 1
        assert p.waste_stream == WasteStream.MIXED and p.processing_method == ProcessingMethod.MATERIAL_RECOVERY
        assert p.processed_quantity_kg == 468 and p.recovered_quantity_kg == 300 and p.residual_quantity_kg == 100
        assert p.recorded_by_user_id == fac1.id
        assert p.status == ProcessingStatus.IN_PROGRESS
        assert p.started_at is not None and p.completed_at is None and p.created_at is not None


def test_processing_of_verified_load_allowed():
    with SessionLocal() as db:
        load = db.get(DigitalLoad, "DL-1001")
        assert load.status == LoadStatus.VERIFIED     # precondition sanity check on the seed
        fac1 = get_user(db, "facility1")
        p = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.ORGANIC,
                                 processing_method=ProcessingMethod.COMPOSTING, processed_quantity_kg=468)
        db.commit()
        assert p.status == ProcessingStatus.IN_PROGRESS


def test_processing_of_settled_load_allowed():
    with SessionLocal() as db:
        settle_dl1002(db)
        load = db.get(DigitalLoad, "DL-1002")
        assert load.status == LoadStatus.SETTLED       # precondition sanity check
        fac1 = get_user(db, "facility1")
        p = svc.start_processing(db, fac1, "DL-1002", facility_id=1, waste_stream=WasteStream.RECYCLABLE,
                                 processing_method=ProcessingMethod.RECYCLING, processed_quantity_kg=390)
        db.commit()
        assert p.status == ProcessingStatus.IN_PROGRESS


def test_processing_blocked_when_discrepancy_unresolved():
    with SessionLocal() as db:
        load = db.get(DigitalLoad, "DL-1002")
        assert load.status == LoadStatus.DISPUTED       # seeded FLAGGED, still open
        fac1 = get_user(db, "facility1")
        with pytest.raises(ServiceError) as exc:
            svc.start_processing(db, fac1, "DL-1002", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=390)
        assert exc.value.status_code == 409 and exc.value.code == "LOAD_NOT_PROCESSABLE"

        load3 = db.get(DigitalLoad, "DL-1003")
        assert load3.status == LoadStatus.DISPUTED       # seeded INVESTIGATING, still open
        with pytest.raises(ServiceError) as exc2:
            svc.start_processing(db, fac1, "DL-1003", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=445)
        assert exc2.value.status_code == 409 and exc2.value.code == "LOAD_NOT_PROCESSABLE"


# ================================================================ 2/3. quantity validation
def test_invalid_quantity_zero_processed_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        with pytest.raises(ServiceError) as exc:
            svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=0)
        assert exc.value.status_code == 422 and exc.value.code == "INVALID_QUANTITY"


def test_recovered_plus_residual_exceeds_processed_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        with pytest.raises(ServiceError) as exc:
            svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.MATERIAL_RECOVERY, processed_quantity_kg=100,
                                 recovered_quantity_kg=80, residual_quantity_kg=30)   # 110 > 100
        assert exc.value.status_code == 422 and exc.value.code == "INVALID_QUANTITY"
        # rejected, not silently clamped: no row was created
        assert db.scalars(select(ProcessingRecord.id).where(ProcessingRecord.digital_load_id == "DL-1001")).first() is None


def test_negative_quantity_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        for kwargs in [dict(recovered_quantity_kg=-1), dict(residual_quantity_kg=-1)]:
            with pytest.raises(ServiceError) as exc:
                svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                     processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=100, **kwargs)
            assert exc.value.status_code == 422 and exc.value.code == "INVALID_QUANTITY"


# ================================================================ 4. state transitions
def test_valid_state_transition_in_progress_to_completed():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        p = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()
        p2 = svc.complete_processing(db, fac1, p.id)
        db.commit()
        assert p2.status == ProcessingStatus.COMPLETED and p2.completed_at is not None


def test_invalid_state_transition_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        p = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        svc.complete_processing(db, fac1, p.id)
        db.commit()
        with pytest.raises(ServiceError) as exc:      # COMPLETED -> COMPLETED again
            svc.complete_processing(db, fac1, p.id)
        assert exc.value.status_code == 409 and exc.value.code == "INVALID_PROCESSING_STATE"
        with pytest.raises(ServiceError) as exc2:      # COMPLETED -> CANCELLED
            svc.cancel_processing(db, fac1, p.id, "changed my mind")
        assert exc2.value.status_code == 409 and exc2.value.code == "INVALID_PROCESSING_STATE"


def test_cancel_processing_valid_transition_and_reason_required():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        p = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()
        with pytest.raises(ServiceError) as exc:
            svc.cancel_processing(db, fac1, p.id, "short")   # < 10 chars
        assert exc.value.status_code == 422 and exc.value.code == "REASON_REQUIRED"
        p2 = svc.cancel_processing(db, fac1, p.id, "Wrong facility selected by mistake")
        db.commit()
        assert p2.status == ProcessingStatus.CANCELLED and "Wrong facility" in p2.notes


# ================================================================ 5/7. idempotency / duplicate protection
def test_duplicate_open_processing_blocked():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                             processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()
        with pytest.raises(ServiceError) as exc:
            svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.RECYCLING, processed_quantity_kg=468)
        assert exc.value.status_code == 409 and exc.value.code == "PROCESSING_ALREADY_OPEN"
        assert db.scalars(select(ProcessingRecord).where(ProcessingRecord.digital_load_id == "DL-1001")).all().__len__() == 1


def test_new_processing_allowed_after_previous_one_closed():
    """Not a required test but confirms the partial unique index behaves as designed: CANCELLED/COMPLETED records
    do not block a new one."""
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        p1 = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                  processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()
        svc.cancel_processing(db, fac1, p1.id, "Wrong method selected initially")
        db.commit()
        p2 = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.RECYCLABLE,
                                  processing_method=ProcessingMethod.RECYCLING, processed_quantity_kg=468)
        db.commit()
        assert p2.id != p1.id and p2.status == ProcessingStatus.IN_PROGRESS


# ================================================================ 6. authorization
def test_unauthorized_citizen_blocked():
    with SessionLocal() as db:
        citizen = get_user(db, "citizen1")
        with pytest.raises(ServiceError) as exc:
            svc.start_processing(db, citizen, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"


def test_unauthorized_worker_blocked():
    with SessionLocal() as db:
        worker = get_user(db, "worker1")
        with pytest.raises(ServiceError) as exc:
            svc.start_processing(db, worker, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"


def test_municipal_admin_is_blocked():
    with SessionLocal() as db:
        admin = get_user(db, "admin1")
        with pytest.raises(ServiceError) as exc:
            svc.start_processing(db, admin, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"


# ================================================================ 8/9/10/11. hash-chain integration
def test_hash_chain_event_created_on_start_and_complete():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        before = len(list_events(db, "DL-1001"))
        p = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()
        events = list_events(db, "DL-1001")
        assert len(events) == before + 1
        started = events[-1]
        assert started.event_type == "PROCESSING_STARTED"
        assert started.payload_json["processing_record_id"] == p.id
        assert started.payload_json["processed_quantity_kg"] == 468

        svc.complete_processing(db, fac1, p.id)
        db.commit()
        events2 = list_events(db, "DL-1001")
        assert len(events2) == before + 2
        completed = events2[-1]
        assert completed.event_type == "PROCESSING_COMPLETED"
        assert completed.payload_json["processing_record_id"] == p.id


def test_hash_chain_event_created_on_cancel():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        p = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()
        svc.cancel_processing(db, fac1, p.id, "Wrong facility selected by mistake")
        db.commit()
        events = list_events(db, "DL-1001")
        assert events[-1].event_type == "PROCESSING_CANCELLED"
        assert events[-1].payload_json["processing_record_id"] == p.id


def test_processing_record_event_id_populated():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        p = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()
        assert p.event_id is not None
        started_event = list_events(db, "DL-1001")[-1]
        assert p.event_id == started_event.id

        svc.complete_processing(db, fac1, p.id)
        db.commit()
        completed_event = list_events(db, "DL-1001")[-1]
        assert p.event_id == completed_event.id   # updated to point at the latest (COMPLETED) event


def test_chain_remains_verifiable_after_processing_events():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        assert verify_chain(db, "DL-1001")["valid"] is True    # baseline, before any Phase 3 activity

        p1 = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                  processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()
        assert verify_chain(db, "DL-1001")["valid"] is True

        svc.cancel_processing(db, fac1, p1.id, "Wrong facility selected by mistake")
        db.commit()
        assert verify_chain(db, "DL-1001")["valid"] is True

        p2 = svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.RECYCLABLE,
                                  processing_method=ProcessingMethod.RECYCLING, processed_quantity_kg=468,
                                  recovered_quantity_kg=400, residual_quantity_kg=50)
        db.commit()
        svc.complete_processing(db, fac1, p2.id)
        db.commit()
        v = verify_chain(db, "DL-1001")
        assert v["valid"] is True and v["total_events"] >= 4   # >= the 3 Phase 3 events + at least 1 pre-existing


# ================================================================ Step 5: facility scoping
def test_facility_user_cannot_process_at_another_facility():
    with SessionLocal() as db:
        fac2 = get_user(db, "facility2")   # facility2's own facility_id is 2
        with pytest.raises(ServiceError) as exc:
            svc.start_processing(db, fac2, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        assert exc.value.status_code == 403 and exc.value.code == "FACILITY_SCOPE_VIOLATION"
        # but CAN process at their own facility
        p = svc.start_processing(db, fac2, "DL-1001", facility_id=2, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()
        assert p.facility_id == 2


def test_municipal_admin_blocked_from_processing_mutation():
    with SessionLocal() as db:
        admin = get_user(db, "admin1")
        with pytest.raises(ServiceError) as exc:
            svc.start_processing(db, admin, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                 processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"
