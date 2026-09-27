"""Phase 3, Step 4 - disposal exception service tests. Pure service-layer tests: no HTTP client, no
router (none exists yet for this step) - calls app.disposal_exception directly against a real SessionLocal.
"""
import pytest
from sqlalchemy import select

from app import disposal_exception as svc
from app import final_disposition as fd_svc
from app import handoff as ho_svc
from app import processing as proc_svc
from app.db import SessionLocal
from app.errors import ServiceError
from app.hashchain import list_events, verify_chain
from app.models import DispositionType, DisposalException, DisposalExceptionStatus, HandoffStatus, ProcessingMethod, User, WasteStream


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


REASON = "Destination facility refused the load on arrival"


# ================================================================ CREATION
def test_valid_exception_triggered_by_processing_record():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id,
                                           original_destination_facility_id=2, reason=REASON)
        db.commit()
        assert de.id is not None
        assert de.digital_load_id == "DL-1001"
        assert de.source_processing_record_id == pr.id and de.source_handoff_id is None
        assert de.original_destination_facility_id == 2
        assert de.reason == REASON
        assert de.status == DisposalExceptionStatus.RAISED
        assert de.raised_by_user_id == fac1.id


def test_valid_exception_triggered_by_handoff():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h = completed_handoff(db, fac1, pr, waste_stream=WasteStream.RECOVERED, quantity_kg=350, destination_facility_id=2)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_handoff_id=h.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        assert de.source_handoff_id == h.id and de.source_processing_record_id is None
        assert de.status == DisposalExceptionStatus.RAISED


def test_missing_trigger_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        with pytest.raises(ServiceError) as exc:
            svc.create_disposal_exception(db, fac1, "DL-1001", original_destination_facility_id=2, reason=REASON)
        assert exc.value.status_code == 422 and exc.value.code == "TRIGGER_REQUIRED"


def test_both_triggers_supplied_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h = completed_handoff(db, fac1, pr, quantity_kg=100)
        with pytest.raises(ServiceError) as exc:
            svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, source_handoff_id=h.id,
                                          original_destination_facility_id=2, reason=REASON)
        assert exc.value.status_code == 422 and exc.value.code == "TRIGGER_REQUIRED"


def test_trigger_from_another_load_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        # settle DL-1002 so it's processable, then build a processing record on IT, but raise the
        # exception against DL-1001 - the trigger belongs to the wrong load.
        from app import resolution
        from app.models import DiscrepancyEvent
        dd = db.execute(select(DiscrepancyEvent).where(DiscrepancyEvent.load_id == "DL-1002")).scalar_one()
        resolution.add_evidence(db, dd.id, "facility:test", "Weighbridge slip shows 390 kg", "slip.jpg")
        resolution.corroborate(db, dd.id, "facility:test", 385, None, "AUD-07")
        resolution.investigate(db, dd.id, "facility:test", "Check transfer point")
        resolution.resolve(db, dd.id, "facility:test", "Spillage at transfer point", "PROCESS")
        resolution.close(db, dd.id, "facility:test", "Closed")
        db.commit()
        other_pr = completed_processing_record(db, fac1, load_id="DL-1002", processed_quantity_kg=390, recovered_quantity_kg=200, residual_quantity_kg=100)
        with pytest.raises(ServiceError) as exc:
            svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=other_pr.id,
                                          original_destination_facility_id=2, reason=REASON)
        assert exc.value.status_code == 409 and exc.value.code == "TRIGGER_LOAD_MISMATCH"


def test_invalid_trigger_state_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        p = proc_svc.start_processing(db, fac1, "DL-1001", facility_id=1, waste_stream=WasteStream.MIXED,
                                      processing_method=ProcessingMethod.LANDFILL, processed_quantity_kg=468)
        db.commit()                                    # still IN_PROGRESS, not COMPLETED
        with pytest.raises(ServiceError) as exc:
            svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=p.id,
                                          original_destination_facility_id=2, reason=REASON)
        assert exc.value.status_code == 409 and exc.value.code == "PROCESSING_NOT_COMPLETED"


def test_empty_invalid_reason_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        with pytest.raises(ServiceError) as exc:
            svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id,
                                          original_destination_facility_id=2, reason="too short")
        assert exc.value.status_code == 422 and exc.value.code == "REASON_REQUIRED"
        with pytest.raises(ServiceError) as exc2:
            svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id,
                                          original_destination_facility_id=2, reason="   ")
        assert exc2.value.status_code == 422 and exc2.value.code == "REASON_REQUIRED"


def test_unauthorized_user_rejected_on_creation():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        citizen = get_user(db, "citizen1")
        with pytest.raises(ServiceError) as exc:
            svc.create_disposal_exception(db, citizen, "DL-1001", source_processing_record_id=pr.id,
                                          original_destination_facility_id=2, reason=REASON)
        assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"


def test_duplicate_open_exception_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        with pytest.raises(ServiceError) as exc:
            svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=3, reason=REASON)
        assert exc.value.status_code == 409 and exc.value.code == "EXCEPTION_ALREADY_OPEN"
        assert len(db.scalars(select(DisposalException).where(DisposalException.digital_load_id == "DL-1001")).all()) == 1


# ================================================================ AUTHORIZATION
def test_valid_alternative_facility_authorized():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        de2 = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                     waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        db.commit()
        assert de2.status == DisposalExceptionStatus.AUTHORIZED
        assert de2.alternative_destination_facility_id == 3
        assert de2.authorized_by_user_id == fac1.id and de2.authorized_at is not None
        assert de2.resulting_handoff_id is not None


def test_nonexistent_alternative_facility_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        with pytest.raises(ServiceError) as exc:
            svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=999, source_facility_id=1,
                                                   waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        assert exc.value.status_code == 404 and exc.value.code == "FACILITY_NOT_FOUND"


def test_unauthorized_user_rejected_on_authorization():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        worker = get_user(db, "worker1")
        with pytest.raises(ServiceError) as exc:
            svc.authorize_alternative_destination(db, worker, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                   waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        assert exc.value.status_code == 403 and exc.value.code == "FORBIDDEN"


def test_authorization_in_wrong_state_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                              waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        db.commit()
        with pytest.raises(ServiceError) as exc:        # AUTHORIZED -> authorize again
            svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=2, source_facility_id=1,
                                                   waste_stream=WasteStream.RESIDUAL, quantity_kg=150)
        assert exc.value.status_code == 409 and exc.value.code == "INVALID_EXCEPTION_STATE"


def test_original_destination_as_alternative_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        with pytest.raises(ServiceError) as exc:
            svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=2, source_facility_id=1,
                                                   waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        assert exc.value.status_code == 422 and exc.value.code == "SAME_AS_ORIGINAL_DESTINATION"


def test_waste_stream_mismatch_for_handoff_trigger_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        h = completed_handoff(db, fac1, pr, waste_stream=WasteStream.RECOVERED, quantity_kg=350, destination_facility_id=2)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_handoff_id=h.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        with pytest.raises(ServiceError) as exc:        # trying to reroute as RESIDUAL when the trigger handoff was RECOVERED
            svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=2,
                                                   waste_stream=WasteStream.RESIDUAL, quantity_kg=350)
        assert exc.value.status_code == 422 and exc.value.code == "WASTE_STREAM_MISMATCH"


# ================================================================ RESULTING HANDOFF
def test_resulting_handoff_created_through_existing_handoff_service():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        de2 = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                     waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        db.commit()
        from app.models import Handoff
        h = db.get(Handoff, de2.resulting_handoff_id)
        assert h is not None
        assert h.digital_load_id == "DL-1001"
        assert h.processing_record_id == pr.id
        assert h.destination_facility_id == 3 and h.source_facility_id == 1
        assert h.quantity_kg == 350 and h.waste_stream == WasteStream.RECOVERED
        assert h.status == HandoffStatus.PENDING   # normal handoff lifecycle, unaffected


def test_exception_resulting_handoff_id_populated():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        assert de.resulting_handoff_id is None
        de2 = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                     waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        db.commit()
        assert de2.resulting_handoff_id is not None


def test_quantity_over_available_balance_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1, recovered_quantity_kg=350, residual_quantity_kg=150)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        with pytest.raises(ServiceError) as exc:        # only 350 kg RECOVERED exists, ever
            svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                   waste_stream=WasteStream.RECOVERED, quantity_kg=351)
        assert exc.value.status_code == 422 and exc.value.code == "QUANTITY_EXCEEDS_AVAILABLE"
        # and the exception must NOT have been left half-authorized by the failed attempt
        db.rollback()
        de_check = db.get(DisposalException, de.id)
        assert de_check.status == DisposalExceptionStatus.RAISED and de_check.resulting_handoff_id is None


def test_exception_workflow_does_not_create_new_waste_quantity():
    """The core Section 10 guarantee: rerouting a HANDOFF-triggered exception's material must use no more
    than that original handoff's own quantity - it must not appear to "free up" extra kg."""
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1, recovered_quantity_kg=350, residual_quantity_kg=150)
        original_h = completed_handoff(db, fac1, pr, waste_stream=WasteStream.RECOVERED, quantity_kg=350, destination_facility_id=2)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_handoff_id=original_h.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        # exactly 350 kg (the original handoff's own quantity) is authorizable...
        de2 = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=2,
                                                     waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        db.commit()
        assert de2.resulting_handoff_id is not None
        # ...and the RESIDUAL stream (never touched by this exception) still has exactly its own 150 kg -
        # no cross-contamination, no phantom extra quantity anywhere.
        assert ho_svc.available_to_hand_off(db, pr.id, WasteStream.RESIDUAL) == 150
        assert ho_svc.available_to_hand_off(db, pr.id, WasteStream.RECOVERED) == 0   # fully reallocated, not doubled


# ================================================================ FULL EXCEPTION PATH
def test_full_exception_path_processing_to_final_disposition():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1, recovered_quantity_kg=350, residual_quantity_kg=150)

        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        de = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                    waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        db.commit()

        from app.models import Handoff
        h = db.get(Handoff, de.resulting_handoff_id)
        h = ho_svc.complete_handoff(db, fac1, h.id)
        db.commit()

        de = svc.resolve_disposal_exception(db, fac1, de.id)
        db.commit()
        assert de.status == DisposalExceptionStatus.RESOLVED and de.resolved_at is not None

        final = fd_svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.RECYCLING, destination_facility_id=3,
                                                 quantity_kg=350, handoff_id=h.id)
        db.commit()
        assert final.status.name == "RECORDED" and final.quantity_kg == 350 and final.handoff_id == h.id


def test_resolve_requires_resulting_handoff_completed():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        de = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                    waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        db.commit()
        with pytest.raises(ServiceError) as exc:        # resulting handoff still PENDING
            svc.resolve_disposal_exception(db, fac1, de.id)
        assert exc.value.status_code == 409 and exc.value.code == "RESULTING_HANDOFF_NOT_COMPLETED"


# ================================================================ HASH CHAIN
def test_hash_chain_events_exist_through_full_path():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1, recovered_quantity_kg=350, residual_quantity_kg=150)
        before = len(list_events(db, "DL-1001"))

        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        de = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                    waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        db.commit()

        from app.models import Handoff
        h = db.get(Handoff, de.resulting_handoff_id)
        h = ho_svc.complete_handoff(db, fac1, h.id)
        db.commit()
        de = svc.resolve_disposal_exception(db, fac1, de.id)
        db.commit()
        final = fd_svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.RECYCLING, destination_facility_id=3,
                                                 quantity_kg=350, handoff_id=h.id)
        db.commit()

        events = list_events(db, "DL-1001")
        types = [e.event_type for e in events[before:]]
        assert types == [
            "DISPOSAL_EXCEPTION_CREATED", "DISPOSAL_EXCEPTION_AUTHORIZED", "HANDOFF_CREATED",
            "HANDOFF_COMPLETED", "DISPOSAL_EXCEPTION_RESOLVED", "FINAL_DISPOSITION_RECORDED",
        ]
        assert final.event_id == events[-1].id


def test_exception_event_id_populated():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        assert de.event_id is not None
        created_event = list_events(db, "DL-1001")[-1]
        assert de.event_id == created_event.id

        de2 = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                     waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        db.commit()
        # the AUTHORIZED event is appended before the resulting HANDOFF_CREATED event, so event_id is the
        # exception's own AUTHORIZED event, not the handoff's
        events = list_events(db, "DL-1001")
        authorized_idx = [i for i, e in enumerate(events) if e.event_type == "DISPOSAL_EXCEPTION_AUTHORIZED"][0]
        assert de2.event_id == events[authorized_idx].id
        assert events[authorized_idx + 1].event_type == "HANDOFF_CREATED"


def test_chain_remains_valid_through_full_exception_path():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1, recovered_quantity_kg=350, residual_quantity_kg=150)
        assert verify_chain(db, "DL-1001")["valid"] is True

        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        assert verify_chain(db, "DL-1001")["valid"] is True

        de = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                    waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        db.commit()
        assert verify_chain(db, "DL-1001")["valid"] is True

        from app.models import Handoff
        h = db.get(Handoff, de.resulting_handoff_id)
        ho_svc.complete_handoff(db, fac1, h.id)
        db.commit()
        svc.resolve_disposal_exception(db, fac1, de.id)
        db.commit()
        fd_svc.record_final_disposition(db, fac1, "DL-1001", disposition_type=DispositionType.RECYCLING, destination_facility_id=3,
                                        quantity_kg=350, handoff_id=h.id)
        db.commit()
        v = verify_chain(db, "DL-1001")
        assert v["valid"] is True and v["total_events"] >= 8   # processing(2) + exception path(6)


# ================================================================ STATE MACHINE
def test_raised_to_authorized_to_resolved_valid_transitions():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        assert de.status == DisposalExceptionStatus.RAISED
        db.commit()
        de = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                    waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        assert de.status == DisposalExceptionStatus.AUTHORIZED
        db.commit()
        from app.models import Handoff
        h = db.get(Handoff, de.resulting_handoff_id)
        ho_svc.complete_handoff(db, fac1, h.id)
        db.commit()
        de = svc.resolve_disposal_exception(db, fac1, de.id)
        assert de.status == DisposalExceptionStatus.RESOLVED
        db.commit()


def test_resolve_from_raised_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        db.commit()
        with pytest.raises(ServiceError) as exc:        # RAISED -> RESOLVED directly, skipping AUTHORIZED
            svc.resolve_disposal_exception(db, fac1, de.id)
        assert exc.value.status_code == 409 and exc.value.code == "INVALID_EXCEPTION_STATE"


def test_resolve_twice_rejected():
    with SessionLocal() as db:
        fac1 = get_user(db, "facility1")
        pr = completed_processing_record(db, fac1)
        de = svc.create_disposal_exception(db, fac1, "DL-1001", source_processing_record_id=pr.id, original_destination_facility_id=2, reason=REASON)
        de = svc.authorize_alternative_destination(db, fac1, de.id, alternative_destination_facility_id=3, source_facility_id=1,
                                                    waste_stream=WasteStream.RECOVERED, quantity_kg=350)
        from app.models import Handoff
        h = db.get(Handoff, de.resulting_handoff_id)
        ho_svc.complete_handoff(db, fac1, h.id)
        de = svc.resolve_disposal_exception(db, fac1, de.id)
        db.commit()
        with pytest.raises(ServiceError) as exc:
            svc.resolve_disposal_exception(db, fac1, de.id)
        assert exc.value.status_code == 409 and exc.value.code == "INVALID_EXCEPTION_STATE"
