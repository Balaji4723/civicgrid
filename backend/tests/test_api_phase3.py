"""Step 5 - API integration tests for the Phase 3 endpoints (processing, handoffs, final-dispositions,
disposal-exceptions, /loads/{id}/timeline). HTTP-level, using the TestClient + login() pattern established
in test_core.py - these exercise the routers, not just the service layer (already covered by
test_processing.py / test_handoff.py / test_final_disposition.py / test_disposal_exception.py).
"""
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import login


def d_id(client, headers, load_id):
    return client.get(f"/loads/{load_id}", headers=headers).json()["discrepancies"][0]["id"]


def settle_dl1002(client, verifier=None):
    """Same sequence as test_core.py's test_full_walk_flagged_to_closed, over HTTP, so DL-1002 becomes SETTLED."""
    if verifier is None:
        verifier = login(client, "facility2")
    d = d_id(client, verifier, "DL-1002")
    for action, body in [
        ("add-evidence", {"note": "Weighbridge slip shows 390 kg", "evidence_ref": "slip.jpg"}),
        ("corroborate", {"audit_quantity": 385, "auditor": "AUD-07"}),
        ("investigate", {"note": "Check transfer point"}),
        ("resolve", {"finding": "Spillage at transfer point", "attributed_to": "PROCESS"}),
        ("close", {"note": "Closed"}),
    ]:
        r = client.post(f"/discrepancy/{d}/{action}", json=body, headers=verifier)
        assert r.status_code == 200, r.text


def start_processing(client, facility=None, load_id="DL-1001", **overrides):
    if facility is None:
        facility = login(client, "facility_ops")
    body = {"load_id": load_id, "facility_id": 1, "waste_stream": "MIXED", "processing_method": "MATERIAL_RECOVERY",
            "processed_quantity_kg": 500, "recovered_quantity_kg": 350, "residual_quantity_kg": 150}
    body.update(overrides)
    r = client.post("/processing", json=body, headers=facility)
    assert r.status_code == 200, r.text
    return r.json()


def complete_processing_http(client, facility, processing_id):
    r = client.post(f"/processing/{processing_id}/complete", headers=facility)
    assert r.status_code == 200, r.text
    return r.json()


# ================================================================ RBAC
def test_citizen_cannot_process(client):
    citizen = login(client, "citizen1")
    r = client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED",
                                         "processing_method": "LANDFILL", "processed_quantity_kg": 100}, headers=citizen)
    assert r.status_code == 403


def test_citizen_cannot_create_handoff(client):
    citizen = login(client, "citizen1")
    r = client.post("/handoffs", json={"load_id": "DL-1001", "processing_record_id": 1, "source_facility_id": 1,
                                       "destination_facility_id": 2, "waste_stream": "RECOVERED", "quantity_kg": 100}, headers=citizen)
    assert r.status_code == 403


def test_citizen_cannot_finalize_disposition(client):
    citizen = login(client, "citizen1")
    r = client.post("/final-dispositions", json={"load_id": "DL-1001", "disposition_type": "LANDFILL", "destination_facility_id": 2,
                                                  "quantity_kg": 100, "processing_record_id": 1}, headers=citizen)
    assert r.status_code == 403


def test_citizen_cannot_authorize_disposal_exception(client):
    citizen = login(client, "citizen1")
    r = client.post("/disposal-exceptions/1/authorize", json={"alternative_destination_facility_id": 3, "source_facility_id": 1,
                                                               "waste_stream": "RECOVERED", "quantity_kg": 100}, headers=citizen)
    assert r.status_code == 403


def test_worker_cannot_perform_facility_actions(client):
    worker = login(client, "worker1")
    assert client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED",
                                             "processing_method": "LANDFILL", "processed_quantity_kg": 100}, headers=worker).status_code == 403
    assert client.post("/handoffs", json={"load_id": "DL-1001", "processing_record_id": 1, "source_facility_id": 1,
                                          "destination_facility_id": 2, "waste_stream": "RECOVERED", "quantity_kg": 100}, headers=worker).status_code == 403


def test_facility_can_process_and_admin_blocked(client):
    fac_ops = login(client, "facility_ops")
    assert start_processing(client, fac_ops)["status"] == "IN_PROGRESS"
    fac_rec = login(client, "facility1")
    # Receiving operator is blocked from processing
    assert client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED",
                                             "processing_method": "LANDFILL", "processed_quantity_kg": 100}, headers=fac_rec).status_code == 403
    admin = login(client, "admin1")
    r = client.post("/processing", json={"load_id": "DL-1002", "facility_id": 1, "waste_stream": "MIXED",
                                         "processing_method": "LANDFILL", "processed_quantity_kg": 100}, headers=admin)
    assert r.status_code == 403


def test_facility_user_cannot_process_at_another_facility(client):
    """Facility-scoping fix: facility2 (facility_id=2, verifier) cannot start processing AS facility 1."""
    facility2 = login(client, "facility2")
    r = client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED",
                                         "processing_method": "LANDFILL", "processed_quantity_kg": 100}, headers=facility2)
    assert r.status_code == 403
    # MUNICIPAL_ADMIN is blocked from operational processing mutations
    admin = login(client, "admin1")
    r3 = client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED",
                                          "processing_method": "LANDFILL", "processed_quantity_kg": 100}, headers=admin)
    assert r3.status_code == 403


# ================================================================ PROCESSING endpoints
def test_processing_create_list_get_complete_cancel(client):
    facility = login(client, "facility_ops")

    p = start_processing(client, facility)
    pid = p["id"]
    assert p["digital_load_id"] == "DL-1001" and p["status"] == "IN_PROGRESS"

    listed = client.get("/processing", params={"load_id": "DL-1001"}, headers=facility).json()
    assert any(row["id"] == pid for row in listed)

    got = client.get(f"/processing/{pid}", headers=facility).json()
    assert got["id"] == pid

    completed = complete_processing_http(client, facility, pid)
    assert completed["status"] == "COMPLETED"

    assert client.post(f"/processing/{pid}/complete", headers=facility).status_code == 409   # invalid transition

    assert client.get("/processing/999999", headers=facility).status_code == 404


def test_processing_cancel_endpoint(client):
    facility = login(client, "facility_ops")
    p = start_processing(client, facility)
    r = client.post(f"/processing/{p['id']}/cancel", json={"reason": "short"}, headers=facility)
    assert r.status_code == 422   # reason too short (Pydantic min_length=10)
    r2 = client.post(f"/processing/{p['id']}/cancel", json={"reason": "Wrong facility selected initially"}, headers=facility)
    assert r2.status_code == 200 and r2.json()["status"] == "CANCELLED"


def test_processing_invalid_quantity_via_api(client):
    facility = login(client, "facility_ops")
    r = client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED",
                                         "processing_method": "LANDFILL", "processed_quantity_kg": 100,
                                         "recovered_quantity_kg": 80, "residual_quantity_kg": 30}, headers=facility)   # 110 > 100
    assert r.status_code == 422 and r.json()["detail"]["error"] == "INVALID_QUANTITY"

    r2 = client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED",
                                          "processing_method": "LANDFILL", "processed_quantity_kg": -5}, headers=facility)
    assert r2.status_code == 422   # Pydantic gt=0 catches this before the service layer


# ================================================================ HANDOFF endpoints
def test_handoff_create_list_get_complete_cancel(client):
    facility = login(client, "facility_ops")
    p = start_processing(client, facility)
    p = complete_processing_http(client, facility, p["id"])

    r = client.post("/handoffs", json={"load_id": "DL-1001", "processing_record_id": p["id"], "source_facility_id": 1,
                                       "destination_facility_id": 2, "waste_stream": "RECOVERED", "quantity_kg": 350}, headers=facility)
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["status"] == "PENDING" and h["quantity_kg"] == 350

    listed = client.get("/handoffs", params={"load_id": "DL-1001"}, headers=facility).json()
    assert any(row["id"] == h["id"] for row in listed)
    assert client.get(f"/handoffs/{h['id']}", headers=facility).json()["id"] == h["id"]
    assert client.get("/handoffs/999999", headers=facility).status_code == 404

    completed = client.post(f"/handoffs/{h['id']}/complete", headers=facility).json()
    assert completed["status"] == "COMPLETED"
    assert client.post(f"/handoffs/{h['id']}/complete", headers=facility).status_code == 409


def test_handoff_quantity_exceeds_available_via_api(client):
    facility = login(client, "facility_ops")
    p = start_processing(client, facility, recovered_quantity_kg=300, residual_quantity_kg=100, processed_quantity_kg=400)
    p = complete_processing_http(client, facility, p["id"])
    r = client.post("/handoffs", json={"load_id": "DL-1001", "processing_record_id": p["id"], "source_facility_id": 1,
                                       "destination_facility_id": 2, "waste_stream": "RECOVERED", "quantity_kg": 301}, headers=facility)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "QUANTITY_EXCEEDS_AVAILABLE"


# ================================================================ FINAL DISPOSITION endpoints
def test_final_disposition_create_list_get_verify_cancel(client):
    facility = login(client, "facility_ops")
    p = start_processing(client, facility)
    p = complete_processing_http(client, facility, p["id"])

    r = client.post("/final-dispositions", json={"load_id": "DL-1001", "disposition_type": "RECYCLING", "destination_facility_id": 2,
                                                  "quantity_kg": 350, "processing_record_id": p["id"]}, headers=facility)
    assert r.status_code == 200, r.text
    fd = r.json()
    assert fd["status"] == "RECORDED"

    listed = client.get("/final-dispositions", params={"load_id": "DL-1001"}, headers=facility).json()
    assert any(row["id"] == fd["id"] for row in listed)
    assert client.get(f"/final-dispositions/{fd['id']}", headers=facility).json()["id"] == fd["id"]
    assert client.get("/final-dispositions/999999", headers=facility).status_code == 404

    verified = client.post(f"/final-dispositions/{fd['id']}/verify", headers=facility).json()
    assert verified["status"] == "VERIFIED"
    assert client.post(f"/final-dispositions/{fd['id']}/verify", headers=facility).status_code == 409

    # a second disposition of the residual stream is a legitimate split
    fd2 = client.post("/final-dispositions", json={"load_id": "DL-1001", "disposition_type": "LANDFILL", "destination_facility_id": 3,
                                                    "quantity_kg": 150, "processing_record_id": p["id"]}, headers=facility)
    assert fd2.status_code == 200
    assert client.post(f"/final-dispositions/{fd2.json()['id']}/cancel", json={"reason": "Wrong destination facility"}, headers=facility).status_code == 200


def test_final_disposition_requires_exactly_one_source_via_api(client):
    facility = login(client, "facility_ops")
    r = client.post("/final-dispositions", json={"load_id": "DL-1001", "disposition_type": "LANDFILL", "destination_facility_id": 2, "quantity_kg": 100},
                    headers=facility)
    assert r.status_code == 422   # neither handoff_id nor processing_record_id - caught by the Pydantic model_validator


# ================================================================ DISPOSAL EXCEPTION endpoints
def test_disposal_exception_create_list_get_authorize_resolve(client):
    facility = login(client, "facility_ops")
    p = start_processing(client, facility)
    p = complete_processing_http(client, facility, p["id"])

    r = client.post("/disposal-exceptions", json={"load_id": "DL-1001", "source_processing_record_id": p["id"],
                                                   "original_destination_facility_id": 2, "reason": "Destination refused the load on arrival"},
                    headers=facility)
    assert r.status_code == 200, r.text
    de = r.json()
    assert de["status"] == "RAISED"

    listed = client.get("/disposal-exceptions", params={"load_id": "DL-1001"}, headers=facility).json()
    assert any(row["id"] == de["id"] for row in listed)
    assert client.get(f"/disposal-exceptions/{de['id']}", headers=facility).json()["id"] == de["id"]
    assert client.get("/disposal-exceptions/999999", headers=facility).status_code == 404

    auth_r = client.post(f"/disposal-exceptions/{de['id']}/authorize",
                         json={"alternative_destination_facility_id": 3, "source_facility_id": 1, "waste_stream": "RECOVERED", "quantity_kg": 350},
                         headers=facility)
    assert auth_r.status_code == 200, auth_r.text
    de2 = auth_r.json()
    assert de2["status"] == "AUTHORIZED" and de2["resulting_handoff_id"] is not None

    # resolve before the resulting handoff completes -> 409
    assert client.post(f"/disposal-exceptions/{de['id']}/resolve", headers=facility).status_code == 409

    complete_r = client.post(f"/handoffs/{de2['resulting_handoff_id']}/complete", headers=facility)
    assert complete_r.status_code == 200

    resolve_r = client.post(f"/disposal-exceptions/{de['id']}/resolve", headers=facility)
    assert resolve_r.status_code == 200 and resolve_r.json()["status"] == "RESOLVED"


def test_disposal_exception_requires_exactly_one_trigger_via_api(client):
    facility = login(client, "facility_ops")
    r = client.post("/disposal-exceptions", json={"load_id": "DL-1001", "original_destination_facility_id": 2, "reason": "Destination refused the load"},
                    headers=facility)
    assert r.status_code == 422   # neither trigger - caught by the Pydantic model_validator


# ================================================================ TIMELINE + INTEGRITY, COMPLETE WORKFLOWS
def test_normal_end_to_end_workflow_timeline_and_integrity(client):
    facility = login(client, "facility_ops")

    before = client.get("/loads/DL-1001/verify-integrity", headers=facility).json()
    assert before["valid"] is True

    p = start_processing(client, facility, recovered_quantity_kg=350, residual_quantity_kg=150, processed_quantity_kg=500)
    p = complete_processing_http(client, facility, p["id"])

    h = client.post("/handoffs", json={"load_id": "DL-1001", "processing_record_id": p["id"], "source_facility_id": 1,
                                       "destination_facility_id": 2, "waste_stream": "RECOVERED", "quantity_kg": 350}, headers=facility).json()
    h = client.post(f"/handoffs/{h['id']}/complete", headers=facility).json()

    fd = client.post("/final-dispositions", json={"load_id": "DL-1001", "disposition_type": "RECYCLING", "destination_facility_id": 2,
                                                   "quantity_kg": 350, "handoff_id": h["id"]}, headers=facility).json()
    fd = client.post(f"/final-dispositions/{fd['id']}/verify", headers=facility).json()
    assert fd["status"] == "VERIFIED"

    timeline = client.get("/loads/DL-1001/timeline", headers=facility).json()
    assert timeline["load_id"] == "DL-1001"
    # every record belongs to the same load
    assert all(row["digital_load_id"] == "DL-1001" for row in timeline["processing_records"] + timeline["handoffs"] + timeline["final_dispositions"])
    # statuses are correct
    assert timeline["processing_records"][-1]["status"] == "COMPLETED"
    assert timeline["handoffs"][-1]["status"] == "COMPLETED"
    assert timeline["final_dispositions"][-1]["status"] == "VERIFIED"
    # quantities are consistent across the chain: processed -> handed off -> disposed, all 350 kg for this stream
    assert timeline["processing_records"][-1]["recovered_quantity_kg"] == 350
    assert timeline["handoffs"][-1]["quantity_kg"] == 350
    assert timeline["final_dispositions"][-1]["quantity_kg"] == 350
    # event IDs are linked to real event_log rows present in the same timeline
    event_ids = {e["id"] for e in timeline["events"]}
    assert timeline["processing_records"][-1]["event_id"] in event_ids
    assert timeline["handoffs"][-1]["event_id"] in event_ids
    assert timeline["final_dispositions"][-1]["event_id"] in event_ids
    # chronological order: event log ids strictly increasing
    ids = [e["id"] for e in timeline["events"]]
    assert ids == sorted(ids)
    # expected event sequence for this exact normal journey (tail end - seed events precede these)
    types = [e["event_type"] for e in timeline["events"]]
    assert types[-6:] == ["PROCESSING_STARTED", "PROCESSING_COMPLETED", "HANDOFF_CREATED", "HANDOFF_COMPLETED",
                          "FINAL_DISPOSITION_RECORDED", "FINAL_DISPOSITION_VERIFIED"]

    after = client.get("/loads/DL-1001/verify-integrity", headers=facility).json()
    assert after["valid"] is True and after["broken_at_index"] is None
    assert after["total_events"] == before["total_events"] + 6


def test_exception_end_to_end_workflow_timeline_and_integrity(client):
    facility = login(client, "facility_ops")
    settle_dl1002(client)   # SETTLED, processable

    before = client.get("/loads/DL-1002/verify-integrity", headers=facility).json()
    assert before["valid"] is True

    p = start_processing(client, facility, load_id="DL-1002", recovered_quantity_kg=200, residual_quantity_kg=100, processed_quantity_kg=390)
    p = complete_processing_http(client, facility, p["id"])

    de = client.post("/disposal-exceptions", json={"load_id": "DL-1002", "source_processing_record_id": p["id"],
                                                    "original_destination_facility_id": 2, "reason": "Destination refused the load on arrival"},
                     headers=facility).json()
    de = client.post(f"/disposal-exceptions/{de['id']}/authorize",
                     json={"alternative_destination_facility_id": 3, "source_facility_id": 1, "waste_stream": "RECOVERED", "quantity_kg": 200},
                     headers=facility).json()
    assert de["status"] == "AUTHORIZED"
    resulting_handoff_id = de["resulting_handoff_id"]

    h = client.post(f"/handoffs/{resulting_handoff_id}/complete", headers=facility).json()
    assert h["status"] == "COMPLETED"

    de = client.post(f"/disposal-exceptions/{de['id']}/resolve", headers=facility).json()
    assert de["status"] == "RESOLVED"

    fd = client.post("/final-dispositions", json={"load_id": "DL-1002", "disposition_type": "RECYCLING", "destination_facility_id": 3,
                                                   "quantity_kg": 200, "handoff_id": resulting_handoff_id}, headers=facility).json()
    assert fd["status"] == "RECORDED"

    timeline = client.get("/loads/DL-1002/timeline", headers=facility).json()
    assert any(row["id"] == de["id"] and row["status"] == "RESOLVED" for row in timeline["disposal_exceptions"])
    types = [e["event_type"] for e in timeline["events"]]
    exc_start = types.index("DISPOSAL_EXCEPTION_CREATED")
    assert types[exc_start:] == ["DISPOSAL_EXCEPTION_CREATED", "DISPOSAL_EXCEPTION_AUTHORIZED", "HANDOFF_CREATED",
                                 "HANDOFF_COMPLETED", "DISPOSAL_EXCEPTION_RESOLVED", "FINAL_DISPOSITION_RECORDED"]

    # the exception did not create new waste: RESIDUAL stream (untouched by the exception) still shows its own 100 kg
    from app import handoff as ho_svc
    from app.db import SessionLocal
    from app.models import WasteStream
    with SessionLocal() as db:
        assert ho_svc.available_to_hand_off(db, p["id"], WasteStream.RESIDUAL) == 100
        assert ho_svc.available_to_hand_off(db, p["id"], WasteStream.RECOVERED) == 0   # fully reallocated, not doubled

    after = client.get("/loads/DL-1002/verify-integrity", headers=facility).json()
    assert after["valid"] is True and after["broken_at_index"] is None
    assert after["total_events"] == before["total_events"] + 8   # processing(2) + exception path(6)
