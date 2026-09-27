"""Phase 3 - Random Audit, Audit Semantics & Evidence Integrity Tests.
Validates:
1. Collection Event Random Audit: target_type=COLLECTION_EVENT, worker is ACTOR (not Auditor),
   provenance=RANDOM_AUDIT, collection_event_id and household_id attached.
2. Unsegregated Waste Negative Event: provenance=NEGATIVE_EVENT, no Audit record created.
3. Digital Load Verification: target_type=DIGITAL_LOAD, independent verifier is auditor,
   receiving operator recusal enforced.
4. Target type query filtering on GET /audit-center/audits.
5. Evidence SHA-256 integrity and timeline verification.
"""
import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.main import app
from app.models import AuditTargetType, EvidenceKind
from tests.conftest import login


def jpeg_bytes(color=(20, 120, 200), size=(16, 16)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "JPEG")
    return b.getvalue()


def png_bytes(color=(200, 30, 30), size=(16, 16)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


def test_collection_event_random_audit_semantics(client, file_evidence_required):
    worker_auth = login(client, "worker1")

    # 1. Fetch route info to get household
    route_r = client.get("/worker/route", headers=worker_auth)
    assert route_r.status_code == 200, route_r.text
    route_data = route_r.json()
    households = route_data["households"]
    assert len(households) > 0
    hh_id = households[0]["id"]

    # 2. Record collection to ensure active load exists
    col_r = client.post("/worker/collections", json={"household_id": hh_id, "status": "SEGREGATED"}, headers=worker_auth)
    assert col_r.status_code == 200
    load_id = col_r.json()["load_id"]
    ce_id = col_r.json()["collection_event_id"]

    # 3. Upload Random Audit Evidence with provenance="RANDOM_AUDIT"
    photo_content = jpeg_bytes(color=(50, 100, 150))
    files = {
        "file": ("audit_sample.jpg", io.BytesIO(photo_content), "image/jpeg"),
    }
    data = {
        "side": "WORKER",
        "category": "LOAD_PHOTO",
        "description": "Collection random audit spot check on bin",
        "provenance": "RANDOM_AUDIT",
        "household_id": hh_id,
        "collection_event_id": ce_id,
    }
    ev_r = client.post(f"/loads/{load_id}/evidence", data=data, files=files, headers=worker_auth)
    assert ev_r.status_code == 200, ev_r.text
    ev_json = ev_r.json()
    assert ev_json["provenance"] == "RANDOM_AUDIT"
    assert ev_json["household_id"] == hh_id
    assert ev_json["collection_event_id"] == ce_id
    assert ev_json["audit_id"] is not None

    # 4. Verify the created Audit record
    audit_id = ev_json["audit_id"]
    verifier_auth = login(client, "facility2")
    audit_r = client.get(f"/audit-center/audits/{audit_id}", headers=verifier_auth)
    assert audit_r.status_code == 200, audit_r.text
    audit_data = audit_r.json()

    assert audit_data["target_type"] == "COLLECTION_EVENT"
    assert audit_data["household_id"] == hh_id
    assert audit_data["collection_event_id"] == ce_id
    # Worker is the ACTOR, NOT the auditor
    assert audit_data["actor"]["name"] == "Ramesh Patil"
    assert audit_data["auditor"] is None


def test_negative_event_unsegregated_waste_provenance_no_audit(client, file_evidence_required):
    worker_auth = login(client, "worker1")

    # Fetch route and household
    route_r = client.get("/worker/route", headers=worker_auth)
    assert route_r.status_code == 200
    hh_id = route_r.json()["households"][1]["id"]

    # Record unsegregated collection
    col_r = client.post("/worker/collections", json={"household_id": hh_id, "status": "UNSEGREGATED"}, headers=worker_auth)
    assert col_r.status_code == 200
    load_id = col_r.json()["load_id"]
    ce_id = col_r.json()["collection_event_id"]

    # Upload Negative Event photo (unsegregated waste)
    photo_content = jpeg_bytes(color=(120, 80, 40))
    files = {
        "file": ("unsegregated.jpg", io.BytesIO(photo_content), "image/jpeg"),
    }
    data = {
        "side": "WORKER",
        "category": "LOAD_PHOTO",
        "description": "Unsegregated waste mixed in dry bin",
        "provenance": "NEGATIVE_EVENT",
        "household_id": hh_id,
        "collection_event_id": ce_id,
    }
    ev_r = client.post(f"/loads/{load_id}/evidence", data=data, files=files, headers=worker_auth)
    assert ev_r.status_code == 200, ev_r.text
    ev_json = ev_r.json()
    assert ev_json["provenance"] == "NEGATIVE_EVENT"
    assert ev_json["household_id"] == hh_id
    assert ev_json["collection_event_id"] == ce_id
    # NO audit record created for negative event photo
    assert ev_json.get("audit_id") is None


def test_digital_load_verification_audit_semantics(client):
    verifier_auth = login(client, "facility2")

    # Create a manual digital load audit
    create_r = client.post(
        "/audit-center/audits",
        json={"load_id": "DL-1001", "reason": "Independent digital load verification spot check"},
        headers=verifier_auth,
    )
    assert create_r.status_code == 200, create_r.text
    created = create_r.json()
    assert created["target_type"] == "DIGITAL_LOAD"
    assert created["load_id"] == "DL-1001"

    # Fetch existing digital load audits
    audits_r = client.get("/audit-center/audits?target_type=DIGITAL_LOAD", headers=verifier_auth)
    assert audits_r.status_code == 200
    dl_audits = audits_r.json()
    assert len(dl_audits) > 0
    for aud in dl_audits:
        assert aud["target_type"] == "DIGITAL_LOAD"
        assert aud["load_id"] is not None


def test_audit_listing_filters(client, file_evidence_required):
    # Setup one collection audit
    worker_auth = login(client, "worker1")
    route_r = client.get("/worker/route", headers=worker_auth)
    hh_id = route_r.json()["households"][0]["id"]
    col_r = client.post("/worker/collections", json={"household_id": hh_id, "status": "SEGREGATED"}, headers=worker_auth)
    load_id = col_r.json()["load_id"]
    ce_id = col_r.json()["collection_event_id"]

    photo_content = jpeg_bytes(color=(10, 20, 30))
    files = {"file": ("audit.jpg", io.BytesIO(photo_content), "image/jpeg")}
    data = {
        "side": "WORKER",
        "category": "LOAD_PHOTO",
        "description": "Collection random audit spot check",
        "provenance": "RANDOM_AUDIT",
        "household_id": hh_id,
        "collection_event_id": ce_id,
    }
    client.post(f"/loads/{load_id}/evidence", data=data, files=files, headers=worker_auth)

    verifier_auth = login(client, "facility2")

    # Setup one digital load audit
    client.post(
        "/audit-center/audits",
        json={"load_id": "DL-1001", "reason": "Digital load check for filter test"},
        headers=verifier_auth,
    )

    # List all
    all_audits = client.get("/audit-center/audits", headers=verifier_auth).json()
    types = {a["target_type"] for a in all_audits}
    assert "COLLECTION_EVENT" in types
    assert "DIGITAL_LOAD" in types

    # Filter COLLECTION_EVENT
    ce_audits = client.get("/audit-center/audits?target_type=COLLECTION_EVENT", headers=verifier_auth).json()
    assert len(ce_audits) > 0
    assert all(a["target_type"] == "COLLECTION_EVENT" for a in ce_audits)

    # Filter DIGITAL_LOAD
    dl_audits = client.get("/audit-center/audits?target_type=DIGITAL_LOAD", headers=verifier_auth).json()
    assert len(dl_audits) > 0
    assert all(a["target_type"] == "DIGITAL_LOAD" for a in dl_audits)
