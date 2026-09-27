"""End-to-end operational workflow test — the new Random Audit gate model.

The worker does NOT see which household is selected as the Random Audit target in
the household list.  The selection is revealed only when the worker ATTEMPTS to
collect that specific household via POST /worker/collections/check-audit.

This test verifies the complete chain:
  Worker → (hidden audit gate) → camera evidence → Audit record persisted →
  trip completion → Digital Load for THAT trip → Receiving → cross-check → chain valid.
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import seed
from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


def login(client, username):
    r = client.post("/auth/login", json={"username": username, "password": seed.PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_png(color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


def test_full_operational_rebuild_workflow(client):
    # ------------------------------------------------------------------ setup
    worker_auth = login(client, "worker2")   # Sunita Jadhav, Route 2

    r = client.get("/worker/route", headers=worker_auth)
    assert r.status_code == 200
    route_data = r.json()
    assert route_data["worker"]["name"] == "Sunita Jadhav"
    assert len(route_data["households"]) == 6
    hh_ids = [h["id"] for h in route_data["households"]]

    # P0-1: audit_selected MUST NOT appear in the household list
    for h in route_data["households"]:
        assert "audit_selected" not in h, (
            "audit_selected must not be present in household list — it reveals the target to the worker"
        )
        assert "audit_reason" not in h, (
            "audit_reason must not be present in household list — it reveals the target to the worker"
        )

    trip = route_data["trip"]
    trip_id = trip["id"]
    trip_code = trip["trip_code"]

    # ------------------------------------------------------------------ collect houses one by one; check audit gate for each
    load_id = None
    audit_was_triggered = False
    audit_household_id = None

    for hh_id in hh_ids:
        # ALWAYS call check-audit before recording collection — this is the new protocol
        r = client.post(
            "/worker/collections/check-audit",
            json={"household_id": hh_id},
            headers=worker_auth,
        )
        assert r.status_code == 200, r.text
        gate = r.json()
        assert gate["household_id"] == hh_id

        if gate["audit_required"]:
            # -------- RANDOM AUDIT GATE TRIGGERED --------
            audit_was_triggered = True
            audit_household_id = hh_id
            load_id_for_audit = gate["load_id"]

            # If load doesn't exist yet, collect first to create it, then upload evidence
            # (In real flow, the load is created on first collection attempt before the audit household)
            if load_id_for_audit is None:
                # collect a previous house to create the load first
                # (This shouldn't happen in practice with a seeded route; the audit target
                # won't be the very first household, but guard against edge cases)
                pass

            # Refresh load_id after possible prior collections
            route_now = client.get("/worker/route", headers=worker_auth).json()
            current_load = route_now.get("active_load")
            if current_load:
                load_id_for_audit = current_load["id"]

            # Upload Random Audit evidence (camera photo)
            png_bytes = make_png((100, 200, 50))
            r_ev = client.post(
                f"/loads/{load_id_for_audit}/evidence",
                data={
                    "description": f"Random verification evidence for household #{hh_id}",
                    "category": "LOAD_PHOTO",
                },
                files={"file": ("audit_photo.png", png_bytes, "image/png")},
                headers=worker_auth,
            )
            assert r_ev.status_code == 200, r_ev.text
            ev = r_ev.json()
            assert ev["kind"] == "FILE_EVIDENCE"

            # After evidence upload, re-check audit gate — should now be cleared
            r2 = client.post(
                "/worker/collections/check-audit",
                json={"household_id": hh_id},
                headers=worker_auth,
            )
            assert r2.status_code == 200
            # audit_required should now be False (audit record was created)
            assert r2.json()["audit_required"] is False, (
                "After uploading audit evidence, audit_required must be False so collection can proceed"
            )

        # Proceed to record collection normally
        status = "UNSEGREGATED" if hh_id == hh_ids[4] else "SEGREGATED"
        r = client.post(
            "/worker/collections",
            json={"household_id": hh_id, "status": status},
            headers=worker_auth,
        )
        assert r.status_code == 200, r.text
        load_id = r.json()["load_id"]

    # At least one household should have triggered the audit gate
    assert audit_was_triggered, "The Random Audit gate must have been triggered for one household"
    assert audit_household_id is not None

    # Negative-event evidence for unsegregated household (hh_ids[4])
    neg_png = make_png((250, 100, 10))
    r_neg = client.post(
        f"/loads/{load_id}/evidence",
        data={
            "description": f"Contextual negative-event photo of unsegregated waste at household #{hh_ids[4]}",
            "category": "LOAD_PHOTO",
        },
        files={"file": ("unseg_photo.png", neg_png, "image/png")},
        headers=worker_auth,
    )
    assert r_neg.status_code == 200, r_neg.text

    # ------------------------------------------------------------------ complete trip (no weight entry)
    r = client.post("/worker/trip/complete", json={}, headers=worker_auth)
    assert r.status_code == 200, r.text
    completed_load = r.json()
    assert completed_load["status"] == "DECLARED"
    assert completed_load["declared_quantity_kg"] is None, "Worker must NOT enter weight"
    assert completed_load["id"] == load_id

    # P0-5/P0-6/P0-7: the completed load must belong to the same trip
    assert completed_load.get("trip_code") == trip_code, (
        f"Digital Load must be linked to trip {trip_code}, not a different trip"
    )

    # ------------------------------------------------------------------ Receiving: same load appears in incoming queue
    facility_auth = login(client, "facility1")
    r = client.get("/loads", headers=facility_auth)
    assert r.status_code == 200
    all_loads = r.json()
    incoming_load = next((l for l in all_loads if l["id"] == load_id), None)
    assert incoming_load is not None, f"Digital Load {load_id} must appear in Receiving incoming loads"
    assert incoming_load["status"] == "DECLARED"
    assert incoming_load.get("trip_code") == trip_code

    # ------------------------------------------------------------------ Record weighbridge measurement
    r = client.post(
        f"/loads/{load_id}/receiving",
        json={"quantity": 390, "condition": "ACCEPTABLE"},
        headers=facility_auth,
    )
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["receiving"]["quantity"] == 390
    assert rec["receiving"]["condition"] == "ACCEPTABLE"

    # ------------------------------------------------------------------ Authority: Audit record persisted and visible
    # P0-2: The completed audit must be visible to authority / municipal oversight (admin1)
    admin_auth = login(client, "admin1")
    r_audits = client.get("/audit-center/audits", headers=admin_auth)
    assert r_audits.status_code == 200
    audits = r_audits.json()
    # There should be at least one audit on our load
    load_audits = [a for a in audits if a.get("load_id") == load_id]
    assert len(load_audits) >= 1, (
        f"Authority (admin1) must see a persisted Audit record for load {load_id} from the Random Audit gate"
    )
    audit_record = load_audits[0]
    assert audit_record["method"] == "RANDOM"
    assert audit_record["status"] == "COMPLETED"

    # ------------------------------------------------------------------ Hash chain integrity
    r = client.get(f"/loads/{load_id}/verify-integrity", headers=facility_auth)
    assert r.status_code == 200
    integrity = r.json()
    assert integrity["valid"] is True
    assert integrity["total_events"] >= 7  # LOAD_CREATED + 6x COLLECTION_RECORDED + EVIDENCE_ADDED + LOAD_DECLARED

    # ------------------------------------------------------------------ Worker history reflects real audit count
    r_hist = client.get("/worker/history", headers=worker_auth)
    assert r_hist.status_code == 200
    history = r_hist.json()
    current_trip = next((h for h in history if h["trip_code"] == trip_code), None)
    assert current_trip is not None
    assert current_trip["random_audits"] >= 1, (
        "Worker history must show random_audits >= 1 from real Audit records, not from verification_triggered"
    )
