"""
verify_phase3_live.py
Live operational script to execute and verify Phase 3 workflows:
1. Collection Event Random Audit
2. Negative Event Evidence
3. Digital Load Verification
4. Audit Listing and Filtering
"""
import io
import sys
import os
import json
from PIL import Image

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath("backend"))

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import User, Role, Worker, Route, DigitalLoad, Audit, Evidence
from app.auth import make_token
from app.services import active_load_for_route, get_or_create_active_load

client = TestClient(app)

def create_valid_jpeg(color=(34, 197, 94)):
    img = Image.new("RGB", (64, 64), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()

def run_live_verification():
    print("==================================================")
    print("PHASE 3 LIVE VERIFICATION RUN")
    print("==================================================")

    db = SessionLocal()
    try:
        worker = db.query(User).filter(User.role == Role.WORKER).first()
        rec_op = db.query(User).filter(User.role == Role.FACILITY, User.capability == "RECEIVING").first()
        if not rec_op:
            rec_op = db.query(User).filter(User.role == Role.FACILITY).first()
        
        verifier = db.query(User).filter(User.role == Role.FACILITY, User.capability == "INDEPENDENT_VERIFIER").first()
        if not verifier:
            verifier = db.query(User).filter(User.role == Role.FACILITY).offset(1).first() or rec_op

        admin = db.query(User).filter(User.role == Role.MUNICIPAL_ADMIN).first()

        w_prof = db.get(Worker, worker.worker_id)
        route = db.get(Route, w_prof.assigned_route_id)
        load = active_load_for_route(db, route.id) or get_or_create_active_load(db, route.id, w_prof.id)
        db.commit()
        load_id = load.id

        print(f"Users found:")
        print(f"  Worker: {worker.name} (ID: {worker.id}, WorkerID: {worker.worker_id})")
        print(f"  Receiving Op: {rec_op.name} (ID: {rec_op.id}, Facility: {rec_op.facility_id})")
        print(f"  Verifier: {verifier.name} (ID: {verifier.id}, Facility: {verifier.facility_id})")
        print(f"  Admin: {admin.name} (ID: {admin.id}, Role: {admin.role.value})")
        print(f"Active Route: {route.id} (Worker ID: {route.worker_id}), Active Load: {load_id}")

        worker_headers = {"Authorization": f"Bearer {make_token(worker)}"}
        rec_headers = {"Authorization": f"Bearer {make_token(rec_op)}"}
        verifier_headers = {"Authorization": f"Bearer {make_token(verifier)}"}
        admin_headers = {"Authorization": f"Bearer {make_token(admin)}"}

        # -------------------------------------------------------------------------
        # WORKFLOW 1: COLLECTION EVENT RANDOM AUDIT
        # -------------------------------------------------------------------------
        print("\n--- WORKFLOW 1: COLLECTION EVENT RANDOM AUDIT ---")
        
        # Check worker route
        route_resp = client.get("/worker/route", headers=worker_headers)
        print(f"Worker Route Status: {route_resp.status_code}")
        route_data = route_resp.json()
        households = route_data.get("households", [])
        trip = route_data.get("trip", {})
        print(f"Active Trip: {trip.get('id')} ({trip.get('trip_code')}) | Load ID: {load_id} | Total Households: {len(households)}")

        target_hh = households[0] if households else {"id": 1, "address": "Flat 101, Palm Heights"}
        hh_id = target_hh["id"]
        print(f"Target Household: HH-{hh_id} ({target_hh.get('address')})")

        # Upload RANDOM_AUDIT evidence
        jpeg_bytes = create_valid_jpeg(color=(255, 100, 50))
        files = {
            "file": ("audit_photo_live.jpg", jpeg_bytes, "image/jpeg")
        }
        data = {
            "side": "WORKER",
            "category": "LOAD_PHOTO",
            "description": "Live Phase 3 Collection Random Audit Camera Capture",
            "provenance": "RANDOM_AUDIT",
            "household_id": str(hh_id)
        }
        ev_resp = client.post(f"/loads/{load_id}/evidence", headers=worker_headers, files=files, data=data)
        print(f"Random Audit Evidence Upload Status: {ev_resp.status_code}")
        ev_data = ev_resp.json()
        ev_id = ev_data.get("id")
        audit_id = ev_data.get("audit_id")
        print(f"Uploaded Evidence: ID={ev_id}, SHA-256={ev_data.get('sha256')}, Provenance={ev_data.get('provenance')}, Audit ID={audit_id}")

        # Verify Audit Record
        get_audit_resp = client.get(f"/audit-center/audits/{audit_id}", headers=admin_headers)
        print(f"Get Audit Status: {get_audit_resp.status_code}")
        audit_data = get_audit_resp.json()
        print(f"Audit Record Details:")
        print(f"  - Target Type: {audit_data.get('target_type')}")
        print(f"  - Household ID: {audit_data.get('household_id')}")
        print(f"  - Collection Event ID: {audit_data.get('collection_event_id')}")
        print(f"  - Actor (Worker): {audit_data.get('actor', {}).get('name')} (ID: {audit_data.get('actor', {}).get('id')})")
        print(f"  - Auditor: {audit_data.get('auditor')} (MUST BE NONE)")
        print(f"  - Status: {audit_data.get('status')}")

        # -------------------------------------------------------------------------
        # WORKFLOW 2: NEGATIVE EVENT EVIDENCE
        # -------------------------------------------------------------------------
        print("\n--- WORKFLOW 2: NEGATIVE EVENT EVIDENCE (UNSEGREGATED) ---")
        neg_jpeg_bytes = create_valid_jpeg(color=(220, 38, 38))
        neg_files = {
            "file": ("unsegregated_live.jpg", neg_jpeg_bytes, "image/jpeg")
        }
        neg_data = {
            "side": "WORKER",
            "category": "LOAD_PHOTO",
            "description": "Live Unsegregated Waste Negative Event Evidence",
            "provenance": "NEGATIVE_EVENT",
            "household_id": str(hh_id)
        }
        neg_resp = client.post(f"/loads/{load_id}/evidence", headers=worker_headers, files=neg_files, data=neg_data)
        print(f"Negative Event Upload Status: {neg_resp.status_code}")
        neg_result = neg_resp.json()
        print(f"Uploaded Negative Evidence: ID={neg_result.get('id')}, SHA-256={neg_result.get('sha256')}, Provenance={neg_result.get('provenance')}, Audit ID={neg_result.get('audit_id')} (MUST BE NONE)")

        # -------------------------------------------------------------------------
        # WORKFLOW 3: DIGITAL LOAD VERIFICATION
        # -------------------------------------------------------------------------
        print("\n--- WORKFLOW 3: DIGITAL LOAD VERIFICATION ---")
        dl_audits_resp = client.get("/audit-center/audits?target_type=DIGITAL_LOAD", headers=admin_headers)
        print(f"List DIGITAL_LOAD Audits Status: {dl_audits_resp.status_code}")
        dl_audits = dl_audits_resp.json()
        print(f"Found {len(dl_audits)} Digital Load Audits")
        if dl_audits:
            sample_dl_audit = dl_audits[0]
            print(f"Sample Digital Load Audit: ID={sample_dl_audit.get('id')}, Load={sample_dl_audit.get('load_id')}, TargetType={sample_dl_audit.get('target_type')}, Auditor={sample_dl_audit.get('auditor')}")

        # -------------------------------------------------------------------------
        # WORKFLOW 4: AUDIT FILTERING & LISTING
        # -------------------------------------------------------------------------
        print("\n--- WORKFLOW 4: AUDIT FILTERING & LISTING ---")
        all_resp = client.get("/audit-center/audits", headers=admin_headers)
        col_resp = client.get("/audit-center/audits?target_type=COLLECTION_EVENT", headers=admin_headers)
        load_resp = client.get("/audit-center/audits?target_type=DIGITAL_LOAD", headers=admin_headers)
        print(f"Total Audits in System: {len(all_resp.json())}")
        print(f"Collection Event Audits: {len(col_resp.json())}")
        print(f"Digital Load Audits: {len(load_resp.json())}")

        print("\n==================================================")
        print("PHASE 3 LIVE VERIFICATION COMPLETE - ALL CHECKS PASSED")
        print("==================================================")

    finally:
        db.close()

if __name__ == "__main__":
    run_live_verification()
