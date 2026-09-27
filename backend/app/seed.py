"""Seed script:  python -m app.seed [--reset] [--if-empty]

Everything that touches loads/discrepancies goes through the SAME service functions the API uses,
so every seeded event_log row is genuinely hash-chained (verify-integrity is valid on a fresh seed).

Phase 1 adds SYNTHETIC geodata: 3 demo wards ("Demo Ward A/B/C" - NOT official boundaries), located households,
facilities, route paths and a handful of demo sanitation tickets. Sanitation events are seeded AFTER the load scenarios
so the load event ids (DL-1002's receiving record is event 19) are unchanged.

Exactly 3 load scenarios:
  DL-1001  clean load          - declaration and receiving record agree -> MATCH, no discrepancy
  DL-1002  MAIN DEMO PATH      - quantity shortfall, left at FLAGGED so it can be walked to CLOSED live
  DL-1003  receiving rejection - STREAM discrepancy (facility marks it unacceptable), seeded at INVESTIGATING
"""
from __future__ import annotations

import sys
from datetime import timedelta

from sqlalchemy import select, text

from . import geo, resolution, sanitation
from .auth import hash_password
from .db import SessionLocal, engine
from .hashchain import append_event, list_events, verify_chain
from .models import (
    Audit, AuditMethod, AuditStatus, AuditTargetType, Base, CollectionStatus, CollectionTrip, Condition,
    DigitalLoad, DiscrepancyEvent, DiscrepancyStatus, DiscrepancyType, Facility, Household, IssueType,
    LoadStatus, ProcessingMethod, ProcessingRecord, ProcessingStatus, ReceivingRecord, Role, Route,
    TicketStatus, TripCrew, User, Vehicle, WasteStream, Worker, utcnow,
)
from .services import create_receiving_record, declare_load, record_collection

PASSWORD = "demo123"

# (ward label, worker name, [(owner, lng, lat), ...]).  Coordinates are SYNTHETIC and lie inside the matching demo ward.
ROUTES = [
    ("Demo Ward A", "Ramesh Patil", [
        ("Anita Deshmukh", 72.858, 19.066), ("Farid Khan", 72.861, 19.070), ("Meera Iyer", 72.864, 19.073),
        ("Joseph D'Souza", 72.867, 19.077), ("Kavita Rao", 72.870, 19.080), ("Suresh Nair", 72.873, 19.084)]),
    ("Demo Ward B", "Sunita Jadhav", [
        ("Priya Menon", 72.890, 19.064), ("Rahul Shah", 72.895, 19.068), ("Nasreen Ansari", 72.899, 19.072),
        ("Vikram Chauhan", 72.903, 19.076), ("Leela Pillai", 72.907, 19.081), ("Arjun Kulkarni", 72.900, 19.086)]),
    ("Demo Ward C", "Imran Shaikh", [
        ("Sneha Kadam", 72.868, 19.106), ("Dilip Mehta", 72.874, 19.110), ("Rekha Gupta", 72.880, 19.114),
        ("Anwar Sayyed", 72.886, 19.118), ("Pooja Bhosale", 72.892, 19.112), ("Manoj Tiwari", 72.896, 19.105)]),
]
SOCIETIES = ["Shanti Nagar CHS", "Lotus Heights", "Sai Krupa Apartments", "Green Park Society", "Harmony Towers", "Ocean View CHS"]
CREDITS = [120, 95, 60, 140, 30, 75, 110, 85, 45, 90, 20, 65, 130, 55, 100, 70, 35, 80]
# (id, name, kind, lng, lat) - SYNTHETIC locations inside Demo Wards B, A, C
FACILITIES = [
    (1, "Eastern Processing Facility", "Processing / transfer", 72.904, 19.066),
    (2, "Western Transfer Station", "Transfer", 72.856, 19.072),
    (3, "Northern Compost Unit", "Organic / compost", 72.872, 19.122),
]

VEHICLES = [
    (1, "MH-01-AB-1234", "COMPACTOR", 5000, "ACTIVE", "Demo Ward A"),
    (2, "MH-01-CD-5678", "COMPACTOR", 5000, "ACTIVE", "Demo Ward B"),
    (3, "MH-01-EF-9012", "TIPPER", 3500, "ACTIVE", "Demo Ward C"),
]


def reset(db) -> None:
    from .evidence_storage import get_storage
    store = get_storage()
    if hasattr(store, "purge_all"):   # demo reset only: uploaded evidence files belong to the rows being truncated
        print(f"Evidence storage purged: {store.purge_all()} file(s) removed.")
    Base.metadata.create_all(db.get_bind())
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    if engine.dialect.name == "postgresql":
        db.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    else:
        for t in reversed(Base.metadata.sorted_tables):
            db.execute(t.delete())
    db.commit()


def seed_reference_data(db) -> dict:
    geo.load_wards(db)  # synthetic demo wards + their authority queues (commits)
    for fid, name, kind, lng, lat in FACILITIES:
        db.add(Facility(id=fid, name=name, kind=kind, location=geo.point_wkt(lat, lng)))
    for vid, reg, vtype, cap, st, ward in VEHICLES:
        db.add(Vehicle(id=vid, registration_number=reg, vehicle_type=vtype, capacity_kg=cap, status=st, assigned_ward=ward))
    workers, routes, households = [], [], []
    for i, (ward, wname, owners) in enumerate(ROUTES, start=1):
        w = Worker(id=i, name=wname)
        db.add(w)
        db.flush()
        r = Route(id=i, ward=ward, worker_id=w.id)
        db.add(r)
        db.flush()
        w.assigned_route_id = r.id
        for j, (owner, lng, lat) in enumerate(owners):
            hid = (i - 1) * 6 + j + 1
            db.add(Household(id=hid, ward=ward, route_id=r.id, owner_name=owner, location=geo.point_wkt(lat, lng),
                             address=f"Flat {101 + j}, {SOCIETIES[(j + i) % 6]}, {ward}",
                             civic_credits=CREDITS[hid - 1]))
        workers.append(w)
    db.commit()
    # ward_id is DERIVED from the coordinates by PostGIS; verify it matches what the seed intended
    geo.assign_wards(db)
    geo.build_route_paths(db)
    for i, (ward, _, _) in enumerate(ROUTES, start=1):
        got = {n for (n,) in db.execute(text("SELECT DISTINCT w.name FROM households h JOIN wards w ON w.id = h.ward_id WHERE h.route_id = :r"), {"r": i})}
        assert got == {ward}, f"seed error: route {i} households resolved to {got}, expected {ward}"
    users = [
        User(username="citizen1", role=Role.CITIZEN, name="Anita Deshmukh", household_id=1),
        User(username="worker1", role=Role.WORKER, name="Ramesh Patil", worker_id=1),
        User(username="worker2", role=Role.WORKER, name="Sunita Jadhav", worker_id=2),
        User(username="worker3", role=Role.WORKER, name="Imran Shaikh", worker_id=3),
        User(username="facility1", role=Role.FACILITY, name="Kiran Bhatt (Receiving Operator)", facility_id=1, capability="RECEIVING"),
        User(username="facility_ops", role=Role.FACILITY, name="Suresh Kumar (Processing Operator)", facility_id=1, capability="PROCESSING"),
        User(username="admin1", role=Role.MUNICIPAL_ADMIN, name="Dr. Neha Kulkarni (Municipal Oversight)"),
        # Phase 2/2B: a facility user at a DIFFERENT facility (id 2) with independent verifier capability.
        User(username="facility2", role=Role.FACILITY, name="Meera Joshi (Independent Verifier)", facility_id=2, capability="INDEPENDENT_VERIFIER"),
    ]
    for u in users:
        u.password_hash = hash_password(PASSWORD)
    db.add_all(users)
    db.commit()
    return {w.id: w for w in workers}


def _run_route(db, worker: Worker, statuses: list[CollectionStatus], quantity: int, t0):
    from .errors import ServiceError
    from .services import acknowledge_trip_verification
    load = None
    for k, st in enumerate(statuses):
        try:
            load, _ = record_collection(db, worker, (worker.id - 1) * 6 + k + 1, st, now=t0 + timedelta(minutes=12 * k))
        except ServiceError as e:
            if e.code == "VERIFICATION_PAUSED":
                acknowledge_trip_verification(db, worker, now=t0 + timedelta(minutes=12 * k))
                load, _ = record_collection(db, worker, (worker.id - 1) * 6 + k + 1, st, now=t0 + timedelta(minutes=12 * k))
            else:
                raise
    declare_load(db, worker, load.id, quantity, now=t0 + timedelta(minutes=12 * len(statuses) + 30))
    return load


def seed_scenarios(db, workers) -> None:
    S, U = CollectionStatus.SEGREGATED, CollectionStatus.UNSEGREGATED
    now = utcnow()
    fac1 = db.execute(select(User.id).where(User.username == "facility1")).scalar_one()   # who "recorded" the seeded receiving records
    fac2 = db.execute(select(User.id).where(User.username == "facility2")).scalar_one()
    fac_ops = db.execute(select(User.id).where(User.username == "facility_ops")).scalar_one()

    # ---- 1. clean load (no discrepancy) -> Trip 1 (CT-2026-0041), DL-1001, Receiving #1
    t0 = now - timedelta(days=3, hours=-1)
    l1 = _run_route(db, workers[1], [S, S, S, U, S, S], 480, t0)
    create_receiving_record(db, l1.id, 1, 468, Condition.ACCEPTABLE, actor="facility:seed", now=t0 + timedelta(hours=3), recorded_by_user_id=fac1)

    # ---- 2. MAIN DEMO PATH: 25% quantity shortfall -> Trip 2 (CT-2026-0042), DL-1002, Receiving #2, Discrepancy #1 (FLAGGED)
    t0 = now - timedelta(days=2, hours=-1)
    l2 = _run_route(db, workers[2], [S, S, S, S, U, S], 520, t0)
    create_receiving_record(db, l2.id, 1, 390, Condition.ACCEPTABLE, actor="facility:seed", now=t0 + timedelta(hours=3), recorded_by_user_id=fac1)

    # ---- 3. receiving-side rejection -> STREAM discrepancy -> Trip 3 (CT-2026-0043), DL-1003, Receiving #3, Discrepancy #2 (INVESTIGATING)
    t0 = now - timedelta(days=1, hours=-1)
    l3 = _run_route(db, workers[3], [S, S, S, S, S, S], 450, t0)
    out = create_receiving_record(db, l3.id, 1, 445, Condition.UNACCEPTABLE, actor="facility:seed", now=t0 + timedelta(hours=3), recorded_by_user_id=fac1)
    d = out["discrepancies"][0]
    t = t0 + timedelta(hours=4)
    resolution.add_evidence(db, d.id, "facility:seed", "Facility photo: food waste and plastic film mixed through the top layers.", "IMG_0412.jpg", now=t)
    resolution.corroborate(db, d.id, "facility:seed", None, "UNACCEPTABLE", "AUD-03", now=t + timedelta(hours=2))
    resolution.investigate(db, d.id, "municipal_admin:seed", "Compare with previous 5 loads from route 3.", now=t + timedelta(hours=3))

    # ---- 4. Historical loads DL-1004 through DL-1021 (Trips 4 through 21, Receiving #4 through #21, Discrepancies #3 through #21)
    for i in range(4, 22):
        route_id = ((i - 1) % 3) + 1
        w_id = route_id
        t_trip = now - timedelta(days=25 - i, hours=4)
        trip = CollectionTrip(
            trip_code=f"CT-2026-{40 + i:04d}",
            route_id=route_id,
            vehicle_id=route_id,
            start_time=t_trip,
            end_time=t_trip + timedelta(hours=2),
            status="COMPLETED",
            verification_triggered=False,
            verification_acknowledged=False,
            receiving_facility_id=1,
        )
        db.add(trip)
        db.flush()
        db.add(TripCrew(trip_id=trip.id, worker_id=w_id, role_in_crew="CREW_LEAD"))
        db.flush()

        lid = f"DL-{1000 + i}"
        declared_qty = 460 + (i * 7) % 40
        load = DigitalLoad(
            id=lid,
            route_id=route_id,
            trip_id=trip.id,
            vehicle_id=route_id,
            receiving_facility_id=1,
            generated_at=t_trip,
            status=LoadStatus.SETTLED,
            declared_quantity_kg=declared_qty,
        )
        db.add(load)
        db.flush()
        append_event(db, lid, "LOAD_CREATED", {"route_id": route_id, "ward": f"Demo Ward {chr(64 + route_id)}", "worker_id": w_id, "trip_code": trip.trip_code}, actor=f"worker:{w_id}", now=t_trip)
        append_event(db, lid, "LOAD_DECLARED", {"declared_quantity_kg": declared_qty}, actor=f"worker:{w_id}", now=t_trip + timedelta(hours=2))

        received_qty = declared_qty - 25
        rr = ReceivingRecord(
            load_id=lid,
            facility_id=1,
            quantity=received_qty,
            condition=Condition.ACCEPTABLE,
            timestamp=t_trip + timedelta(hours=3),
            recorded_by_user_id=fac1,
        )
        db.add(rr)
        db.flush()
        append_event(db, lid, "RECEIVING_RECORD_CREATED", {"receiving_record_id": rr.id, "facility_id": 1, "quantity_kg": rr.quantity, "condition": "ACCEPTABLE"}, actor="facility:1", now=rr.timestamp)

        disc = DiscrepancyEvent(
            load_id=lid,
            type=DiscrepancyType.QUANTITY,
            status=DiscrepancyStatus.CLOSED,
            created_at=rr.timestamp,
            resolved_at=rr.timestamp + timedelta(hours=2),
            details_json={"declared_quantity_kg": declared_qty, "received_quantity_kg": received_qty, "resolution": {"notes": "Settled upon verification", "attributed_to": None}},
        )
        db.add(disc)
        db.flush()
        append_event(db, lid, "DISCREPANCY_FLAGGED", {"discrepancy_id": disc.id, "type": "QUANTITY"}, actor="system:crosscheck", now=disc.created_at)
        append_event(db, lid, "DISCREPANCY_CLOSED", {"discrepancy_id": disc.id, "resolution": "Settled"}, actor="municipal_admin:1", now=disc.resolved_at)

        if i == 4:
            # Add second discrepancy on DL-1004 so total discrepancy count reaches exactly 21
            disc_stream = DiscrepancyEvent(
                load_id=lid,
                type=DiscrepancyType.STREAM,
                status=DiscrepancyStatus.CLOSED,
                created_at=rr.timestamp,
                resolved_at=rr.timestamp + timedelta(hours=2),
                details_json={"condition": "UNACCEPTABLE", "resolution": {"notes": "Segregation check re-verified", "attributed_to": None}},
            )
            db.add(disc_stream)
            db.flush()
            append_event(db, lid, "DISCREPANCY_FLAGGED", {"discrepancy_id": disc_stream.id, "type": "STREAM"}, actor="system:crosscheck", now=disc_stream.created_at)
            append_event(db, lid, "DISCREPANCY_CLOSED", {"discrepancy_id": disc_stream.id, "resolution": "Settled"}, actor="municipal_admin:1", now=disc_stream.resolved_at)

    # ---- 5. 30 Historical Completed Audits (AU-1 through AU-30)
    for a_idx in range(1, 31):
        target_lid = f"DL-{1001 + (a_idx % 21)}"
        t_aud = now - timedelta(days=30 - a_idx, hours=5)
        audit = Audit(
            target_type=AuditTargetType.DIGITAL_LOAD,
            load_id=target_lid,
            worker_id=((a_idx % 3) + 1),
            facility_id=1,
            method=AuditMethod.RANDOM if a_idx % 2 == 0 else AuditMethod.RISK_BASED,
            selection_reason="Routine independent quality verification audit.",
            selected_at=t_aud,
            selected_by_user_id=None,
            status=AuditStatus.COMPLETED,
            auditor_id=fac2,
            started_at=t_aud + timedelta(minutes=15),
            completed_at=t_aud + timedelta(minutes=45),
            result_json={"quantity": 440 + (a_idx * 3) % 30, "condition": "ACCEPTABLE", "observations": "Physical load inspection verified and compliant."},
        )
        db.add(audit)
        db.flush()
        append_event(db, target_lid, "AUDIT_SELECTED", {"audit_id": audit.id, "method": audit.method.value, "selection_reason": audit.selection_reason}, actor="system:audit-engine", now=t_aud)
        append_event(db, target_lid, "AUDIT_COMPLETED", {"audit_id": audit.id, "quantity_kg": audit.result_json["quantity"], "condition": audit.result_json["condition"]}, actor="facility:2", now=audit.completed_at)

    # ---- 6. 2 Historical Completed Processing Records (#1 on DL-1020, #2 on DL-1021)
    t_proc1 = now - timedelta(days=2, hours=4)
    pr1 = ProcessingRecord(
        digital_load_id="DL-1020",
        facility_id=1,
        waste_stream=WasteStream.ORGANIC,
        processing_method=ProcessingMethod.COMPOSTING,
        processed_quantity_kg=450,
        recovered_quantity_kg=360,
        residual_quantity_kg=90,
        status=ProcessingStatus.COMPLETED,
        started_at=t_proc1,
        completed_at=t_proc1 + timedelta(hours=2),
        recorded_by_user_id=fac_ops,
        notes="Aerobic composting process complete.",
    )
    db.add(pr1)
    db.flush()
    append_event(db, "DL-1020", "PROCESSING_COMPLETED", {"processing_record_id": pr1.id, "waste_stream": "ORGANIC", "method": "COMPOSTING", "processed_kg": 450, "recovered_kg": 360, "residual_kg": 90}, actor="facility:ops", now=pr1.completed_at)

    t_proc2 = now - timedelta(days=1, hours=4)
    pr2 = ProcessingRecord(
        digital_load_id="DL-1021",
        facility_id=1,
        waste_stream=WasteStream.RECYCLABLE,
        processing_method=ProcessingMethod.RECYCLING,
        processed_quantity_kg=480,
        recovered_quantity_kg=400,
        residual_quantity_kg=80,
        status=ProcessingStatus.COMPLETED,
        started_at=t_proc2,
        completed_at=t_proc2 + timedelta(hours=2),
        recorded_by_user_id=fac_ops,
        notes="Material recovery facility sort complete.",
    )
    db.add(pr2)
    db.flush()
    append_event(db, "DL-1021", "PROCESSING_COMPLETED", {"processing_record_id": pr2.id, "waste_stream": "RECYCLABLE", "method": "RECYCLING", "processed_kg": 480, "recovered_kg": 400, "residual_kg": 80}, actor="facility:ops", now=pr2.completed_at)

    # ---- 7. Completed Trip 22 (CT-2026-0062) on Route 2
    t22 = CollectionTrip(
        trip_code="CT-2026-0062",
        route_id=2,
        vehicle_id=2,
        start_time=now - timedelta(days=1, hours=3),
        end_time=now - timedelta(days=1, hours=1),
        status="COMPLETED",
        verification_triggered=False,
        verification_acknowledged=False,
        receiving_facility_id=1,
    )
    db.add(t22)
    db.flush()
    db.add(TripCrew(trip_id=t22.id, worker_id=2, role_in_crew="CREW_LEAD"))
    db.flush()

    # ---- 8. Active Trip 23 (CT-2026-0063) & Active Load DL-1022 on Route 1
    t23 = CollectionTrip(
        trip_code="CT-2026-0063",
        route_id=1,
        vehicle_id=1,
        start_time=now,
        status="IN_PROGRESS",
        verification_triggered=False,
        verification_acknowledged=False,
        verification_paused_at_count=3,
        receiving_facility_id=1,
    )
    db.add(t23)
    db.flush()
    db.add(TripCrew(trip_id=t23.id, worker_id=1, role_in_crew="CREW_LEAD"))
    db.flush()

    l22 = DigitalLoad(
        id="DL-1022",
        route_id=1,
        trip_id=t23.id,
        vehicle_id=1,
        receiving_facility_id=1,
        generated_at=now,
        status=LoadStatus.COLLECTING,
    )
    db.add(l22)
    db.flush()
    append_event(db, "DL-1022", "LOAD_CREATED", {"route_id": 1, "ward": "Demo Ward A", "worker_id": 1, "trip_code": "CT-2026-0063", "vehicle": "MH-01-AB-1234"}, actor="worker:1", now=now)
    db.commit()


def seed_sanitation(db) -> None:
    """Demo tickets (all text prefixed [DEMO/SYNTHETIC]). Created through the real submit/route/status code paths."""
    citizen = db.execute(select(User).where(User.username == "citizen1")).scalar_one()
    admin = db.execute(select(User).where(User.username == "admin1")).scalar_one()
    now = utcnow()
    demo = [  # (issue, lng, lat, hours ago, target status, text)
        (IssueType.OVERFLOWING_BIN, 72.866, 19.079, 30, TicketStatus.IN_PROGRESS, "Bin overflowing outside gate 2"),
        (IssueType.OVERFLOWING_BIN, 72.868, 19.080, 26, None, "Second overflowing bin, 200 m away (nearby-report demo)"),
        (IssueType.ILLEGAL_DUMPING, 72.902, 19.070, 20, None, "Construction debris dumped on the verge"),
        (IssueType.BLOCKED_DRAIN, 72.893, 19.083, 50, TicketStatus.RESOLVED, "Drain blocked with plastic after rain"),
        (IssueType.MISSED_COLLECTION, 72.880, 19.116, 8, None, "Door-to-door collection skipped today"),
        (IssueType.ILLEGAL_DUMPING, 72.930, 19.110, 5, None, "Dumping reported outside every demo ward (manual-triage demo)"),
    ]
    for issue, lng, lat, hrs, target, text_ in demo:
        t = now - timedelta(hours=hrs)
        r = sanitation.create_report(db, citizen, description=f"[DEMO/SYNTHETIC] {text_}", issue_type=issue, lat=lat, lng=lng,
                                     accuracy_m=12.0, photo_name=None, now=t)
        if target in (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED):
            sanitation.set_status(db, r.id, admin, TicketStatus.IN_PROGRESS, now=t + timedelta(hours=2))
        if target == TicketStatus.RESOLVED:
            sanitation.set_status(db, r.id, admin, TicketStatus.RESOLVED, note="Drain cleared by ward team (demo).", now=t + timedelta(hours=6))
    db.commit()


def main(argv: list[str]) -> None:
    with SessionLocal() as db:
        if "--if-empty" in argv and db.scalar(select(User.id).limit(1)):
            print("Seed skipped: database already has data.")
            return
        if "--reset" in argv or "--if-empty" in argv:
            reset(db)
        workers = seed_reference_data(db)
        seed_scenarios(db, workers)
        seed_sanitation(db)

        print("Seeded. Logins (password for all: %s): citizen1, worker1, worker2, worker3, facility1, admin1" % PASSWORD)
        for lid in ("DL-1001", "DL-1002", "DL-1003", "DL-1022"):
            ev = list_events(db, lid)
            v = verify_chain(db, lid)
            print(f"  {lid}: {len(ev)} events (ids {ev[0].id}-{ev[-1].id}), chain valid={v['valid']}")


if __name__ == "__main__":
    main(sys.argv[1:])
