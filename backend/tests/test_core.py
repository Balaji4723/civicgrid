import pytest
from sqlalchemy import select

from app import crosscheck
from app.db import SessionLocal
from app.models import EventLog
from tests.conftest import login

LOAD = "DL-1002"  # main demo path: seeded at FLAGGED


def disc_id(client, headers, load_id):
    return client.get(f"/loads/{load_id}", headers=headers).json()["discrepancies"][0]["id"]


# ------------------------------------------------------------ hash chain
def test_seeded_chains_are_valid(client, admin):
    for lid in ("DL-1001", "DL-1002", "DL-1003"):
        r = client.get(f"/loads/{lid}/verify-integrity", headers=admin).json()
        assert r["valid"] is True and r["broken_at_index"] is None and r["total_events"] > 0


def test_corrupt_event_is_detected_at_exact_index(client, admin):
    events = client.get(f"/loads/{LOAD}/events", headers=admin).json()
    target = next(e for e in events if e["event_type"] == "RECEIVING_RECORDED")
    r = client.post(f"/admin/loads/{LOAD}/corrupt-event/{target['id']}", headers=admin)
    assert r.status_code == 200
    assert r.json()["hash_recomputed"] is False and r.json()["after"]["quantity"] != r.json()["before"]["quantity"]
    v = client.get(f"/loads/{LOAD}/verify-integrity", headers=admin).json()
    assert v["valid"] is False and v["broken_at_index"] == target["index"] and v["broken_event_id"] == target["id"]
    # other loads are unaffected
    assert client.get("/loads/DL-1001/verify-integrity", headers=admin).json()["valid"] is True


def test_corrupt_endpoint_is_admin_only_and_scoped(client, facility):
    events = client.get(f"/loads/{LOAD}/events", headers=facility).json()
    assert client.post(f"/admin/loads/{LOAD}/corrupt-event/{events[0]['id']}", headers=facility).status_code == 403
    admin = login(client, "admin1")
    other_load_event = client.get("/loads/DL-1001/events", headers=admin).json()[0]["id"]
    assert client.post(f"/admin/loads/{LOAD}/corrupt-event/{other_load_event}", headers=admin).status_code == 404


def test_deleting_a_middle_event_breaks_the_chain(client, admin):
    events = client.get(f"/loads/{LOAD}/events", headers=admin).json()
    with SessionLocal() as db:
        row = db.get(EventLog, events[3]["id"])
        db.delete(row)
        db.commit()
    v = client.get(f"/loads/{LOAD}/verify-integrity", headers=admin).json()
    assert v["valid"] is False and v["broken_at_index"] == 3  # the next event no longer links


def test_state_changes_append_events(client, facility):
    d = disc_id(client, facility, LOAD)
    before = client.get(f"/loads/{LOAD}", headers=facility).json()["event_count"]
    client.post(f"/discrepancy/{d}/add-evidence", json={"note": "Weighbridge slip attached"}, headers=facility)
    assert client.get(f"/loads/{LOAD}", headers=facility).json()["event_count"] == before + 1


# -------------------------------------------------------- state machine
def test_invalid_transitions_rejected_with_clear_error(client, facility):
    verifier = login(client, "facility2")
    d = disc_id(client, facility, LOAD)
    for action, body in [("resolve", {"finding": "x y z"}), ("close", {}), ("investigate", {}),
                         ("corroborate", {"audit_quantity": 385})]:
        r = client.post(f"/discrepancy/{d}/{action}", json=body, headers=verifier)
        assert r.status_code == 409, (action, r.text)
        detail = r.json()["detail"]
        assert detail["error"] == "INVALID_TRANSITION" and detail["allowed_action"] == "add-evidence"
    assert client.get(f"/discrepancy/{d}", headers=facility).json()["status"] == "FLAGGED"


def test_full_walk_flagged_to_closed(client, facility):
    verifier = login(client, "facility2")
    d = disc_id(client, facility, LOAD)
    assert client.post(f"/discrepancy/{d}/add-evidence", json={"note": "Weighbridge slip shows 390 kg", "evidence_ref": "slip.jpg"}, headers=facility).status_code == 200
    steps = [
        ("corroborate", {"audit_quantity": 385, "auditor": "AUD-07"}, "CORROBORATED"),
        ("investigate", {"note": "Check transfer point"}, "INVESTIGATING"),
        ("resolve", {"finding": "Spillage at transfer point", "attributed_to": "PROCESS"}, "RESOLVED"),
        ("close", {"note": "Closed"}, "CLOSED"),
    ]
    for action, body, expected in steps:
        r = client.post(f"/discrepancy/{d}/{action}", json=body, headers=verifier)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == expected
    # closed is terminal
    assert client.post(f"/discrepancy/{d}/close", json={}, headers=verifier).status_code == 409
    load = client.get(f"/loads/{LOAD}", headers=facility).json()
    assert load["status"] == "SETTLED"
    assert client.get(f"/loads/{LOAD}/verify-integrity", headers=facility).json()["valid"] is True


def test_single_signal_never_corroborates(client, facility):
    verifier = login(client, "facility2")
    d = disc_id(client, facility, LOAD)
    client.post(f"/discrepancy/{d}/add-evidence", json={"note": "Weighbridge slip"}, headers=facility)
    # audit sides with the worker's declaration (520) -> NOT corroborated, nothing attributed
    r = client.post(f"/discrepancy/{d}/corroborate", json={"audit_quantity": 515}, headers=verifier)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "NOT_CORROBORATED"
    assert client.get(f"/discrepancy/{d}", headers=facility).json()["status"] == "EVIDENCE_PENDING"
    # audit differs from declaration but disagrees with the facility figure -> still not corroborated
    r = client.post(f"/discrepancy/{d}/corroborate", json={"audit_quantity": 250}, headers=verifier)
    assert r.status_code == 409
    assert client.post(f"/discrepancy/{d}/investigate", json={}, headers=verifier).status_code == 409
    # the rejected attempts are themselves in the audit trail
    types = [e["event_type"] for e in client.get(f"/loads/{LOAD}/events", headers=facility).json()]
    assert types.count("CORROBORATION_REJECTED") == 2
    # a genuine agreeing audit works afterwards
    assert client.post(f"/discrepancy/{d}/corroborate", json={"audit_quantity": 385}, headers=verifier).status_code == 200


def test_stream_discrepancy_needs_audit_condition(client, facility):
    verifier = login(client, "facility2")
    d = disc_id(client, facility, "DL-1003")   # seeded at INVESTIGATING
    assert client.get(f"/discrepancy/{d}", headers=facility).json()["status"] == "INVESTIGATING"
    r = client.post(f"/discrepancy/{d}/resolve", json={"finding": "Contamination at source", "attributed_to": "NONE"}, headers=verifier)
    assert r.status_code == 200 and r.json()["type"] == "STREAM"


# ---------------------------------------------------------- cross-check
def test_compare_records_unit():
    decl = {"source": "WORKER_DECLARATION", "quantity": 500, "stream": "SEGREGATED"}
    fac = {"source": "FACILITY_RECEIVING", "quantity": 495, "condition": "ACCEPTABLE"}
    assert crosscheck.compare_records(decl, fac) == "MATCH"
    fac_bad = {**fac, "quantity": 350}
    assert crosscheck.compare_records(decl, fac_bad) == "FLAGGED"
    audit = {"source": "AUDIT", "quantity": 345, "condition": "ACCEPTABLE"}
    assert crosscheck.compare_records(decl, audit, flagged_against=fac_bad, dimension="QUANTITY") == "CORROBORATED"
    audit_sides_with_worker = {**audit, "quantity": 500}
    assert crosscheck.compare_records(decl, audit_sides_with_worker, flagged_against=fac_bad, dimension="QUANTITY") == "MATCH"
    with pytest.raises(crosscheck.IndependenceError):          # same source is not independent
        crosscheck.compare_records(decl, {**fac_bad, "quantity": 349}, flagged_against=fac_bad, dimension="QUANTITY")
    with pytest.raises(crosscheck.IndependenceError):          # worker cannot corroborate against themself
        crosscheck.compare_records(decl, {**decl, "quantity": 350}, flagged_against=fac_bad, dimension="QUANTITY")


def test_mixed_load_rejected_by_facility_is_not_a_mismatch():
    decl = {"quantity": 400, "stream": "MIXED"}
    assert crosscheck.compare_records(decl, {"source": "FACILITY_RECEIVING", "quantity": 400, "condition": "UNACCEPTABLE"}) == "MATCH"


# ------------------------------------------- live end-to-end (worker -> facility)
def test_live_path_worker_to_receiving_triggers_crosscheck(client, facility):
    w = login(client, "worker1")
    route = client.get("/worker/route", headers=w).json()
    assert route["active_load"] is None or route["active_load"]["id"] == "DL-1022"
    for h in route["households"]:
        r = client.post("/worker/collections", json={"household_id": h["id"], "status": "SEGREGATED"}, headers=w)
        if r.status_code == 409:
            d = r.json().get("detail")
            if (isinstance(d, dict) and (d.get("code") == "VERIFICATION_PAUSED" or d.get("error") == "VERIFICATION_PAUSED")) or (isinstance(d, str) and "VERIFICATION_PAUSED" in d):
                client.post("/worker/trip/acknowledge-verification", headers=w)
                r = client.post("/worker/collections", json={"household_id": h["id"], "status": "SEGREGATED"}, headers=w)
        assert r.status_code == 200, r.text
    assert client.post("/worker/collections", json={"household_id": route["households"][0]["id"], "status": "SEGREGATED"}, headers=w).status_code == 409
    load_id = client.get("/worker/route", headers=w).json()["active_load"]["id"]
    assert client.post(f"/loads/{load_id}/receiving", json={"quantity": 100, "condition": "ACCEPTABLE"}, headers=facility).status_code == 409  # not declared yet
    assert client.post(f"/loads/{load_id}/declare", json={"declared_quantity_kg": 600}, headers=w).status_code == 200
    after_declare = client.get("/worker/route", headers=w).json()
    assert after_declare["trip"]["status"] == "COMPLETED"
    assert after_declare["active_load"]["id"] == load_id
    assert after_declare["active_load"]["status"] == "DECLARED"
    assert all(h["status"] == "SEGREGATED" for h in after_declare["households"])
    r = client.post(f"/loads/{load_id}/receiving", json={"quantity": 380, "condition": "ACCEPTABLE"}, headers=facility).json()
    assert r["cross_check_result"] == "FLAGGED" and r["discrepancies"][0]["status"] == "FLAGGED" and r["discrepancies"][0]["type"] == "QUANTITY"
    assert client.get(f"/loads/{load_id}/verify-integrity", headers=facility).json()["valid"] is True


def test_role_guards(client):
    w = login(client, "worker1")
    assert client.get("/loads", headers=w).status_code == 403
    assert client.get("/loads").status_code == 401
    c = login(client, "citizen1")
    assert client.get("/citizen/me", headers=c).json()["civic_credits"] == 120
    assert client.post("/citizen/sanitation-reports", json={"description": "Overflowing bin near gate 2"}, headers=c).status_code == 200


def test_multi_device_session_isolation(client, facility):
    w = login(client, "worker1")
    dev_a = {**w, "X-Demo-Session": "device_alpha_01"}
    dev_b = {**w, "X-Demo-Session": "device_bravo_02"}
    fac_a = {**facility, "X-Demo-Session": "device_alpha_01"}
    fac_b = {**facility, "X-Demo-Session": "device_bravo_02"}

    # Device A starts with a clean 0/6 PENDING shift (does not see seeded active DL-1022)
    route_a = client.get("/worker/route", headers=dev_a).json()
    assert route_a["active_load"] is None
    assert route_a["trip"]["status"] == "IN_PROGRESS"
    assert all(h["status"] == "PENDING" for h in route_a["households"])

    # Device A marks all 6 households and completes trip without weight
    for h in route_a["households"]:
        r = client.post("/worker/collections", json={"household_id": h["id"], "status": "SEGREGATED"}, headers=dev_a)
        assert r.status_code == 200, r.text
    comp_a = client.post("/worker/trip/complete", json={}, headers=dev_a)
    assert comp_a.status_code == 200, comp_a.text
    load_a_id = comp_a.json()["id"]
    assert comp_a.json()["status"] == "DECLARED"
    assert comp_a.json()["declared_quantity"] is None

    # Refreshing on Device A preserves completed trip and DECLARED load
    refresh_a = client.get("/worker/route", headers=dev_a).json()
    assert refresh_a["trip"]["status"] == "COMPLETED"
    assert refresh_a["active_load"]["id"] == load_a_id
    assert refresh_a["active_load"]["status"] == "DECLARED"
    assert all(h["status"] == "SEGREGATED" for h in refresh_a["households"])

    # Device B opens /worker/route concurrently -> gets its own clean 0/6 PENDING shift!
    route_b = client.get("/worker/route", headers=dev_b).json()
    assert route_b["active_load"] is None
    assert route_b["trip"]["status"] == "IN_PROGRESS"
    assert route_b["trip"]["id"] != refresh_a["trip"]["id"]
    assert all(h["status"] == "PENDING" for h in route_b["households"])

    # Device B does NOT see Device A's load in /loads or /worker/history
    loads_a = [l["id"] for l in client.get("/loads", headers=fac_a).json()]
    loads_b = [l["id"] for l in client.get("/loads", headers=fac_b).json()]
    assert load_a_id in loads_a
    assert load_a_id not in loads_b
    assert "DL-1022" not in loads_a and "DL-1022" not in loads_b

    hist_a = [t["load_id"] for t in client.get("/worker/history", headers=dev_a).json()]
    hist_b = [t["load_id"] for t in client.get("/worker/history", headers=dev_b).json()]
    assert load_a_id in hist_a
    assert load_a_id not in hist_b

    # Receiving facility on Device A receives load_a_id
    rec_a = client.post(f"/loads/{load_a_id}/receiving", json={"quantity": 390, "condition": "UNACCEPTABLE"}, headers=fac_a)
    assert rec_a.status_code == 200, rec_a.text
    assert rec_a.json()["cross_check_result"] == "FLAGGED"

