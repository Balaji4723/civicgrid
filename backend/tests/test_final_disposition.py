"""Phase 3, Step 3(D) - final disposition service tests. Pure service-layer tests: no HTTP client, no
router (none exists yet for this step) - calls app.final_disposition directly against a real SessionLocal.
"""
import pytest
from sqlalchemy import select

from app import final_disposition as svc
from app import handoff as ho_svc
from app import processing as proc_svc
from app.db import SessionLocal
from app.errors import ServiceError
from app.hashchain import list_events, verify_chain
from app.models import DispositionStatus, DispositionType, FinalDisposition, ProcessingMethod, User, WasteStream


def get_user(db, username):
    return db.execute(select(User).where(User.username == username)).scalar_one()


def completed_processing_record(db, user, load_id="DL-1001", *, facility_id=1, processed_quantity_kg=500,
                                recovered_quantity_kg=350, residual_quantity_kg=150):
    p = proc_svc.start_processing(db, user, load_id, facility_id=facility_id, waste_stream=WasteStream.MIXED,
                                  processing_method=ProcessingMethod.MATERIAL_RECOVERY, processed_quantity_kg=processed_quantity_kg,
                                  recovered_quantity_kg=recovered_quantity_kg, residual_quantity_kg=residual_quantity_kg)
    db.flush()
    return proc_svc.complete_processing(db, user, p.id)


def completed_handoff(db, user, pr, *, waste_stream=WasteStream.RECOVERED, quantity_kg=350, destination_facility_id=2):
    h = ho_svc.create_handoff(db, user, pr.digital_load_id, processing_record_id=pr.id, source_facility_id=1,
                              destination_facility_id=destination_facility_id, waste_stream=waste_stream, quantity_kg=quantity_kg)
    db.flush()
    return ho_svc.complete_handoff(db, user, h.id)


# ================================================================ 1. valid final disposition (from a handoff)
def test_valid_final_disposition_from_handoff():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h = completed_handoff(db, fac1, pr, waste_stream=WasteStream.RECOVERED, quantity_kg=350, destination_facility_id=2)
        fd = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.RECYCLING, destination_facility_id=2,
                                          quantity_kg=350, handoff_id=h.id)
        db.commit()
        assert fd.id is not None and fd.digital_load_id == "DL-1001"
        assert fd.handoff_id == h.id and fd.processing_record_id is None
        assert fd.disposition_type == DispositionType.RECYCLING and fd.destination_facility_id == 2
        assert fd.quantity_kg == 350 and fd.status == DispositionStatus.RECORDED
        assert fd.recorded_by_user_id == fac1.id


# ================================================================ 2. valid split of processed output (many-per-load)
def test_valid_split_of_processed_output_directly_from_processing_record():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1, recovered_quantity_kg=350, residual_quantity_kg=150)   # 500 total
        fd1 = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.RECYCLING, destination_facility_id=2,
                                           quantity_kg=350, processing_record_id=pr.id)
        db.commit()
        fd2 = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=3,
                                           quantity_kg=150, processing_record_id=pr.id)
        db.commit()
        assert fd1.id != fd2.id
        assert fd1.destination_facility_id == 2 and fd2.destination_facility_id == 3
        rows = db.scalars(select(FinalDisposition).where(FinalDisposition.digital_load_id == "DL-1001")).all()
        assert len(rows) == 2 and {r.quantity_kg for r in rows} == {350, 150}
        # fully allocated: a third disposition from the same processing record must be rejected
        with pytest.raises(ServiceError) as exc:
            svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.OTHER, destination_facility_id=2,
                                         quantity_kg=1, processing_record_id=pr.id)
        assert exc.value.code == "QUANTITY_EXCEEDS_AVAILABLE"


def test_multiple_final_dispositions_same_load_legitimate_split():
    """Explicit requirement: multiple FinalDisposition rows for the SAME load, sourced from the SAME
    processing record's two distinct output streams via two separate handoffs."""
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1, recovered_quantity_kg=350, residual_quantity_kg=150)
        h_recovered = completed_handoff(db, fac1, pr, waste_stream=WasteStream.RECOVERED, quantity_kg=350, destination_facility_id=2)
        fd1 = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.RECYCLING, destination_facility_id=2,
                                           quantity_kg=350, handoff_id=h_recovered.id)
        db.commit()
        h_residual = completed_handoff(db, fac1, pr, waste_stream=WasteStream.RESIDUAL, quantity_kg=150, destination_facility_id=3)
        fd2 = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=3,
                                           quantity_kg=150, handoff_id=h_residual.id)
        db.commit()
        rows = db.scalars(select(FinalDisposition).where(FinalDisposition.digital_load_id == "DL-1001").order_by(FinalDisposition.id)).all()
        assert len(rows) == 2
        assert rows[0].id == fd1.id and rows[1].id == fd2.id
        assert {r.disposition_type for r in rows} == {DispositionType.RECYCLING, DispositionType.LANDFILL}


# ================================================================ 3/4. quantity validation
def test_invalid_quantity_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        with pytest.raises(ServiceError) as exc:
            svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2,
                                         quantity_kg=0, processing_record_id=pr.id)
        assert exc.value.status_code == 422 and exc.value.code == "INVALID_QUANTITY"


def test_quantity_exceeding_available_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1, recovered_quantity_kg=350, residual_quantity_kg=150)   # 500 total
        with pytest.raises(ServiceError) as exc:
            svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2,
                                         quantity_kg=501, processing_record_id=pr.id)
        assert exc.value.status_code == 422 and exc.value.code == "QUANTITY_EXCEEDS_AVAILABLE"


# ================================================================ 5. invalid destination
def test_invalid_destination_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        with pytest.raises(ServiceError) as exc:
            svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=999,
                                         quantity_kg=100, processing_record_id=pr.id)
        assert exc.value.status_code == 404 and exc.value.code == "FACILITY_NOT_FOUND"


def test_source_required_exactly_one():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h = completed_handoff(db, fac1, pr)
        with pytest.raises(ServiceError) as exc:       # neither given
            svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2, quantity_kg=10)
        assert exc.value.code == "SOURCE_REQUIRED"
        with pytest.raises(ServiceError) as exc2:       # both given
            svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2, quantity_kg=10,
                                         handoff_id=h.id, processing_record_id=pr.id)
        assert exc2.value.code == "SOURCE_REQUIRED"


# ================================================================ 6. authorization
def test_unauthorized_citizen_blocked():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        citizen = get_user(db, "citizen1")
        with pytest.raises(ServiceError) as exc:
            svc.record_final_disposition(db, citizen, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2,
                                         quantity_kg=100, processing_record_id=pr.id)
        assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"


def test_unauthorized_worker_blocked():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        worker = get_user(db, "worker1")
        with pytest.raises(ServiceError) as exc:
            svc.record_final_disposition(db, worker, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2,
                                         quantity_kg=100, processing_record_id=pr.id)
        assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"


# ================================================================ 7/8. state transitions
def test_valid_state_transition_recorded_to_verified():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        fd = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2,
                                          quantity_kg=100, processing_record_id=pr.id)
        db.commit()
        fd2 = svc.verify_disposition(db, fac1, fd.id)
        db.commit()
        assert fd2.status == DispositionStatus.VERIFIED


def test_invalid_state_transition_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        fd = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2,
                                          quantity_kg=100, processing_record_id=pr.id)
        svc.verify_disposition(db, fac1, fd.id)
        db.commit()
        with pytest.raises(ServiceError) as exc:        # VERIFIED -> VERIFIED again
            svc.verify_disposition(db, fac1, fd.id)
        assert exc.value.status_code == 409 and exc.value.code == "INVALID_DISPOSITION_STATE"
        with pytest.raises(ServiceError) as exc2:        # VERIFIED -> CANCELLED
            svc.cancel_disposition(db, fac1, fd.id, "changed my mind")
        assert exc2.value.status_code == 409 and exc2.value.code == "INVALID_DISPOSITION_STATE"


def test_cancel_disposition_valid_transition_and_reason_required():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        fd = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2,
                                          quantity_kg=100, processing_record_id=pr.id)
        db.commit()
        with pytest.raises(ServiceError) as exc:
            svc.cancel_disposition(db, fac1, fd.id, "short")
        assert exc.value.status_code == 422 and exc.value.code == "REASON_REQUIRED"
        fd2 = svc.cancel_disposition(db, fac1, fd.id, "Wrong destination facility selected")
        db.commit()
        assert fd2.status == DispositionStatus.CANCELLED
        # cancelled quantity is released back to the available balance
        assert svc.available_from_processing_record(db, pr.id) == 500


# ================================================================ hash-chain integration
def test_hash_chain_event_created_on_record_and_verify():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        before = len(list_events(db, "DL-1001"))
        fd = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2,
                                          quantity_kg=100, processing_record_id=pr.id)
        db.commit()
        events = list_events(db, "DL-1001")
        assert len(events) == before + 1
        assert events[-1].event_type == "FINAL_DISPOSITION_RECORDED" and events[-1].payload_json["final_disposition_id"] == fd.id

        svc.verify_disposition(db, fac1, fd.id)
        db.commit()
        events2 = list_events(db, "DL-1001")
        assert len(events2) == before + 2
        assert events2[-1].event_type == "FINAL_DISPOSITION_VERIFIED" and events2[-1].payload_json["final_disposition_id"] == fd.id


def test_hash_chain_event_created_on_cancel():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        fd = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2,
                                          quantity_kg=100, processing_record_id=pr.id)
        db.commit()
        svc.cancel_disposition(db, fac1, fd.id, "Wrong destination facility selected")
        db.commit()
        events = list_events(db, "DL-1001")
        assert events[-1].event_type == "FINAL_DISPOSITION_CANCELLED" and events[-1].payload_json["final_disposition_id"] == fd.id


def test_final_disposition_event_id_populated():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        fd = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=2,
                                          quantity_kg=100, processing_record_id=pr.id)
        db.commit()
        assert fd.event_id is not None
        recorded_event = list_events(db, "DL-1001")[-1]
        assert fd.event_id == recorded_event.id

        svc.verify_disposition(db, fac1, fd.id)
        db.commit()
        verified_event = list_events(db, "DL-1001")[-1]
        assert fd.event_id == verified_event.id


def test_chain_remains_valid_after_final_disposition_events():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1, recovered_quantity_kg=350, residual_quantity_kg=150)
        assert verify_chain(db, "DL-1001")["valid"] is True

        fd1 = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.RECYCLING, destination_facility_id=2,
                                           quantity_kg=350, processing_record_id=pr.id)
        db.commit()
        assert verify_chain(db, "DL-1001")["valid"] is True

        svc.verify_disposition(db, fac1, fd1.id)
        db.commit()
        assert verify_chain(db, "DL-1001")["valid"] is True

        fd2 = svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.LANDFILL, destination_facility_id=3,
                                           quantity_kg=150, processing_record_id=pr.id)
        db.commit()
        svc.cancel_disposition(db, fac1, fd2.id, "Landfill site was unexpectedly closed")
        db.commit()
        v = verify_chain(db, "DL-1001")
        assert v["valid"] is True and v["total_events"] >= 5   # processing start+complete + 3 disposition events
