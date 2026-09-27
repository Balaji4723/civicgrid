"""Phase 2 - independence rules and audit -> Cross-Check corroboration.

Setting: REQUIRE_FILE_EVIDENCE=true (the Docker/demo mode) for every test here.
Cast (all seeded): DL-1002 was declared by worker2 (520 kg), received by facility1 at facility 1 (390 kg) -> discrepancy #1 FLAGGED.
  worker2  = the responsible worker           facility1 = recorded the receiving record (facility 1)
  facility2 = a user of a DIFFERENT facility  admin1    = municipal admin, involved in neither signal
"""
import io
import json

import pytest
from PIL import Image
from sqlalchemy import text

from app.auth import hash_password
from app.db import SessionLocal
from app.independence import auditor_violations, get_parties
from app.models import (Audit, AuditCorroboration, DigitalLoad, DiscrepancyEvent, Evidence, Role, User)
from tests.conftest import login

pytestmark = pytest.mark.usefixtures("file_evidence_required")
D, LOAD = 1, "DL-1002"


def png(color):
    b = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(b, "PNG")
    return b.getvalue()


_n = [0]


def fresh_png():
    _n[0] += 1
    return png((_n[0] % 256, (_n[0] * 7) % 256, (_n[0] * 13) % 256))


def up(client, headers, path, data=None, **form):
    return client.post(path, files={"file": ("photo.png", data or fresh_png(), "image/png")},
                       data={"description": "evidence photo", **form}, headers=headers)


@pytest.fixture()
def worker(client): return login(client, "worker2")
@pytest.fixture()
def fac1(client): return login(client, "facility1")
@pytest.fixture()
def fac2(client): return login(client, "facility2")
@pytest.fixture()
def admin(client): return login(client, "admin1")


def make_user(username, role, **kw):
    with SessionLocal() as db:
        u = User(username=username, role=role, name=username, password_hash=hash_password("demo123"), **kw)
        db.add(u)
        db.commit()
        return u.id


def manual(client, admin=None, load=LOAD, reason="Independent re-check requested for this load"):
    fac = login(client, "facility2")
    r = client.post("/audit-center/audits", json={"load_id": load, "reason": reason}, headers=fac)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def conduct(client, auditor, audit_id, qty, cond="ACCEPTABLE", with_file=True, data=None):
    assert client.post(f"/audit-center/audits/{audit_id}/start", headers=auditor).status_code == 200
    if with_file:
        r = up(client, auditor, f"/audit-center/audits/{audit_id}/evidence", data)
        assert r.status_code == 200, r.text
    return client.post(f"/audit-center/audits/{audit_id}/complete", json={"quantity": qty, "condition": cond, "observations": "Weighed on the calibrated scale."}, headers=auditor)


def to_evidence_pending(client, fac1):
    assert up(client, fac1, f"/discrepancy/{D}/evidence", description="weighbridge slip").status_code == 200
    r = client.post(f"/discrepancy/{D}/add-evidence", json={"note": "weighbridge slip attached"}, headers=fac1)
    assert r.status_code == 200 and r.json()["status"] == "EVIDENCE_PENDING"


def status(client, h): return client.get(f"/discrepancy/{D}", headers=h).json()


# ================================================================ who may audit at all
def test_worker_role_cannot_use_the_audit_center_or_audit(client, worker, admin):
    aid = manual(client, admin)
    for method, path in [("get", "/audit-center/audits"), ("get", f"/audit-center/audits/{aid}"), ("post", f"/audit-center/audits/{aid}/start"),
                         ("get", "/audit-center/summary"), ("get", "/audit-center/config")]:
        assert getattr(client, method)(path, headers=worker).status_code == 403, path
    assert client.post(f"/audit-center/audits/{aid}/complete", json={"quantity": 1, "condition": "ACCEPTABLE", "observations": "self audit"}, headers=worker).status_code == 403
    assert client.post("/audit-center/audits", json={"load_id": LOAD, "reason": "worker selecting own audit"}, headers=worker).status_code == 403


def test_worker_account_cannot_audit_own_collection_even_if_given_an_auditor_role(client, admin):
    """The rule is enforced from the data (which worker this account belongs to), not from the role name."""
    make_user("bad_admin", Role.MUNICIPAL_ADMIN, worker_id=2)         # an ADMIN account that is linked to worker2
    h = login(client, "bad_admin")
    aid = manual(client, admin)
    r = client.post(f"/audit-center/audits/{aid}/start", headers=h)
    assert r.status_code == 403 and r.json()["detail"]["error"] == "NOT_INDEPENDENT"
    assert {v["code"] for v in r.json()["detail"]["violations"]} == {"RESPONSIBLE_WORKER"}
    assert client.get(f"/audit-center/audits/{aid}", headers=admin).json()["status"] == "PENDING"


def test_a_worker_may_still_audit_someone_elses_load_in_principle_but_not_via_the_worker_role(client, admin):
    """A linked account of a DIFFERENT worker (worker1) is not the responsible worker for DL-1002 -> no RESPONSIBLE_WORKER violation."""
    with SessionLocal() as db:
        u = User(username="w1_admin", role=Role.MUNICIPAL_ADMIN, name="x", password_hash="x$y", worker_id=1)
        parties = get_parties(db, db.get(DigitalLoad, LOAD))
        assert auditor_violations(u, parties) == []
        w = User(username="w", role=Role.WORKER, name="w", password_hash="x$y", worker_id=2)
        assert {v["code"] for v in auditor_violations(w, parties)} == {"ROLE_WORKER", "RESPONSIBLE_WORKER"}


def test_facility_that_recorded_the_signal_is_recused(client, fac1, admin):
    aid = manual(client, admin)
    assert client.get("/audit-center/audits", headers=fac1).json() == []                     # cannot even see it
    assert client.get(f"/audit-center/audits/{aid}", headers=fac1).status_code == 404
    assert client.post(f"/audit-center/audits/{aid}/start", headers=fac1).status_code == 404
    with SessionLocal() as db:
        u = db.query(User).filter(User.username == "facility1").one()
        v = {x["code"] for x in auditor_violations(u, get_parties(db, db.get(DigitalLoad, LOAD)))}
    assert v == {"RECORDED_FACILITY_SIGNAL", "SAME_FACILITY_ORGANISATION"}


def test_another_user_of_the_same_facility_is_not_independent_either(client, admin):
    make_user("facility1b", Role.FACILITY, facility_id=1)                                    # different account, same facility organisation
    h = login(client, "facility1b")
    aid = manual(client, admin)
    assert client.get(f"/audit-center/audits/{aid}", headers=h).status_code == 404
    with SessionLocal() as db:
        u = db.query(User).filter(User.username == "facility1b").one()
        assert {x["code"] for x in auditor_violations(u, get_parties(db, db.get(DigitalLoad, LOAD)))} == {"SAME_FACILITY_ORGANISATION"}


def test_recorder_who_recorded_the_receiving_record_cannot_audit_that_load(client, admin):
    """Live path: facility1 records receiving on a fresh load -> facility1 is the recorder -> not independent for that load."""
    w = login(client, "worker1")
    fac1 = login(client, "facility1")
    for h in client.get("/worker/route", headers=w).json()["households"]:
        client.post("/worker/collections", json={"household_id": h["id"], "status": "SEGREGATED"}, headers=w)
    lid = client.get("/worker/route", headers=w).json()["active_load"]["id"]
    client.post(f"/loads/{lid}/declare", json={"declared_quantity_kg": 600}, headers=w)
    assert client.post(f"/loads/{lid}/receiving", json={"quantity": 590, "condition": "ACCEPTABLE"}, headers=fac1).status_code == 200
    aid = manual(client, admin, load=lid)
    r = client.post(f"/audit-center/audits/{aid}/start", headers=fac1)
    assert r.status_code == 404


def test_independent_facility_and_admin_can_audit(client, admin, fac2):
    a1 = manual(client, admin)
    assert client.get(f"/audit-center/audits/{a1}", headers=fac2).json()["can_conduct"] is True
    assert client.post(f"/audit-center/audits/{a1}/start", headers=fac2).json()["status"] == "IN_PROGRESS"
    a2 = manual(client, admin, load="DL-1001")
    assert client.post(f"/audit-center/audits/{a2}/start", headers=admin).json()["status"] == "IN_PROGRESS"


def test_only_the_auditor_who_started_can_add_evidence_or_complete(client, admin, fac2):
    aid = manual(client, admin)
    client.post(f"/audit-center/audits/{aid}/start", headers=fac2)
    assert up(client, admin, f"/audit-center/audits/{aid}/evidence").status_code == 409
    assert client.post(f"/audit-center/audits/{aid}/complete", json={"quantity": 385, "condition": "ACCEPTABLE", "observations": "not my audit"}, headers=admin).status_code == 409
    assert up(client, fac2, f"/audit-center/audits/{aid}/evidence").status_code == 200


# ================================================================ corroboration outcomes
def test_audit_supporting_the_facility_is_accepted_and_the_state_machine_continues(client, fac1, fac2, admin):
    to_evidence_pending(client, fac1)
    aid = manual(client, admin)
    done = conduct(client, fac2, aid, 385)
    assert done.status_code == 200 and done.json()["result"]["overall"] == "SUPPORTS_FACILITY" and done.json()["status"] == "COMPLETED"
    r = client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": aid}, headers=fac2)
    assert r.status_code == 200 and r.json()["status"] == "CORROBORATED" and r.json()["outcome"] == "ACCEPTED"
    d = status(client, admin)
    assert d["corroboration_path"] == "INDEPENDENT_AUDIT" and d["corroboration_evidence_backed"] is True
    assert d["details"]["audit"]["audit_id"] == aid and d["details"]["audit"]["evidence"]
    assert d["details"]["resolution"] is None, "corroboration must not attribute anything"
    # the EXISTING state machine carries on unchanged
    assert client.post(f"/discrepancy/{D}/investigate", json={}, headers=fac2).json()["status"] == "INVESTIGATING"
    assert client.post(f"/discrepancy/{D}/resolve", json={"finding": "Spillage in transfer", "attributed_to": "PROCESS"}, headers=fac2).json()["status"] == "RESOLVED"
    assert client.post(f"/discrepancy/{D}/close", json={}, headers=fac2).json()["status"] == "CLOSED"
    assert client.get(f"/loads/{LOAD}/verify-integrity", headers=admin).json()["valid"] is True


def test_audit_supporting_the_worker_is_rejected_and_nothing_is_attributed(client, fac1, fac2, admin):
    to_evidence_pending(client, fac1)
    aid = manual(client, admin)
    assert conduct(client, fac2, aid, 515).json()["result"]["overall"] == "SUPPORTS_WORKER"
    r = client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": aid}, headers=fac2)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "NOT_CORROBORATED"
    assert r.json()["detail"]["reason_code"] == "AUDIT_SUPPORTS_WORKER" and r.json()["detail"]["outcome"] == "REJECTED_SUPPORTS_WORKER"
    d = status(client, admin)
    assert d["status"] == "EVIDENCE_PENDING" and d["details"]["audit"] is None and d["details"]["resolution"] is None
    ev = [e for e in client.get(f"/loads/{LOAD}/events", headers=admin).json() if e["event_type"] == "CORROBORATION_REJECTED"]
    assert len(ev) == 1 and ev[0]["payload"]["reason_code"] == "AUDIT_SUPPORTS_WORKER" and ev[0]["payload"]["attribution"].startswith("NONE")
    with SessionLocal() as db:
        c = db.query(AuditCorroboration).one()
        assert c.outcome.value == "REJECTED_SUPPORTS_WORKER" and c.audit_id == aid and c.discrepancy_id == D and c.event_id == ev[0]["id"]
    # an audit is evaluated once per discrepancy
    assert client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": aid}, headers=fac2).json()["detail"]["error"] == "AUDIT_ALREADY_EVALUATED"


def test_audit_disagreeing_with_both_is_rejected_as_inconclusive(client, fac1, fac2, admin):
    to_evidence_pending(client, fac1)
    aid = manual(client, admin)
    done = conduct(client, fac2, aid, 250)
    assert done.json()["result"]["overall"] == "INCONCLUSIVE" and done.json()["result"]["requires_followup"] is True
    r = client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": aid}, headers=fac2)
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "AUDIT_INCONCLUSIVE" and r.json()["detail"]["outcome"] == "REJECTED_INCONCLUSIVE"
    assert status(client, admin)["status"] == "EVIDENCE_PENDING"


def test_auditor_who_became_non_independent_is_rejected_at_corroboration_time(client, fac1, fac2, admin):
    """Independence is re-checked on the server when the audit is submitted, not only when it was started."""
    to_evidence_pending(client, fac1)
    aid = manual(client, admin)
    assert conduct(client, fac2, aid, 385).status_code == 200
    with SessionLocal() as db:   # the audit is now found to have been done by the person who recorded the facility signal
        fac2_id = db.query(User.id).filter(User.username == "facility2").scalar()
        db.execute(text("update receiving_records set recorded_by_user_id = :u where load_id = 'DL-1002'"), {"u": fac2_id})
        db.commit()
    r = client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": aid}, headers=fac2)
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "AUDITOR_NOT_INDEPENDENT" and r.json()["detail"]["outcome"] == "REJECTED_NOT_INDEPENDENT"
    assert status(client, admin)["status"] == "EVIDENCE_PENDING"


def test_audit_whose_only_evidence_duplicates_someone_elses_file_is_rejected(client, worker, fac1, fac2, admin):
    to_evidence_pending(client, fac1)
    shared = fresh_png()
    assert up(client, worker, f"/discrepancy/{D}/evidence", data=shared).status_code == 200       # worker's photo
    aid = manual(client, admin)
    assert conduct(client, fac2, aid, 385, data=shared).status_code == 200                       # auditor re-uses the same bytes
    r = client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": aid}, headers=fac2)
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "NO_INDEPENDENT_FILE_EVIDENCE" and r.json()["detail"]["outcome"] == "REJECTED_NO_EVIDENCE"


def test_workers_own_evidence_cannot_corroborate_their_own_declaration(client, worker, fac1, fac2, admin):
    to_evidence_pending(client, fac1)
    e = up(client, worker, f"/discrepancy/{D}/evidence").json()
    assert e["independence"]["independent"] is False and any("responsible" in x.lower() for x in e["independence"]["reasons"])
    assert len(e["independence"]["reasons"]) == 1 and not any("conduct audits" in x for x in e["independence"]["reasons"]), "reasons must describe the EVIDENCE"
    # evidence alone never corroborates: a completed independent audit is required
    r = client.post(f"/discrepancy/{D}/corroborate", json={}, headers=fac2)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "AUDIT_REQUIRED"
    assert status(client, admin)["status"] == "EVIDENCE_PENDING"
    # and the worker cannot drive the workflow themselves
    assert client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": 1}, headers=worker).status_code == 403


def test_facility_own_evidence_is_not_independent_either(client, fac1, admin):
    e = up(client, fac1, f"/discrepancy/{D}/evidence").json()
    assert e["independence"]["independent"] is False
    assert any("recorded the facility" in x or "facility that received" in x for x in e["independence"]["reasons"])
    admin_ev = up(client, admin, f"/discrepancy/{D}/evidence").json()
    assert admin_ev["independence"] == {"independent": True, "reasons": []} and admin_ev["side"] == "NEUTRAL"


def test_audit_state_preconditions(client, fac1, fac2, admin):
    to_evidence_pending(client, fac1)
    aid = manual(client, admin)
    assert client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": aid}, headers=fac2).json()["detail"]["error"] == "AUDIT_NOT_COMPLETED"
    client.post(f"/audit-center/audits/{aid}/start", headers=fac2)
    assert client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": aid}, headers=fac2).json()["detail"]["error"] == "AUDIT_NOT_COMPLETED"
    assert client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": 9999}, headers=fac2).status_code == 404
    other = manual(client, admin, load="DL-1001")            # an audit of a different load
    assert client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": other}, headers=fac2).status_code == 404


def test_audit_cannot_be_completed_without_file_evidence_when_required(client, fac2, admin):
    aid = manual(client, admin)
    client.post(f"/audit-center/audits/{aid}/start", headers=fac2)
    r = client.post(f"/audit-center/audits/{aid}/complete", json={"quantity": 385, "condition": "ACCEPTABLE", "observations": "no photo taken"}, headers=fac2)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "AUDIT_EVIDENCE_REQUIRED"


def test_legacy_manual_corroboration_is_refused_in_file_evidence_mode(client, fac1, fac2, admin):
    to_evidence_pending(client, fac1)
    r = client.post(f"/discrepancy/{D}/corroborate", json={"audit_quantity": 385}, headers=fac2)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "AUDIT_REQUIRED"
    r = client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": 1, "audit_quantity": 385}, headers=fac2)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "AMBIGUOUS_CORROBORATION"


def test_existing_cross_check_engine_and_state_machine_still_reject_out_of_order(client, fac2):
    for action, body in [("resolve", {"finding": "x y z"}), ("close", {}), ("investigate", {}), ("corroborate", {"audit_id": 1})]:
        r = client.post(f"/discrepancy/{D}/{action}", json=body, headers=fac2)
        assert r.status_code == 409 and r.json()["detail"]["error"] == "INVALID_TRANSITION" and r.json()["detail"]["allowed_action"] == "add-evidence"


# ================================================================ THE PHASE 2 DEMO, as a test
def test_phase2_demo_scenario_end_to_end(client, worker, fac1, fac2, admin):
    """DL-1002: 520 kg declared / 390 kg received  ->  FLAGGED -> EVIDENCE_PENDING -> audit #1 (supports worker) REJECTED ->
    independent audit #2 (supports facility) ACCEPTED -> CORROBORATED -> INVESTIGATING -> RESOLVED -> CLOSED."""
    d = status(client, admin)
    assert d["status"] == "FLAGGED" and d["details"]["declaration"]["quantity"] == 520 and d["details"]["receiving"]["quantity"] == 390
    # worker supplies THEIR side - it is recorded, classified WORKER and can never be independent
    w = up(client, worker, f"/discrepancy/{D}/evidence", description="my load photo at pickup").json()
    assert w["side"] == "WORKER" and w["independence"]["independent"] is False
    # the facility supplies its side and advances the workflow (a real file is required)
    to_evidence_pending(client, fac1)
    # audit #1 by the admin: weighs 515 kg -> supports the worker -> rejected
    a1 = manual(client, admin, reason="First independent check requested by the municipal admin")
    assert conduct(client, admin, a1, 515).json()["result"]["overall"] == "SUPPORTS_WORKER"
    r1 = client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": a1}, headers=fac2)
    assert r1.status_code == 409 and r1.json()["detail"]["reason_code"] == "AUDIT_SUPPORTS_WORKER"
    assert status(client, admin)["status"] == "EVIDENCE_PENDING"
    # audit #2 by an independent facility auditor (different facility): 385 kg -> supports facility -> accepted
    a2 = manual(client, admin, reason="Second audit by an auditor from a different facility")
    assert conduct(client, fac2, a2, 385).json()["result"]["overall"] == "SUPPORTS_FACILITY"
    r2 = client.post(f"/discrepancy/{D}/corroborate", json={"audit_id": a2}, headers=fac2)
    assert r2.status_code == 200 and r2.json()["status"] == "CORROBORATED"
    for action, body, expect in [("investigate", {}, "INVESTIGATING"), ("resolve", {"finding": "Spillage during transfer between vehicles", "attributed_to": "PROCESS"}, "RESOLVED"), ("close", {}, "CLOSED")]:
        assert client.post(f"/discrepancy/{D}/{action}", json=body, headers=fac2).json()["status"] == expect
    # ONE load, ONE trail
    events = client.get(f"/loads/{LOAD}/events", headers=admin).json()
    types = [e["event_type"] for e in events]
    for t in ("EVIDENCE_ADDED", "DISCREPANCY_EVIDENCE_ADDED", "AUDIT_SELECTED", "AUDIT_STARTED", "AUDIT_COMPLETED", "CORROBORATION_REJECTED",
              "DISCREPANCY_CORROBORATED", "DISCREPANCY_INVESTIGATING", "DISCREPANCY_RESOLVED", "DISCREPANCY_CLOSED"):
        assert t in types, t
    assert types.count("AUDIT_SELECTED") == 2 and types.count("AUDIT_COMPLETED") == 2
    assert client.get(f"/loads/{LOAD}/verify-integrity", headers=admin).json()["valid"] is True
    # provenance panel shows both audits, who did them and whether they were independent
    ind = status(client, admin)["independence"]
    assert [(a["audit_id"], a["independent"], a["evaluated"]["outcome"]) for a in ind["audits"]] == [(a1, True, "REJECTED_SUPPORTS_WORKER"), (a2, True, "ACCEPTED")]
    assert ind["principle"] == "AI can flag. Independent evidence corroborates."
    # every file hash is in the immutable chain
    file_hashes = {e["payload"]["sha256"] for e in events if e["event_type"] == "EVIDENCE_ADDED"}
    with SessionLocal() as db:
        assert {e.sha256 for e in db.query(Evidence).filter(Evidence.sha256.is_not(None)).all()} == file_hashes
    # tamper detection still works on the enriched chain
    target = next(e for e in events if e["event_type"] == "EVIDENCE_ADDED")
    with SessionLocal() as db:
        from app.models import EventLog
        row = db.get(EventLog, target["id"])
        row.payload_json = {**row.payload_json, "sha256": "f" * 64}
        db.commit()
    v = client.get(f"/loads/{LOAD}/verify-integrity", headers=admin).json()
    assert v["valid"] is False and v["broken_event_id"] == target["id"]


def test_worker_evidence_requests_endpoint_shows_only_own_loads(client, worker, fac1):
    r = client.get("/worker/evidence-requests", headers=worker).json()
    assert [(x["load_id"], x["discrepancy_id"], x["status"], x["accepting_evidence"]) for x in r] == [("DL-1002", 1, "FLAGGED", True)]
    assert client.get("/worker/evidence-requests", headers=login(client, "worker1")).json() == []
    assert client.get("/worker/evidence-requests", headers=fac1).status_code == 403
