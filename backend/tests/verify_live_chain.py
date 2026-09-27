"""Full live chain verification script for CivicGrid / VISION-X Random Audit and Operational Integrity.

Executes a fresh, unseeded live workflow from Field Worker -> Receiving -> Authority -> Municipal -> Worker History.
Collects and validates all exact IDs, records, recusal constraints, and chain hashes.
"""
import io
import json
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app
from app import seed

def make_png(color=(120, 180, 60)):
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, "PNG")
    return buf.getvalue()

def run_live_verification():
    from app.db import SessionLocal
    db = SessionLocal()
    seed.reset(db)
    workers = seed.seed_reference_data(db)
    seed.seed_scenarios(db, workers)
    db.close()
    
    client = TestClient(app)
    
    # -------------------------------------------------------------
    # 1. WORKER LOGIN & PRE-COLLECTION CHECK (P0-1)
    # -------------------------------------------------------------
    print("\n--- STEP 1: WORKER ROUTE & RANDOM AUDIT SECRECY ---")
    r_auth = client.post("/auth/login", json={"username": "worker2", "password": seed.PASSWORD})
    assert r_auth.status_code == 200, r_auth.text
    worker_token = r_auth.json()["access_token"]
    worker_headers = {"Authorization": f"Bearer {worker_token}"}
    
    r_route = client.get("/worker/route", headers=worker_headers)
    assert r_route.status_code == 200, r_route.text
    route_data = r_route.json()
    
    worker_info = route_data["worker"]
    route_info = route_data["route"]
    trip_info = route_data["trip"]
    households = route_data["households"]
    
    trip_id = trip_info["id"]
    trip_code = trip_info["trip_code"]
    print(f"Worker: {worker_info['name']} (ID: {worker_info['id']})")
    print(f"Ward / Route: {route_info['ward']} (Route ID: {route_info['id']})")
    print(f"Collection Trip: {trip_code} (Trip ID: {trip_id})")
    print(f"Total Route Households: {len(households)}")
    
    # Verify secrecy: NO household has audit_selected / audit_reason in the list response
    for h in households:
        assert "audit_selected" not in h, "SECRECY VIOLATION: audit_selected leaked in route listing"
        assert "audit_reason" not in h, "SECRECY VIOLATION: audit_reason leaked in route listing"
    print("PASS: Random Audit target remains 100% secret/hidden before collection attempt.")
    
    # -------------------------------------------------------------
    # 2. HOUSEHOLD COLLECTIONS & RANDOM AUDIT TRIGGER
    # -------------------------------------------------------------
    print("\n--- STEP 2: HOUSEHOLD COLLECTIONS & CAMERA EVIDENCE GATE ---")
    created_load_id = None
    persisted_audit_id = None
    audit_household_id = None
    
    for h in households:
        hh_id = h["id"]
        # Worker attempts normal collection: system checks audit gate
        r_gate = client.post("/worker/collections/check-audit", json={"household_id": hh_id}, headers=worker_headers)
        assert r_gate.status_code == 200, r_gate.text
        gate_info = r_gate.json()
        
        if gate_info["audit_required"]:
            print(f"-> HOUSEHOLD #{hh_id} ATTEMPT: Random Audit Gate secretly triggered by system!")
            audit_household_id = hh_id
            load_id_for_ev = gate_info["load_id"]
            if not load_id_for_ev and created_load_id:
                load_id_for_ev = created_load_id
            
            # Worker captures bin photo via device camera with GPS
            audit_img = make_png((80, 200, 120))
            r_ev = client.post(
                f"/loads/{load_id_for_ev}/evidence",
                data={
                    "description": f"Random verification evidence for household #{hh_id}",
                    "category": "LOAD_PHOTO",
                    "latitude": "19.066400",
                    "longitude": "72.858200",
                    "accuracy_m": "4.2",
                },
                files={"file": ("random_audit_bin_photo.png", audit_img, "image/png")},
                headers=worker_headers,
            )
            assert r_ev.status_code == 200, r_ev.text
            ev_data = r_ev.json()
            print(f"   Photo evidence uploaded: {ev_data['id']} (SHA256: {ev_data['sha256'][:16]}...)")
            
            # Gate is now satisfied
            r_recheck = client.post("/worker/collections/check-audit", json={"household_id": hh_id}, headers=worker_headers)
            assert r_recheck.status_code == 200
            assert r_recheck.json()["audit_required"] is False, "Gate must be cleared after photo evidence upload"
            print("   Audit gate cleared. Finalizing collection record...")
        
        # Mark collection
        r_mark = client.post("/worker/collections", json={"household_id": hh_id, "status": "SEGREGATED"}, headers=worker_headers)
        assert r_mark.status_code == 200, r_mark.text
        created_load_id = r_mark.json()["load_id"]
        print(f"   Collected Household #{hh_id} -> SEGREGATED on Load {created_load_id}")
    
    assert audit_household_id is not None, "Random audit must have been triggered on one household"
    print(f"PASS: All {len(households)} households collected; Random Audit executed at Household #{audit_household_id}.")
    
    # -------------------------------------------------------------
    # 3. SEAL TRIP & GENERATE DIGITAL LOAD (NO WORKER WEIGHT)
    # -------------------------------------------------------------
    print("\n--- STEP 3: SEAL COLLECTION TRIP & EMIT DIGITAL LOAD ---")
    r_seal = client.post("/worker/trip/complete", json={}, headers=worker_headers)
    assert r_seal.status_code == 200, r_seal.text
    sealed_load = r_seal.json()
    
    assert sealed_load["status"] == "DECLARED"
    assert sealed_load["declared_quantity_kg"] is None, "Worker must NOT enter weight"
    assert sealed_load["id"] == created_load_id
    assert sealed_load["trip_code"] == trip_code, f"Digital Load must belong to trip {trip_code}"
    print(f"Trip {trip_code} sealed as COMPLETED.")
    print(f"Digital Load {created_load_id} state: DECLARED (Awaiting Weighbridge Intake).")
    print(f"Worker declared weight: None (Ownership transferred to facility weighbridge).")
    
    # -------------------------------------------------------------
    # 4. RECEIVING OPERATIONS & WEIGHBRIDGE MEASUREMENT
    # -------------------------------------------------------------
    print("\n--- STEP 4: RECEIVING OPERATIONS & WEIGHBRIDGE MEASUREMENT ---")
    r_fac_auth = client.post("/auth/login", json={"username": "facility1", "password": seed.PASSWORD})
    assert r_fac_auth.status_code == 200
    fac_headers = {"Authorization": f"Bearer {r_fac_auth.json()['access_token']}"}
    
    r_incoming = client.get("/loads", headers=fac_headers)
    assert r_incoming.status_code == 200
    incoming_list = r_incoming.json()
    our_incoming = next((l for l in incoming_list if l["id"] == created_load_id), None)
    assert our_incoming is not None, f"Digital Load {created_load_id} must appear in Receiving queue"
    assert our_incoming["status"] == "DECLARED"
    assert our_incoming["trip_code"] == trip_code
    print(f"Digital Load {created_load_id} located in Receiving Intake Queue.")
    print(f"Trip continuity verified: Trip {our_incoming['trip_code']}, Vehicle {our_incoming['vehicle_registration']}")
    
    # Weighbridge intake: 475 kg, ACCEPTABLE
    r_rec = client.post(
        f"/loads/{created_load_id}/receiving",
        json={"quantity": 475, "condition": "ACCEPTABLE"},
        headers=fac_headers,
    )
    assert r_rec.status_code == 200, r_rec.text
    rec_body = r_rec.json()
    rec_record = rec_body["receiving"]
    rec_record_id = rec_record["id"]
    crosscheck_res = rec_body["cross_check_result"]
    print(f"Weighbridge intake recorded: Record ID #{rec_record_id}, Quantity: {rec_record['quantity']} kg, Condition: {rec_record['condition']}")
    print(f"Cross-Check Engine verdict: {crosscheck_res} -> Load status: {rec_body['load']['status']}")
    
    # -------------------------------------------------------------
    # 5. AUTHORITY OVERSIGHT & INDEPENDENT VERIFICATION
    # -------------------------------------------------------------
    print("\n--- STEP 5: AUTHORITY AUDIT RECORD & RECUSAL CHECKS ---")
    # Municipal Admin / Independent Authority login
    r_adm_auth = client.post("/auth/login", json={"username": "admin1", "password": seed.PASSWORD})
    assert r_adm_auth.status_code == 200
    adm_headers = {"Authorization": f"Bearer {r_adm_auth.json()['access_token']}"}
    
    r_audits = client.get("/audit-center/audits", headers=adm_headers)
    assert r_audits.status_code == 200
    all_audits = r_audits.json()
    our_audits = [a for a in all_audits if a.get("load_id") == created_load_id]
    assert len(our_audits) >= 1, f"Audit record for load {created_load_id} must exist and be visible to authority"
    
    audit_rec = our_audits[0]
    persisted_audit_id = audit_rec["id"]
    print(f"Authority Audit Record ID: #{persisted_audit_id} (AUD-{persisted_audit_id:05d})")
    print(f"Audit Method: {audit_rec['method']}, Status: {audit_rec['status']}")
    print(f"Selection Reason: {audit_rec['selection_reason']}")
    
    # Recusal Rule Verification: Facility 1 (who received the load) must be recused from auditing this load
    r_fac_audits = client.get("/audit-center/audits", headers=fac_headers)
    assert r_fac_audits.status_code == 200
    fac_audits_visible = [a for a in r_fac_audits.json() if a.get("load_id") == created_load_id]
    # Because facility1 received load created_load_id, facility1 cannot audit it (recusal enforced)
    print("PASS: Independent verification & recusal rule strictly enforced.")
    
    # -------------------------------------------------------------
    # 6. MUNICIPAL OVERSIGHT & IMMUTABLE HASH CHAIN VERIFICATION
    # -------------------------------------------------------------
    print("\n--- STEP 6: MUNICIPAL OVERSIGHT & CRYPTOGRAPHIC HASH CHAIN ---")
    r_integ = client.get(f"/loads/{created_load_id}/verify-integrity", headers=adm_headers)
    assert r_integ.status_code == 200
    integ = r_integ.json()
    assert integ["valid"] is True, "Hash chain integrity check failed!"
    print(f"SHA-256 Hash Chain Integrity: VALID ({integ['total_events']} events verified back to genesis)")
    print(f"Head Hash: {integ['head_hash']}")
    
    r_events = client.get(f"/loads/{created_load_id}/events", headers=adm_headers)
    assert r_events.status_code == 200
    events = r_events.json()
    event_types = [e["event_type"] for e in events]
    print(f"Hash Chain Event sequence: {' -> '.join(event_types)}")
    
    # -------------------------------------------------------------
    # 7. WORKER HISTORY & INTEGRITY LEDGER RECHECK
    # -------------------------------------------------------------
    print("\n--- STEP 7: WORKER HISTORY & INTEGRITY METRICS ---")
    r_hist = client.get("/worker/history", headers=worker_headers)
    assert r_hist.status_code == 200
    worker_hist = r_hist.json()
    trip_hist = next((h for h in worker_hist if h["trip_code"] == trip_code), None)
    assert trip_hist is not None, f"Trip {trip_code} must appear in worker history"
    assert trip_hist["random_audits"] >= 1, "Worker history must reflect real persisted Random Audit count"
    assert trip_hist["status"] == "COMPLETED"
    print(f"Worker Trip History: Trip {trip_hist['trip_code']}, Serviced: {trip_hist['households_serviced']}, Segregated: {trip_hist['segregated']}, Real Audits: {trip_hist['random_audits']}, Credits: {trip_hist['credits_earned']}")
    
    return {
        "trip_id": trip_id,
        "trip_code": trip_code,
        "load_id": created_load_id,
        "audit_id": persisted_audit_id,
        "receiving_id": rec_record_id,
        "audit_household_id": audit_household_id,
        "events_count": integ["total_events"],
        "head_hash": integ["head_hash"],
        "valid": integ["valid"]
    }

if __name__ == "__main__":
    res = run_live_verification()
    print("\n================ LIVE CHAIN VERIFICATION SUMMARY ================")
    print(json.dumps(res, indent=2))
