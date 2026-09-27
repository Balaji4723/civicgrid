"""Phase 2 RBAC & Role Separation Tests.
Verifies authority boundaries between Worker, Receiving Operator, Independent Verifier (Facility), and Municipal Admin.
"""
import pytest
from app.db import SessionLocal
from app.models import Audit, Role
from tests.conftest import login


@pytest.fixture()
def admin(client):
    return login(client, "admin1")


@pytest.fixture()
def fac1(client):
    return login(client, "facility1")


@pytest.fixture()
def fac2(client):
    return login(client, "facility2")


@pytest.fixture()
def worker(client):
    return login(client, "worker1")


@pytest.fixture()
def citizen(client):
    return login(client, "citizen1")


@pytest.fixture()
def fac_ops(client):
    return login(client, "facility_ops")


# ================================================================ 1. Worker Restrictions
def test_worker_cannot_access_audit_center(client, worker):
    assert client.get("/audit-center/audits", headers=worker).status_code == 403
    assert client.get("/audit-center/summary", headers=worker).status_code == 403
    assert client.post("/audit-center/selection-runs", json={"method": "RANDOM"}, headers=worker).status_code == 403
    assert client.post("/audit-center/audits", json={"load_id": "DL-1001", "reason": "Test manual audit reason"}, headers=worker).status_code == 403


def test_worker_cannot_record_receiving(client, worker):
    r = client.post("/loads/DL-1001/receiving", json={"quantity": 400, "condition": "ACCEPTABLE"}, headers=worker)
    assert r.status_code == 403


def test_worker_cannot_mutate_processing_or_handoffs(client, worker):
    assert client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED", "processing_method": "LANDFILL", "processed_quantity_kg": 400}, headers=worker).status_code == 403
    assert client.post("/handoffs", json={"processing_record_id": 1, "destination_facility_id": 2, "waste_stream": "RECOVERED", "quantity_kg": 100}, headers=worker).status_code == 403
    assert client.post("/final-dispositions", json={"processing_record_id": 1, "disposition_type": "LANDFILL", "quantity_kg": 100}, headers=worker).status_code == 403
    assert client.post("/disposal-exceptions", json={"processing_record_id": 1, "reason": "Test exception reason"}, headers=worker).status_code == 403


# ================================================================ 2. Citizen Restrictions
def test_citizen_blocked_from_operational_endpoints(client, citizen):
    assert client.get("/loads", headers=citizen).status_code == 403
    assert client.get("/discrepancy/1", headers=citizen).status_code == 403
    assert client.get("/audit-center/audits", headers=citizen).status_code == 403
    assert client.post("/loads/DL-1001/receiving", json={"quantity": 400, "condition": "ACCEPTABLE"}, headers=citizen).status_code == 403


# ================================================================ 3. Municipal Admin View-Only Restrictions
def test_municipal_admin_cannot_mutate_discrepancies(client, admin):
    # Municipal Admin is view-only for discrepancy resolution
    assert client.post("/discrepancy/1/corroborate", json={"audit_id": 1}, headers=admin).status_code == 403
    assert client.post("/discrepancy/1/investigate", json={"note": "Test investigation note"}, headers=admin).status_code == 403
    assert client.post("/discrepancy/1/resolve", json={"finding": "Test resolution finding", "attributed_to": "PROCESS"}, headers=admin).status_code == 403
    assert client.post("/discrepancy/1/close", json={"note": "Test closing note"}, headers=admin).status_code == 403


def test_municipal_admin_cannot_execute_audit_selections(client, admin):
    # Selection runs and manual audit creation are operational actions (restricted from municipal admin)
    r_sel = client.post("/audit-center/selection-runs", json={"method": "RANDOM", "random_sample_pct": 50}, headers=admin)
    assert r_sel.status_code == 403

    r_man = client.post("/audit-center/audits", json={"load_id": "DL-1001", "reason": "Municipal requested check"}, headers=admin)
    assert r_man.status_code == 403

    r_can = client.post("/audit-center/audits/1/cancel", json={"reason": "Cancel audit reason"}, headers=admin)
    assert r_can.status_code == 403


def test_municipal_admin_cannot_operate_downstream_processing(client, admin):
    # Processing mutations restricted to FACILITY
    assert client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED", "processing_method": "LANDFILL", "processed_quantity_kg": 400}, headers=admin).status_code == 403
    assert client.post("/processing/1/complete", json={}, headers=admin).status_code == 403
    assert client.post("/processing/1/cancel", json={"reason": "Cancel processing reason"}, headers=admin).status_code == 403

    # Handoff mutations restricted to FACILITY
    assert client.post("/handoffs", json={"processing_record_id": 1, "destination_facility_id": 2, "waste_stream": "RECOVERED", "quantity_kg": 100}, headers=admin).status_code == 403
    assert client.post("/handoffs/1/complete", json={}, headers=admin).status_code == 403
    assert client.post("/handoffs/1/cancel", json={"reason": "Cancel handoff reason"}, headers=admin).status_code == 403

    # Disposal exception mutations restricted to FACILITY
    assert client.post("/disposal-exceptions", json={"processing_record_id": 1, "reason": "Test exception reason"}, headers=admin).status_code == 403
    assert client.post("/disposal-exceptions/1/authorize", json={"corrective_action": "REROUTE_FACILITY", "reroute_facility_id": 2}, headers=admin).status_code == 403
    assert client.post("/disposal-exceptions/1/resolve", json={"settlement_note": "Settlement note"}, headers=admin).status_code == 403

    # Final disposition mutations restricted to FACILITY
    assert client.post("/final-dispositions", json={"processing_record_id": 1, "disposition_type": "LANDFILL", "quantity_kg": 100}, headers=admin).status_code == 403
    assert client.post("/final-dispositions/1/verify", json={}, headers=admin).status_code == 403
    assert client.post("/final-dispositions/1/cancel", json={"reason": "Cancel disposition reason"}, headers=admin).status_code == 403


# ================================================================ 4. Municipal Admin View-Only Permissions
def test_municipal_admin_can_view_oversight_endpoints(client, admin):
    assert client.get("/audit-center/audits", headers=admin).status_code == 200
    assert client.get("/audit-center/selection-runs", headers=admin).status_code == 200
    assert client.get("/audit-center/summary", headers=admin).status_code == 200
    assert client.get("/loads", headers=admin).status_code == 200
    assert client.get("/loads/DL-1001", headers=admin).status_code == 200
    assert client.get("/discrepancy/1", headers=admin).status_code == 200
    assert client.get("/processing", headers=admin).status_code == 200
    assert client.get("/handoffs", headers=admin).status_code == 200
    assert client.get("/disposal-exceptions", headers=admin).status_code == 200
    assert client.get("/final-dispositions", headers=admin).status_code == 200


# ================================================================ 5. Receiving Operator Restrictions & Capability Split
def test_receiving_operator_blocked_from_processing_handoffs_and_disposal(client, fac1):
    # Receiving operator (facility1) cannot mutate processing, handoffs, dispositions, or exceptions
    assert client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED", "processing_method": "LANDFILL", "processed_quantity_kg": 400}, headers=fac1).status_code == 403
    assert client.post("/handoffs", json={"load_id": "DL-1001", "processing_record_id": 1, "source_facility_id": 1, "destination_facility_id": 2, "waste_stream": "RECOVERED", "quantity_kg": 100}, headers=fac1).status_code == 403
    assert client.post("/final-dispositions", json={"load_id": "DL-1001", "processing_record_id": 1, "disposition_type": "LANDFILL", "destination_facility_id": 2, "quantity_kg": 100}, headers=fac1).status_code == 403
    assert client.post("/disposal-exceptions", json={"load_id": "DL-1001", "source_processing_record_id": 1, "original_destination_facility_id": 2, "reason": "Test exception reason long enough"}, headers=fac1).status_code == 403


def test_receiving_operator_blocked_from_audit_and_discrepancies(client, fac1):
    # Receiving operator (facility1) cannot run audit selections, create manual audits, or mutate discrepancies
    assert client.post("/audit-center/selection-runs", json={"method": "RANDOM"}, headers=fac1).status_code == 403
    assert client.post("/audit-center/audits", json={"load_id": "DL-1001", "reason": "Manual audit request reason"}, headers=fac1).status_code == 403
    assert client.post("/discrepancy/1/investigate", json={"note": "Investigate note"}, headers=fac1).status_code == 403
    assert client.post("/discrepancy/1/corroborate", json={"audit_id": 1}, headers=fac1).status_code == 403
    assert client.post("/discrepancy/1/resolve", json={"finding": "Resolve finding", "attributed_to": "PROCESS"}, headers=fac1).status_code == 403
    assert client.post("/discrepancy/1/close", json={"note": "Close note"}, headers=fac1).status_code == 403


# ================================================================ 6. Processing Operator Capabilities & Restrictions
def test_processing_operator_can_process_and_blocked_from_receiving_and_audits(client, fac_ops):
    # Processing operator (facility_ops) CAN start processing
    r_proc = client.post("/processing", json={"load_id": "DL-1001", "facility_id": 1, "waste_stream": "MIXED", "processing_method": "MATERIAL_RECOVERY", "processed_quantity_kg": 468, "recovered_quantity_kg": 300, "residual_quantity_kg": 100}, headers=fac_ops)
    assert r_proc.status_code == 200

    # Processing operator CANNOT record physical receiving intake
    assert client.post("/loads/DL-1001/receiving", json={"quantity": 400, "condition": "ACCEPTABLE"}, headers=fac_ops).status_code == 403

    # Processing operator CANNOT run audit selections or mutate discrepancies
    assert client.post("/audit-center/selection-runs", json={"method": "RANDOM"}, headers=fac_ops).status_code == 403
    assert client.post("/discrepancy/1/corroborate", json={"audit_id": 1}, headers=fac_ops).status_code == 403


# ================================================================ 7. Independent Verifier Permissions & Restrictions
def test_independent_verifier_can_audit_and_blocked_from_receiving_and_processing(client, fac2):
    # Independent verifier (facility2) CAN run audit selections
    r_sel = client.post("/audit-center/selection-runs", json={"method": "RANDOM", "dry_run": True, "random_sample_pct": 50}, headers=fac2)
    assert r_sel.status_code == 200
    assert "eligible_count" in r_sel.json()

    # Independent verifier CAN create manual audit
    r_man = client.post("/audit-center/audits", json={"load_id": "DL-1001", "reason": "Independent audit check reason"}, headers=fac2)
    assert r_man.status_code == 200

    # Independent verifier CANNOT record physical receiving intake
    assert client.post("/loads/DL-1001/receiving", json={"quantity": 400, "condition": "ACCEPTABLE"}, headers=fac2).status_code == 403

    # Independent verifier CANNOT start downstream processing
    assert client.post("/processing", json={"load_id": "DL-1001", "facility_id": 2, "waste_stream": "MIXED", "processing_method": "LANDFILL", "processed_quantity_kg": 400}, headers=fac2).status_code == 403


# ================================================================ 8. Collection Random Audit Semantics
def test_collection_audit_has_no_worker_as_auditor():
    with SessionLocal() as db:
        audits = db.query(Audit).all()
        for a in audits:
            if a.risk_factors and isinstance(a.risk_factors, dict) and a.risk_factors.get("source") == "COLLECTION_EVENT_RANDOM_AUDIT":
                assert a.auditor_id is None, f"Audit {a.id} should not have worker as auditor"

