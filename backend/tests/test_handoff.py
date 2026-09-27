"""Phase 3, Step 3(A) - handoff service tests. Pure service-layer tests: no HTTP client, no router (none
exists yet for this step) - calls app.handoff directly against a real SessionLocal.

Seeded loads used here (see app/seed.py): DL-1001 is VERIFIED (clean load) - used as the base for a
COMPLETED processing record fixture, since a handoff always requires one.
"""
import pytest
from sqlalchemy import select

from app import handoff as svc
from app import processing as proc_svc
from app.db import SessionLocal
from app.errors import ServiceError
from app.hashchain import list_events, verify_chain
from app.models import Handoff, HandoffStatus, ProcessingMethod, ProcessingStatus, User, WasteStream


def get_user(db, username):
    return db.execute(select(User).where(User.username == username)).scalar_one()


def completed_processing_record(db, user, load_id="DL-1001", *, facility_id=1, processed_quantity_kg=468,
                                recovered_quantity_kg=300, residual_quantity_kg=100):
    p = proc_svc.start_processing(db, user, load_id, facility_id=facility_id, waste_stream=WasteStream.MIXED,
                                  processing_method=ProcessingMethod.MATERIAL_RECOVERY, processed_quantity_kg=processed_quantity_kg,
                                  recovered_quantity_kg=recovered_quantity_kg, residual_quantity_kg=residual_quantity_kg)
    db.flush()
    return proc_svc.complete_processing(db, user, p.id)


# ================================================================ 1. valid handoff / preconditions
def test_valid_handoff():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h = svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=200)
        db.commit()
        assert h.id is not None
        assert h.digital_load_id == "DL-1001" and h.processing_record_id == pr.id
        assert h.source_facility_id == 1 and h.destination_facility_id == 2
        assert h.quantity_kg == 200 and h.waste_stream == WasteStream.RECOVERED
        assert h.status == HandoffStatus.PENDING
        assert h.recorded_by_user_id == fac1.id


def test_processing_workflow_must_exist_and_be_completed():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        with pytest.raises(ServiceError) as exc:      # nonexistent processing record
            svc.create_handoff(db, fac1, "DL-1001", processing_record_id=999999, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=100)
        assert exc.value.status_code == 404 and exc.value.code == "PROCESSING_RECORD_NOT_FOUND"

        p = proc_svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                      processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()                                   # still IN_PROGRESS, not COMPLETED
        with pytest.raises(ServiceError) as exc2:
            svc.create_handoff(db, fac1, "DL-1001", processing_record_id=p.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=100)
        assert exc2.value.status_code == 409 and exc2.value.code == "PROCESSING_NOT_COMPLETED"


# ================================================================ 2/3. facility existence
def test_nonexistent_source_facility_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        with pytest.raises(ServiceError) as exc:
            svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=999, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=100)
        assert exc.value.status_code == 404 and exc.value.code == "FACILITY_NOT_FOUND"


def test_nonexistent_destination_facility_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        with pytest.raises(ServiceError) as exc:
            svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=999,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=100)
        assert exc.value.status_code == 404 and exc.value.code == "FACILITY_NOT_FOUND"


def test_source_equals_destination_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        with pytest.raises(ServiceError) as exc:
            svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=1,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=100)
        assert exc.value.status_code == 422 and exc.value.code == "SAME_FACILITY"


# ================================================================ 4/5. quantity validation
def test_invalid_quantity_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        with pytest.raises(ServiceError) as exc:
            svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=0)
        assert exc.value.status_code == 422 and exc.value.code == "INVALID_QUANTITY"


def test_quantity_exceeding_available_processing_output_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1, recovered_quantity_kg=300, residual_quantity_kg=100)
        with pytest.raises(ServiceError) as exc:      # only 300 kg RECOVERED is available
            svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=301)
        assert exc.value.status_code == 422 and exc.value.code == "QUANTITY_EXCEEDS_AVAILABLE"
        # a second handoff drawing from the SAME stream after the first is already open must also respect the remaining balance
        svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                           waste_stream=WasteStream.RECOVERED, quantity_kg=300)
        db.commit()
        assert svc.available_to_hand_off(db, pr.id, WasteStream.RECOVERED) == 0


# ================================================================ 6. authorization
def test_unauthorized_citizen_blocked():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        citizen = get_user(db, "citizen1")
        with pytest.raises(ServiceError) as exc:
            svc.create_handoff(db, citizen, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=100)
        assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"


def test_unauthorized_worker_blocked():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        worker = get_user(db, "worker1")
        with pytest.raises(ServiceError) as exc:
            svc.create_handoff(db, worker, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=100)
        assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"


# ================================================================ state transitions
def test_valid_state_transition_pending_to_completed():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h = svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=200)
        db.commit()
        h2 = svc.complete_handoff(db, fac1, h.id)
        db.commit()
        assert h2.status == HandoffStatus.COMPLETED


def test_invalid_state_transition_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h = svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=200)
        svc.complete_handoff(db, fac1, h.id)
        db.commit()
        with pytest.raises(ServiceError) as exc:       # COMPLETED -> COMPLETED again
            svc.complete_handoff(db, fac1, h.id)
        assert exc.value.status_code == 409 and exc.value.code == "INVALID_HANDOFF_STATE"
        with pytest.raises(ServiceError) as exc2:       # COMPLETED -> CANCELLED
            svc.cancel_handoff(db, fac1, h.id, "changed my mind")
        assert exc2.value.status_code == 409 and exc2.value.code == "INVALID_HANDOFF_STATE"


# ================================================================ 8/9. duplicate / idempotency
def test_duplicate_open_handoff_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                           waste_stream=WasteStream.RECOVERED, quantity_kg=100)
        db.commit()
        with pytest.raises(ServiceError) as exc:
            svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RESIDUAL, quantity_kg=50)
        assert exc.value.status_code == 409 and exc.value.code == "HANDOFF_ALREADY_OPEN"
        assert len(db.scalars(select(Handoff).where(Handoff.digital_load_id == "DL-1001")).all()) == 1


def test_new_handoff_allowed_after_previous_one_closed():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h1 = svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                                waste_stream=WasteStream.RECOVERED, quantity_kg=100)
        db.commit()
        svc.cancel_handoff(db, fac1, h1.id, "Wrong destination selected initially")
        db.commit()
        h2 = svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=3,
                                waste_stream=WasteStream.RESIDUAL, quantity_kg=50)
        db.commit()
        assert h2.id != h1.id and h2.status == HandoffStatus.PENDING


# ================================================================ hash-chain integration
def test_hash_chain_event_created_on_create_and_complete():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        before = len(list_events(db, "DL-1001"))
        h = svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=200)
        db.commit()
        events = list_events(db, "DL-1001")
        assert len(events) == before + 1
        assert events[-1].event_type == "HANDOFF_CREATED" and events[-1].payload_json["handoff_id"] == h.id

        svc.complete_handoff(db, fac1, h.id)
        db.commit()
        events2 = list_events(db, "DL-1001")
        assert len(events2) == before + 2
        assert events2[-1].event_type == "HANDOFF_COMPLETED" and events2[-1].payload_json["handoff_id"] == h.id


def test_hash_chain_event_created_on_cancel():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h = svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=200)
        db.commit()
        svc.cancel_handoff(db, fac1, h.id, "Wrong destination selected initially")
        db.commit()
        events = list_events(db, "DL-1001")
        assert events[-1].event_type == "HANDOFF_CANCELLED" and events[-1].payload_json["handoff_id"] == h.id


def test_handoff_event_id_populated():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h = svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                               waste_stream=WasteStream.RECOVERED, quantity_kg=200)
        db.commit()
        assert h.event_id is not None
        created_event = list_events(db, "DL-1001")[-1]
        assert h.event_id == created_event.id

        svc.complete_handoff(db, fac1, h.id)
        db.commit()
        completed_event = list_events(db, "DL-1001")[-1]
        assert h.event_id == completed_event.id


def test_chain_remains_valid_after_handoff_events():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        assert verify_chain(db, "DL-1001")["valid"] is True

        h1 = svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=2,
                                waste_stream=WasteStream.RECOVERED, quantity_kg=200)
        db.commit()
        assert verify_chain(db, "DL-1001")["valid"] is True

        svc.cancel_handoff(db, fac1, h1.id, "Wrong destination selected initially")
        db.commit()
        assert verify_chain(db, "DL-1001")["valid"] is True

        h2 = svc.create_handoff(db, fac1, "DL-1001", processing_record_id=pr.id, source_facility_id=1, destination_facility_id=3,
                                waste_stream=WasteStream.RESIDUAL, quantity_kg=50)
        db.commit()
        svc.complete_handoff(db, fac1, h2.id)
        db.commit()
        v = verify_chain(db, "DL-1001")
        assert v["valid"] is True and v["total_events"] >= 5   # processing start+complete + 3 handoff events
