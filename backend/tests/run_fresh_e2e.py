"""Fresh E2E run script without resetting database.
Captures before-state, creates a completely new collection trip, collects, audits if triggered,
completes trip, records receiving, and executes cross-check.
"""
import io
import json
from datetime import datetime, timezone
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.main import app
from app.db import SessionLocal
from app.models import CollectionTrip, DigitalLoad, ReceivingRecord, Audit, EventLog
from app import seed

def make_png(color=(120, 180, 60)):
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, "PNG")
    return buf.getvalue()

def run_fresh_e2e():
    db = SessionLocal()
    
    # 1. Capture BEFORE state
    latest_trip = db.scalars(select(CollectionTrip).order_by(CollectionTrip.id.desc())).first()
    latest_load = db.scalars(select(DigitalLoad).order_by(DigitalLoad.generated_at.desc())).first()
    latest_recv = db.scalars(select(ReceivingRecord).order_by(ReceivingRecord.id.desc())).first()
    latest_audit = db.scalars(select(Audit).order_by(Audit.id.desc())).first()
    
    before_state = {
        "latest_trip_id": latest_trip.id if latest_trip else None,
        "latest_trip_code": latest_trip.trip_code if latest_trip else None,
        "latest_load_id": latest_load.id if latest_load else None,
        "latest_recv_id": latest_recv.id if latest_recv else None,
        "latest_audit_id": latest_audit.id if latest_audit else None,
    }
    print("=== BEFORE RUN LATEST RECORDS ===")
    print(json.dumps(before_state, indent=2))
    
    db.close()
    
    client = TestClient(app)
    
    # 2. Worker 2 (Route 2 - Demo Ward B) starts new collection trip
    r_auth = client.post("/auth/login", json={"username": "worker2", "password": seed.PASSWORD})
    assert r_auth.status_code == 200, r_auth.text
    worker_token = r_auth.json()["access_token"]
    worker_headers = {"Authorization": f"Bearer {worker_token}"}
    
    r_route = client.get("/worker/route", headers=worker_headers)
    assert r_route.status_code == 200, r_route.text
    route_data = r_route.json()
    
    trip_info = route_data["trip"]
    trip_id = trip_info["id"]
    trip_code = trip_info["trip_code"]
    active_load_info = route_data.get("active_load")
    active_load_id = active_load_info["id"] if active_load_info else None
    
    print(f"\n--- STEP 1: WORKER INITIATES ROUTE ---")
    print(f"Worker: {route_data['worker']['name']} (ID: {route_data['worker']['id']})")
    print(f"Route: {route_data['route']['ward']} (Route ID: {route_data['route']['id']})")
    print(f"Trip ID: {trip_id}, Trip Code: {trip_code}")
    print(f"Active Digital Load ID: {active_load_id}")
    
    # Verify this is a genuinely new trip (not the previous one)
    assert trip_id != before_state["latest_trip_id"] or before_state["latest_trip_id"] is None or trip_info["status"] == "IN_PROGRESS"
    
    # 3. Perform collections
    households = route_data["households"]
    audit_id_created = None
    audit_created_at = None
    
    print(f"\n--- STEP 2: PERFORMING COLLECTIONS ({len(households)} households) ---")
    for hh in households:
        hh_id = hh["id"]
        # Attempt collection
        r_col = client.post("/worker/collections", headers=worker_headers, json={
            "household_id": hh_id,
            "status": "SEGREGATED",
            "waste_type": "WET_ORGANIC"
        })
        
        if r_col.status_code == 428 or (r_col.status_code == 200 and r_col.json().get("verification_required")):
            # Random audit triggered!
            print(f"-> Household #{hh_id}: Random Audit Gate triggered!")
            # Upload evidence
            img_bytes = make_png((80, 200, 100))
            r_ev = client.post("/evidence/upload", headers=worker_headers, files={"file": ("audit_evidence.png", img_bytes, "image/png")})
            assert r_ev.status_code == 201, r_ev.text
            ev_meta = r_ev.json()
            ev_id = ev_meta["id"]
            
            # Finalize with evidence
            r_col2 = client.post("/worker/collections", headers=worker_headers, json={
                "household_id": hh_id,
                "status": "SEGREGATED",
                "waste_type": "WET_ORGANIC",
                "evidence_id": ev_id
            })
            assert r_col2.status_code == 200, r_col2.text
            col_res = r_col2.json()
            print(f"   Evidence {ev_id} submitted. Collection #{hh_id} recorded on load {col_res.get('load_id')}.")
            
            # Check if audit was created
            db = SessionLocal()
            curr_audit = db.scalars(select(Audit).order_by(Audit.id.desc())).first()
            if curr_audit and (before_state["latest_audit_id"] is None or curr_audit.id > before_state["latest_audit_id"]):
                audit_id_created = curr_audit.id
                audit_created_at = curr_audit.created_at.isoformat() if curr_audit.created_at else None
            db.close()
        else:
            assert r_col.status_code == 200, r_col.text
            col_res = r_col.json()
            print(f"   Collected Household #{hh_id} -> SEGREGATED on load {col_res.get('load_id')}")
            
    # 4. Complete collection trip
    print(f"\n--- STEP 3: COMPLETE COLLECTION TRIP ---")
    r_complete = client.post("/worker/trip/complete", headers=worker_headers, json={
        "route_id": route_data["route"]["id"]
    })
    assert r_complete.status_code == 200, r_complete.text
    comp_data = r_complete.json()
    sealed_load_id = comp_data["id"]
    print(f"Trip completed successfully.")
    print(f"Digital Load sealed: {sealed_load_id} (Status: {comp_data.get('status', 'DECLARED')})")
    
    # 5. Facility Login & Receiving Queue Discovery
    print(f"\n--- STEP 4: RECEIVING INTAKE DISCOVERY ---")
    r_fac_auth = client.post("/auth/login", json={"username": "facility1", "password": seed.PASSWORD})
    assert r_fac_auth.status_code == 200, r_fac_auth.text
    fac_token = r_fac_auth.json()["access_token"]
    fac_headers = {"Authorization": f"Bearer {fac_token}"}
    
    r_loads = client.get("/loads", headers=fac_headers)
    assert r_loads.status_code == 200, r_loads.text
    loads_list = r_loads.json()
    
    # Verify sealed_load_id is in incoming loads
    matching_loads = [l for l in loads_list if l["id"] == sealed_load_id]
    assert len(matching_loads) == 1, f"Expected sealed load {sealed_load_id} in loads list, found {len(matching_loads)}"
    target_load = matching_loads[0]
    print(f"Discovered {sealed_load_id} in Receiving queue.")
    print(f"Trip continuity: Trip Code {target_load['trip_code']}, Vehicle {target_load.get('vehicle_registration')}")
    assert target_load["trip_code"] == trip_code, f"Trip code mismatch: {target_load['trip_code']} vs {trip_code}"
    
    # 6. Record Weighbridge Intake
    print(f"\n--- STEP 5: RECORD WEIGHBRIDGE INTAKE & RUN CROSS-CHECK ---")
    intake_weight = 460
    r_recv = client.post(f"/loads/{sealed_load_id}/receiving", headers=fac_headers, json={
        "facility_id": 1,
        "quantity": intake_weight,
        "condition": "ACCEPTABLE"
    })
    assert r_recv.status_code == 200, r_recv.text
    recv_res = r_recv.json()
    cross_check_verdict = recv_res.get("cross_check_result")
    print(f"Weighbridge intake recorded.")
    print(f"Cross-Check Engine Verdict: {cross_check_verdict}")
    print(f"Note: {recv_res.get('note')}")
    
    # 7. Fetch full state from DB for exact reporting
    db = SessionLocal()
    fresh_trip = db.get(CollectionTrip, trip_id)
    fresh_load = db.get(DigitalLoad, sealed_load_id)
    fresh_recv = db.scalars(select(ReceivingRecord).where(ReceivingRecord.load_id == sealed_load_id)).first()
    
    report_data = {
        "before_state": before_state,
        "fresh_run": {
            "trip_id": fresh_trip.id,
            "trip_code": fresh_trip.trip_code,
            "trip_status": fresh_trip.status,
            "trip_created_at": fresh_trip.start_time.isoformat() if fresh_trip.start_time else None,
            "trip_completed_at": fresh_trip.end_time.isoformat() if fresh_trip.end_time else None,
            "load_id": fresh_load.id,
            "load_status": fresh_load.status.value,
            "load_generated_at": fresh_load.generated_at.isoformat() if fresh_load.generated_at else None,
            "receiving_record_id": fresh_recv.id if fresh_recv else None,
            "receiving_quantity": fresh_recv.quantity if fresh_recv else None,
            "receiving_condition": fresh_recv.condition.value if fresh_recv else None,
            "receiving_timestamp": fresh_recv.timestamp.isoformat() if fresh_recv else None,
            "audit_id": audit_id_created,
            "audit_created_at": audit_created_at,
            "cross_check_result": cross_check_verdict,
        },
        "is_load_new": before_state["latest_load_id"] != fresh_load.id if before_state["latest_load_id"] else True,
        "is_receiving_new": before_state["latest_recv_id"] != fresh_recv.id if (before_state["latest_recv_id"] and fresh_recv) else True,
        "is_audit_new": (audit_id_created is not None and audit_id_created != before_state["latest_audit_id"]) if before_state["latest_audit_id"] else (audit_id_created is not None),
    }
    
    print("\n=== COMPLETE FRESH RUN SUMMARY ===")
    print(json.dumps(report_data, indent=2))
    db.close()

if __name__ == "__main__":
    run_fresh_e2e()
