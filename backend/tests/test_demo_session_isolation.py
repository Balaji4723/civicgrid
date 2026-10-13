"""Automated tests for fresh, isolated demo sessions in CivicGrid.

Verifies:
1. Every new demo session receives a pristine seeded workspace.
2. Cross-session data isolation: two independent demo sessions cannot see or modify each other's data.
3. Persistence across page refreshes and route navigation.
4. Multi-role lifecycle within a single demo session (Citizen -> Worker -> Receiving -> Processing -> Verifier -> Authority).
5. Token-carried session isolation and IP-continuity across logouts (preserving compatibility with older frontends).
"""
import pytest
from fastapi.testclient import TestClient

from app import seed
from tests.conftest import login


def test_fresh_session_gets_clean_seeded_workspace(client):
    """A fresh session must receive pristine seeded records:
    clean 0/6 pending shift, pristine FLAGGED discrepancy on DL-1002, and standard stats.
    """
    sid = "test_fresh_01"
    headers_worker = {**login(client, "worker1"), "X-Demo-Session": sid}
    headers_facility = {**login(client, "facility1"), "X-Demo-Session": sid}
    headers_admin = {**login(client, "admin1"), "X-Demo-Session": sid}

    # Worker starts with a clean shift: all households PENDING
    route = client.get("/worker/route", headers=headers_worker).json()
    assert route["trip"]["status"] == "IN_PROGRESS"
    assert all(h["status"] == "PENDING" for h in route["households"])

    # Discrepancy #1 is in pristine FLAGGED state (ready for live demo walkthrough)
    discs = client.get("/discrepancy", headers=headers_facility).json()
    disc1 = next(d for d in discs if d["id"] == 1)
    assert disc1["load_id"] == "DL-1002"
    assert disc1["status"] == "FLAGGED"

    # Stats reflect pristine seeded counts
    stats = client.get("/stats", headers=headers_admin).json()
    assert stats["households"] == 18
    assert stats["workers"] == 3
    assert stats["open_discrepancies"] >= 2


def test_cross_session_data_isolation(client):
    """Two independent demo sessions cannot see or modify each other's data."""
    sid_a = "session_alpha_iso"
    sid_b = "session_bravo_iso"

    w_a = {**login(client, "worker1"), "X-Demo-Session": sid_a}
    w_b = {**login(client, "worker1"), "X-Demo-Session": sid_b}
    fac_a = {**login(client, "facility1"), "X-Demo-Session": sid_a}
    fac_b = {**login(client, "facility1"), "X-Demo-Session": sid_b}
    ver_a = {**login(client, "facility2"), "X-Demo-Session": sid_a}
    ver_b = {**login(client, "facility2"), "X-Demo-Session": sid_b}
    adm_a = {**login(client, "admin1"), "X-Demo-Session": sid_a}
    adm_b = {**login(client, "admin1"), "X-Demo-Session": sid_b}

    # 1. Session A worker marks all 6 households and completes trip
    route_a = client.get("/worker/route", headers=w_a).json()
    for h in route_a["households"]:
        client.post("/worker/collections", json={"household_id": h["id"], "status": "SEGREGATED"}, headers=w_a)
    comp_a = client.post("/worker/trip/complete", json={"declared_quantity_kg": 500}, headers=w_a).json()
    load_a_id = comp_a["id"]
    assert comp_a["status"] == "DECLARED"

    # 2. Concurrently, Session B worker opens /worker/route -> MUST be pristine 0/6 PENDING!
    route_b = client.get("/worker/route", headers=w_b).json()
    assert route_b["trip"]["status"] == "IN_PROGRESS"
    assert route_b["trip"]["id"] != comp_a["trip_id"]
    assert all(h["status"] == "PENDING" for h in route_b["households"])

    # 3. Session B cannot see Session A's new load in /loads or /worker/history
    loads_a = [l["id"] for l in client.get("/loads", headers=fac_a).json()]
    loads_b = [l["id"] for l in client.get("/loads", headers=fac_b).json()]
    assert load_a_id in loads_a
    assert load_a_id not in loads_b

    hist_a = [t["load_id"] for t in client.get("/worker/history", headers=w_a).json()]
    hist_b = [t["load_id"] for t in client.get("/worker/history", headers=w_b).json()]
    assert load_a_id in hist_a
    assert load_a_id not in hist_b

    # 4. Session A progresses discrepancy #1 on DL-1002 to CLOSED
    client.post("/discrepancy/1/add-evidence", json={"note": "Slip photo", "evidence_ref": "slip.jpg"}, headers=fac_a)
    client.post("/discrepancy/1/corroborate", json={"audit_quantity": 385, "auditor": "AUD-07"}, headers=ver_a)
    client.post("/discrepancy/1/investigate", json={"note": "Investigating"}, headers=ver_a)
    client.post("/discrepancy/1/resolve", json={"finding": "Spillage settled", "attributed_to": "PROCESS"}, headers=ver_a)
    r_close = client.post("/discrepancy/1/close", json={"note": "Closed"}, headers=ver_a)
    assert r_close.status_code == 200
    assert r_close.json()["status"] == "CLOSED"

    # 5. In Session B, discrepancy #1 MUST STILL be in pristine FLAGGED status!
    disc1_b = next(d for d in client.get("/discrepancy", headers=fac_b).json() if d["id"] == 1)
    assert disc1_b["status"] == "FLAGGED"

    # 6. Session A stats reflect closed discrepancy; Session B stats reflect open discrepancy
    stats_a = client.get("/stats", headers=adm_a).json()
    stats_b = client.get("/stats", headers=adm_b).json()
    assert stats_a["closed_discrepancies"] > stats_b["closed_discrepancies"]


def test_persistence_after_page_refresh_and_navigation(client):
    """Changes made in a session persist across page refreshes and route navigation."""
    sid = "session_persist_01"
    w = {**login(client, "worker1"), "X-Demo-Session": sid}

    # Worker completes trip
    route = client.get("/worker/route", headers=w).json()
    for h in route["households"]:
        client.post("/worker/collections", json={"household_id": h["id"], "status": "SEGREGATED"}, headers=w)
    comp = client.post("/worker/trip/complete", json={"declared_quantity_kg": 490}, headers=w).json()
    load_id = comp["id"]

    # Page refresh: re-fetch /worker/route with the same session
    refresh = client.get("/worker/route", headers=w).json()
    assert refresh["trip"]["status"] == "COMPLETED"
    assert refresh["active_load"]["id"] == load_id
    assert refresh["active_load"]["status"] == "DECLARED"
    assert all(h["status"] == "SEGREGATED" for h in refresh["households"])

    # Navigation: navigate to /citizen/me and check household collection history
    c = {**login(client, "citizen1"), "X-Demo-Session": sid}
    c_me = client.get("/citizen/me", headers=c).json()
    assert any(ev["load_id"] == load_id for ev in c_me["collection_history"])


def test_role_workflows_shared_within_single_session(client):
    """Citizen, Worker, Receiving, Verifier, and Municipal Authority all participate
    in the SAME lifecycle within a single demo session.
    """
    sid = "session_shared_roles"
    c = {**login(client, "citizen1"), "X-Demo-Session": sid}
    w = {**login(client, "worker1"), "X-Demo-Session": sid}
    fac_rec = {**login(client, "facility1"), "X-Demo-Session": sid}
    verifier = {**login(client, "facility2"), "X-Demo-Session": sid}
    admin = {**login(client, "admin1"), "X-Demo-Session": sid}

    # 1. Citizen submits sanitation report
    rep = client.post(
        "/citizen/sanitation-reports",
        json={"description": "Overflowing bin on Elm Street", "issue_type": "OVERFLOWING_BIN", "latitude": 19.066, "longitude": 72.858},
        headers=c,
    ).json()
    ticket_id = rep["id"]

    # 2. Worker completes collections and seals digital load
    route = client.get("/worker/route", headers=w).json()
    for h in route["households"]:
        client.post("/worker/collections", json={"household_id": h["id"], "status": "SEGREGATED"}, headers=w)
    comp = client.post("/worker/trip/complete", json={"declared_quantity_kg": 500}, headers=w).json()
    new_load_id = comp["id"]

    # 3. Receiving operator at facility sees the new load and intakes it at weighbridge
    loads = client.get("/loads", headers=fac_rec).json()
    assert any(l["id"] == new_load_id for l in loads)

    rec_res = client.post(
        f"/loads/{new_load_id}/receiving",
        json={"quantity": 380, "condition": "UNACCEPTABLE"},
        headers=fac_rec,
    ).json()
    assert rec_res["cross_check_result"] == "FLAGGED"
    discs = rec_res["discrepancies"]
    assert len(discs) > 0
    new_disc_id = discs[0]["id"]

    # 4. Independent Verifier adds evidence and corroborates the new discrepancy
    client.post(
        f"/discrepancy/{new_disc_id}/add-evidence",
        json={"note": "Weighbridge discrepancy slip #991", "evidence_ref": "slip.png"},
        headers=verifier,
    )
    client.post(
        f"/discrepancy/{new_disc_id}/corroborate",
        json={"audit_quantity": 375, "auditor": "AUD-07"},
        headers=verifier,
    )
    client.post(f"/discrepancy/{new_disc_id}/investigate", json={"note": "Investigating root cause"}, headers=verifier)
    client.post(
        f"/discrepancy/{new_disc_id}/resolve",
        json={"finding": "Transit loss acknowledged", "attributed_to": "PROCESS"},
        headers=verifier,
    )

    # 5. Independent Verifier closes the discrepancy
    r_close = client.post(f"/discrepancy/{new_disc_id}/close", json={"note": "Resolved and settled"}, headers=verifier)
    assert r_close.status_code == 200
    assert r_close.json()["status"] == "CLOSED"

    # Municipal Authority views the closed discrepancy and sees citizen ticket in queue
    discs = client.get("/discrepancy", headers=admin).json()
    assert any(d["id"] == new_disc_id and d["status"] == "CLOSED" for d in discs)

    # Authority sees the citizen's ticket in the queue
    ticket = client.get(f"/sanitation/tickets/{ticket_id}", headers=admin).json()
    assert ticket["id"] == ticket_id


def test_token_carried_session_and_ip_continuity_for_older_frontend(client):
    """Simulates the older frontend behavior:
    1. Client does NOT send X-Demo-Session header.
    2. Client logs in via POST /auth/login -> receives JWT with embedded session_id.
    3. Authenticated requests use only Authorization: Bearer <token>.
    4. Client signs out (discards token) and logs in as another role from the SAME IP:
       Backend associates the new login with the same active demo session!
    5. A visitor from a different IP gets a completely separate clean session.
    """
    ip_visitor_1 = "198.51.100.42"
    ip_visitor_2 = "203.0.113.88"

    # Visitor 1 logs in as worker1 (no custom headers)
    r1 = client.post("/auth/login", json={"username": "worker1", "password": seed.PASSWORD}, headers={"X-Forwarded-For": ip_visitor_1})
    assert r1.status_code == 200
    token_w1 = r1.json()["access_token"]
    session_1 = r1.json()["session_id"]
    assert session_1 is not None

    # Visitor 1 records work using only the Bearer token
    headers_w1 = {"Authorization": f"Bearer {token_w1}", "X-Forwarded-For": ip_visitor_1}
    route = client.get("/worker/route", headers=headers_w1).json()
    for h in route["households"]:
        client.post("/worker/collections", json={"household_id": h["id"], "status": "SEGREGATED"}, headers=headers_w1)
    comp = client.post("/worker/trip/complete", json={"declared_quantity_kg": 500}, headers=headers_w1).json()
    load_id_v1 = comp["id"]

    # Visitor 1 signs out (token discarded) and logs in as facility1 from SAME IP
    r2 = client.post("/auth/login", json={"username": "facility1", "password": seed.PASSWORD}, headers={"X-Forwarded-For": ip_visitor_1})
    assert r2.status_code == 200
    token_f1 = r2.json()["access_token"]
    session_2 = r2.json()["session_id"]
    # IP continuity preserved the same session across sign-out!
    assert session_2 == session_1

    # Facility operator sees the load declared by worker1!
    headers_f1 = {"Authorization": f"Bearer {token_f1}", "X-Forwarded-For": ip_visitor_1}
    loads_v1 = [l["id"] for l in client.get("/loads", headers=headers_f1).json()]
    assert load_id_v1 in loads_v1

    # Visitor 2 logs in from a DIFFERENT IP -> receives a separate, clean session!
    r3 = client.post("/auth/login", json={"username": "facility1", "password": seed.PASSWORD}, headers={"X-Forwarded-For": ip_visitor_2})
    assert r3.status_code == 200
    token_v2 = r3.json()["access_token"]
    session_v2 = r3.json()["session_id"]
    assert session_v2 != session_1

    # Visitor 2 does NOT see Visitor 1's newly declared load!
    headers_v2 = {"Authorization": f"Bearer {token_v2}", "X-Forwarded-For": ip_visitor_2}
    loads_v2 = [l["id"] for l in client.get("/loads", headers=headers_v2).json()]
    assert load_id_v1 not in loads_v2
