"""Phase 1: PostGIS spatial queries, ward loading, point-in-ward, GPS routing and the sanitation ticket lifecycle."""
import json
import math

import pytest
from sqlalchemy import text

from app import geo, seed
from app.auth import hash_password
from app.db import SessionLocal
from app.models import EventLog, Role, User
from tests.conftest import login

# ---- known synthetic points (see app/data/demo_wards.geojson)
IN_A = (19.075, 72.865)        # (lat, lng)
IN_B = (19.070, 72.902)
IN_C = (19.116, 72.880)
BBOX_TRAP = (19.075, 72.879)   # inside Ward B's bounding box, but the polygon it is really in is Ward A
OUTSIDE = (19.110, 72.930)     # east of every ward
SHARED_VERTEX = (19.060, 72.880)  # corner shared by Ward A and Ward B -> ambiguous


def haversine(a, b):
    R = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


@pytest.fixture()
def admin(client):
    return login(client, "admin1")


@pytest.fixture()
def citizen(client):
    return login(client, "citizen1")


@pytest.fixture()
def facility(client):
    return login(client, "facility1")


def report(client, headers, lat=None, lng=None, **kw):
    body = {"description": "[TEST] overflowing bin outside the gate", "issue_type": "OVERFLOWING_BIN", **kw}
    if lat is not None:
        body.update(latitude=lat, longitude=lng)
    return client.post("/citizen/sanitation-reports", json=body, headers=headers)


# ================================================================ wards + source labelling
def test_wards_are_synthetic_and_labelled(client, citizen):
    r = client.get("/geo/wards", headers=citizen).json()
    assert [f["properties"]["name"] for f in r["features"]] == ["Demo Ward A", "Demo Ward B", "Demo Ward C"]
    for f in r["features"]:
        assert f["properties"]["is_official"] is False
        assert f["properties"]["source_label"] == "DEMO DATA — NOT OFFICIAL MUNICIPAL BOUNDARIES"
        assert f["geometry"]["type"] == "MultiPolygon"
    assert r["source"]["all_official"] is False
    assert "BMC" not in json.dumps(r) and "K/East" not in json.dumps(r)
    assert ".geojson" not in json.dumps(r), "server file paths must not be exposed"


def test_wards_endpoint_requires_login(client):
    assert client.get("/geo/wards").status_code == 401


@pytest.fixture()
def good_source():
    return json.load(open(geo.WARD_BOUNDARY_SOURCE))


def write(tmp_path, data, name="src.geojson"):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return str(p)


def square(x, y, s=0.01):
    return {"type": "Polygon", "coordinates": [[[x, y], [x + s, y], [x + s, y + s], [x, y + s], [x, y]]]}


def ward(code, geom, q=None):
    return {"type": "Feature", "geometry": geom,
            "properties": {"code": code, "name": code, "queue": q or {"code": f"Q-{code}", "name": f"Queue {code}"}}}


def source(features, **meta):
    m = {"name": "test", "version": "1", "label": "TEST DATA", "is_official": False, **meta}
    return {"type": "FeatureCollection", "civicgrid_source": m, "features": features}


@pytest.mark.parametrize("label,data,msg", [
    ("overlap", source([ward("X", square(72, 19)), ward("Y", square(72.005, 19.005))]), "overlap"),
    ("bowtie", source([ward("X", {"type": "Polygon", "coordinates": [[[72, 19], [72.01, 19.01], [72.01, 19], [72, 19.01], [72, 19]]]})]), "invalid geometry"),
    ("not_wgs84", source([ward("X", square(500000, 2100000))]), "WGS84"),
    ("point", source([ward("X", {"type": "Point", "coordinates": [72, 19]})]), "Polygon"),
    ("no_source_meta", {"type": "FeatureCollection", "features": [ward("X", square(72, 19))]}, "civicgrid_source"),
    ("no_queue", source([{"type": "Feature", "geometry": square(72, 19), "properties": {"code": "X", "name": "X"}}]), "queue"),
    ("dup_code", source([ward("X", square(72, 19)), ward("X", square(73, 19))]), "Duplicate"),
    ("empty", source([]), "at least one feature"),
])
def test_ward_source_validation_rejects_bad_data(tmp_path, label, data, msg):
    with pytest.raises(geo.WardSourceError, match=msg):
        geo.parse_ward_source(write(tmp_path, data))


def test_ward_source_unreadable_file(tmp_path):
    with pytest.raises(geo.WardSourceError, match="Cannot read"):
        geo.parse_ward_source(str(tmp_path / "nope.geojson"))


def test_load_wards_is_upsert_and_source_is_configurable(client, tmp_path):
    with SessionLocal() as db:
        again = geo.load_wards(db)
        assert (again["created"], again["updated"]) == (0, 3)
        ids_before = dict(db.execute(text("select code, id from wards")).all())
        # a *different* configured source: one ward, explicit non-official label, boundary moved
        other = source([ward("DEMO-A", square(10.0, 10.0))], name="Alt demo source", version="alt-2", label="ALT DEMO DATA")
        r = geo.load_wards(db, write(tmp_path, other))
        assert (r["created"], r["updated"]) == (0, 1)
        row = db.execute(text("select id, source_name, source_version, is_official, ST_Covers(boundary, ST_SetSRID(ST_MakePoint(10.005, 10.005), 4326)) "
                              "from wards where code='DEMO-A'")).one()
        assert row[0] == ids_before["DEMO-A"], "upsert must keep the ward id (FKs point at it)"
        assert row[1:4] == ("Alt demo source", "alt-2", False) and row[4] is True


# ================================================================ geometry types + indexes
def test_spatial_columns_are_real_postgis_types():
    with SessionLocal() as db:
        got = {(t, c): (ty.upper(), srid) for t, c, ty, srid in db.execute(text(
            "select f_table_name, f_geometry_column, type, srid from geometry_columns "
            "union all select f_table_name, f_geography_column, type, srid from geography_columns"))}
    assert got[("wards", "boundary")] == ("MULTIPOLYGON", 4326)
    assert got[("routes", "path")] == ("LINESTRING", 4326)
    for t in ("households", "facilities", "sanitation_reports"):
        assert got[(t, "location")] == ("POINT", 4326), t


def test_gist_indexes_exist_and_serve_the_queries():
    with SessionLocal() as db:
        defs = {n: d for n, d in db.execute(text("select indexname, indexdef from pg_indexes where schemaname='public'"))}
        for n in ("idx_wards_boundary", "idx_households_location", "idx_facilities_location", "idx_routes_path", "idx_sanitation_reports_location"):
            assert "USING gist" in defs[n], n
        db.execute(text("SET LOCAL enable_seqscan = off"))   # tables are tiny; force the planner to show it CAN use the index
        cases = {
            "idx_wards_boundary": "SELECT 1 FROM wards WHERE ST_Covers(boundary, ST_SetSRID(ST_MakePoint(72.865, 19.075), 4326))",
            "idx_sanitation_reports_location": "SELECT 1 FROM sanitation_reports WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(72.865, 19.075), 4326)::geography, 500)",
            "idx_households_location": "SELECT 1 FROM households WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(72.865, 19.075), 4326)::geography, 500)",
            "idx_facilities_location": "SELECT 1 FROM facilities WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(72.865, 19.075), 4326)::geography, 5000)",
            "idx_routes_path": "SELECT 1 FROM routes WHERE ST_Intersects(path, ST_MakeEnvelope(72.85, 19.06, 72.88, 19.09, 4326))",
        }
        for idx, sql in cases.items():
            plan = "\n".join(r[0] for r in db.execute(text("EXPLAIN " + sql)))
            assert idx in plan, f"{idx} not used:\n{plan}"


def test_event_log_check_constraint_blocks_mismatched_chain():
    from sqlalchemy.exc import IntegrityError
    with SessionLocal() as db:
        db.add(EventLog(chain_id="DL-1001", load_id="DL-1002", event_type="X", payload_json={}, prev_hash="0" * 64, hash="1" * 64))
        with pytest.raises(IntegrityError):
            db.commit()


# ================================================================ point-in-ward
@pytest.mark.parametrize("pt,name", [(IN_A, "Demo Ward A"), (IN_B, "Demo Ward B"), (IN_C, "Demo Ward C")])
def test_point_in_ward_inside(client, citizen, pt, name):
    r = client.get("/geo/ward-lookup", params={"lat": pt[0], "lng": pt[1]}, headers=citizen).json()
    assert r["outcome"] == "ROUTABLE" and r["ward"]["name"] == name and r["ward"]["queue"]["name"].startswith(name)
    assert r["ward"]["is_official"] is False and "NOT OFFICIAL" in r["ward"]["source_label"]


def test_point_in_polygon_is_not_a_bounding_box_test(client, citizen):
    r = client.get("/geo/ward-lookup", params={"lat": BBOX_TRAP[0], "lng": BBOX_TRAP[1]}, headers=citizen).json()
    assert r["ward"]["name"] == "Demo Ward A"          # a bbox test would have said B
    from shapely.geometry import Point, shape
    b = next(f for f in client.get("/geo/wards", headers=citizen).json()["features"] if f["properties"]["code"] == "DEMO-B")
    minx, miny, maxx, maxy = shape(b["geometry"]).bounds
    assert minx <= BBOX_TRAP[1] <= maxx and miny <= BBOX_TRAP[0] <= maxy and not shape(b["geometry"]).covers(Point(BBOX_TRAP[1], BBOX_TRAP[0]))


def test_point_outside_all_wards_and_on_shared_boundary(client, citizen):
    out = client.get("/geo/ward-lookup", params={"lat": OUTSIDE[0], "lng": OUTSIDE[1]}, headers=citizen).json()
    assert out["outcome"] == "OUTSIDE_ALL_WARDS" and out["ward"] is None
    edge = client.get("/geo/ward-lookup", params={"lat": SHARED_VERTEX[0], "lng": SHARED_VERTEX[1]}, headers=citizen).json()
    assert edge["outcome"] == "AMBIGUOUS_OR_NO_QUEUE" and {w["code"] for w in edge["wards"]} == {"DEMO-A", "DEMO-B"}


@pytest.mark.parametrize("params", [{"lat": 91, "lng": 72}, {"lat": 19, "lng": 181}, {"lat": "nan", "lng": 72}, {"lat": "inf", "lng": 72}, {"lat": 19}])
def test_ward_lookup_rejects_bad_coordinates(client, citizen, params):
    assert client.get("/geo/ward-lookup", params=params, headers=citizen).status_code == 422


def test_household_wards_are_derived_from_geometry_not_typed_in(client, admin):
    with SessionLocal() as db:
        rows = db.execute(text("select h.id, h.route_id, w.name, h.ward from households h join wards w on w.id = h.ward_id order by h.id")).all()
        assert len(rows) == 18
        for hid, route, wname, legacy in rows:
            assert wname == ["Demo Ward A", "Demo Ward B", "Demo Ward C"][route - 1] and legacy == wname
        assert db.execute(text("select count(*) from routes where ward_id is null")).scalar() == 0
        # recomputing changes nothing
        assert geo.assign_wards(db)["households_assigned"] == 18


# ================================================================ spatial query APIs
def test_nearby_reports_uses_metres(client, citizen, admin):
    centre = (19.0800, 72.8700)
    for dlat in (0.0, 0.001, 0.005):   # ~0 m, ~111 m, ~553 m north
        assert report(client, citizen, centre[0] + dlat, centre[1]).status_code == 200
    r = client.get("/geo/reports/nearby", params={"lat": centre[0], "lng": centre[1], "radius_m": 300}, headers=admin).json()
    assert [x["distance_m"] for x in r][0] < 1 and len(r) == 2
    assert abs(r[1]["distance_m"] - haversine(centre, (centre[0] + 0.001, centre[1]))) / r[1]["distance_m"] < 0.01
    wide = client.get("/geo/reports/nearby", params={"lat": centre[0], "lng": centre[1], "radius_m": 700}, headers=admin).json()
    assert len(wide) == 3 and wide == sorted(wide, key=lambda x: x["distance_m"])
    assert client.get("/geo/reports/nearby", params={"lat": 19, "lng": 72, "radius_m": 999999}, headers=admin).status_code == 422


def test_nearest_facility_ordering_and_distance(client, facility):
    p = (19.072, 72.860)   # next to the Western Transfer Station (id 2)
    r = client.get("/geo/facilities/nearest", params={"lat": p[0], "lng": p[1], "limit": 3}, headers=facility).json()
    assert [f["name"] for f in r][0] == "Western Transfer Station" and r[0]["ward"] == "Demo Ward A"
    assert [f["distance_m"] for f in r] == sorted(f["distance_m"] for f in r) and len(r) == 3
    west = haversine(p, (19.072, 72.856))
    assert abs(r[0]["distance_m"] - west) / west < 0.01
    only = client.get("/geo/facilities/nearest", params={"lat": p[0], "lng": p[1], "kind": "compost"}, headers=facility).json()
    assert [f["name"] for f in only] == ["Northern Compost Unit"]


def test_household_lookup_and_clusters(client, admin):
    near = client.get("/geo/households/nearby", params={"lat": 19.066, "lng": 72.858, "radius_m": 100}, headers=admin).json()
    assert [h["id"] for h in near] == [1] and near[0]["distance_m"] < 1
    assert set(near[0]) == {"id", "ward_id", "route_id", "distance_m", "latitude", "longitude"}, "no names/addresses in geo output"
    wa = next(f["properties"]["id"] for f in client.get("/geo/wards", headers=admin).json()["features"] if f["properties"]["code"] == "DEMO-A")
    tight = client.get("/geo/households/clusters", params={"ward_id": wa, "eps_m": 250, "min_points": 2}, headers=admin).json()
    assert tight["clusters"] == [] and tight["unclustered"] == 6          # stops are ~540 m apart
    wide = client.get("/geo/households/clusters", params={"ward_id": wa, "eps_m": 700, "min_points": 2}, headers=admin).json()
    assert len(wide["clusters"]) == 1 and wide["clusters"][0]["size"] == 6 and wide["srid_used"] == 32643
    assert client.get("/geo/households/clusters", params={"eps_m": 1}, headers=admin).status_code == 422


def test_utm_zone_helper():
    assert geo.utm_srid(19.07, 72.88) == 32643 and geo.utm_srid(-33.9, 151.2) == 32756


def test_route_geometry_and_length(client, facility):
    r = client.get("/geo/routes/1", headers=facility).json()
    assert r["ward"]["name"] == "Demo Ward A" and len(r["stops"]) == 6 and r["path"]["type"] == "LineString"
    pts = [(s["latitude"], s["longitude"]) for s in r["stops"]]
    expected = sum(haversine(a, b) for a, b in zip(pts, pts[1:]))
    assert abs(r["length_m"] - expected) / expected < 0.01
    assert [w["code"] for w in r["wards_crossed"]] == ["DEMO-A"]
    assert client.get("/geo/routes/999", headers=facility).status_code == 404


def test_area_query(client, admin):
    poly = {"type": "Polygon", "coordinates": [[[72.855, 19.064], [72.875, 19.064], [72.875, 19.086], [72.855, 19.086], [72.855, 19.064]]]}
    r = client.post("/geo/area/query", json={"area": poly}, headers=admin).json()
    assert r["households"] == 6 and r["route_ids"] == [1] and [w["code"] for w in r["wards"]] == ["DEMO-A"]
    assert [f["name"] for f in r["facilities"]] == ["Western Transfer Station"]
    for bad in [{"type": "Point", "coordinates": [72, 19]},
                {"type": "Polygon", "coordinates": [[[72, 19], [72.01, 19.01], [72.01, 19], [72, 19.01], [72, 19]]]},   # bow-tie
                {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},                      # too large
                {"type": "Polygon", "coordinates": [[[200, 0], [201, 0], [201, 1], [200, 1], [200, 0]]]}]:               # out of range
        assert client.post("/geo/area/query", json={"area": bad}, headers=admin).status_code == 422
    assert client.post("/geo/area/query", json={}, headers=admin).status_code == 422


def test_geo_rbac(client, citizen, facility):
    w = login(client, "worker1")
    assert client.get("/geo/reports", headers=w).status_code == 403
    assert client.get("/geo/facilities", headers=w).status_code == 403
    assert client.get("/geo/households/nearby", params={"lat": 19, "lng": 72, "radius_m": 100}, headers=facility).status_code == 403
    assert client.get("/geo/reports", headers=facility).status_code == 403
    assert client.get("/geo/facilities", headers=facility).status_code == 200


# ================================================================ GPS routing
def events(client, admin, ticket_id):
    return client.get(f"/sanitation/tickets/{ticket_id}/events", headers=admin).json()


def test_report_inside_ward_is_routed_and_audited(client, citizen, admin):
    r = report(client, citizen, *IN_B, accuracy_m=9.5)
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["status"] == "ROUTED" and t["ward"]["code"] == "DEMO-B" and t["queue"]["code"] == "DEMO-Q-B"
    assert t["location"]["verified"] is False and t["location"]["source"] == "DEVICE_REPORTED"
    assert t["location"]["note"] == "Location reported by device — not independently verified."
    assert t["routing"]["method"] == "POINT_IN_POLYGON" and t["routing"]["reason"] == "POINT_INSIDE_WARD_POLYGON"
    assert t["ward"]["is_official"] is False
    ev = events(client, admin, t["id"])
    assert [e["event_type"] for e in ev] == ["SANITATION_SUBMITTED", "SANITATION_ROUTED"]
    routed = ev[1]["payload"]
    assert routed["ward_code"] == "DEMO-B" and routed["queue_code"] == "DEMO-Q-B" and routed["boundary_is_official"] is False
    assert routed["location"]["verified"] is False and "not independently verified" in routed["location"]["note"]
    assert ev[0]["prev_hash"] == "0" * 64
    d = client.get(f"/sanitation/tickets/{t['id']}", headers=admin).json()
    assert len(d["routing_history"]) == 1 and d["routing_history"][0]["event_id"] == ev[1]["id"]
    assert client.get(f"/sanitation/tickets/{t['id']}/verify-integrity", headers=admin).json()["valid"] is True


def test_report_outside_all_wards_goes_to_manual_triage(client, citizen, admin):
    t = report(client, citizen, *OUTSIDE).json()
    assert t["status"] == "UNROUTABLE" and t["ward"] is None and t["queue"] is None and t["routing"]["reason"] == "OUTSIDE_ALL_WARDS"
    assert [e["event_type"] for e in events(client, admin, t["id"])] == ["SANITATION_SUBMITTED", "SANITATION_UNROUTABLE"]
    q = client.get("/sanitation/queues", headers=admin).json()
    assert q[-1]["code"] == "MANUAL_TRIAGE" and q[-1]["counts"]["UNROUTABLE"] == 1


def test_report_on_shared_boundary_is_ambiguous_not_guessed(client, citizen, admin):
    t = report(client, citizen, *SHARED_VERTEX).json()
    assert t["status"] == "UNROUTABLE" and t["routing"]["reason"] == "OVERLAPPING_WARDS"
    assert set(t["routing"]["candidates"]) == {"DEMO-A", "DEMO-B"}


def test_report_without_gps_is_unroutable_not_routed_by_household(client, citizen):
    t = client.post("/citizen/sanitation-reports", json={"description": "no gps on this one"}, headers=citizen).json()
    assert t["status"] == "UNROUTABLE" and t["routing"]["reason"] == "NO_LOCATION" and t["location"] is None


@pytest.mark.parametrize("patch", [
    {"latitude": 91, "longitude": 72.8}, {"latitude": 19, "longitude": 181}, {"latitude": 0, "longitude": 0},
    {"latitude": 19.0}, {"longitude": 72.8}, {"latitude": 19, "longitude": 72.8, "accuracy_m": -1},
    {"latitude": 19, "longitude": 72.8, "issue_type": "NOT_A_TYPE"}, {"description": "hi", "latitude": 19, "longitude": 72.8},
    {"latitude": "abc", "longitude": 72.8}])
def test_invalid_report_input_rejected(client, citizen, patch):
    body = {"description": "valid description text", **patch}
    assert client.post("/citizen/sanitation-reports", json=body, headers=citizen).status_code == 422


def test_nan_coordinates_rejected(client, citizen):
    raw = '{"description":"valid description text","latitude":NaN,"longitude":72.8}'
    r = client.post("/citizen/sanitation-reports", content=raw, headers={**citizen, "Content-Type": "application/json"})
    assert r.status_code == 422


def test_pin_placed_on_map_is_not_labelled_as_device_gps(client, citizen, admin):
    t = report(client, citizen, *IN_A, location_source="CITIZEN_PLACED").json()
    assert t["location"]["source"] == "CITIZEN_PLACED" and t["location"]["verified"] is False
    assert t["location"]["note"] == "Location placed by the citizen on a map — not independently verified."
    assert "device" not in t["location"]["note"]
    ev = events(client, admin, t["id"])
    assert ev[0]["payload"]["location"]["source"] == "CITIZEN_PLACED" and "placed by the citizen" in ev[1]["payload"]["location"]["note"]
    assert report(client, citizen, *IN_A, location_source="SATELLITE_CERTIFIED").status_code == 422


def test_photo_name_is_sanitised(client, citizen):
    t = report(client, citizen, *IN_A, photo_name="../../etc/pass wd<script>.jpg").json()
    assert "/" not in t["photo_name"] and "<" not in t["photo_name"] and t["photo_name"].endswith(".jpg")


def test_only_citizens_submit_and_only_admin_sees_the_queue(client, citizen, facility):
    assert report(client, login(client, "worker1"), *IN_A).status_code == 403
    assert report(client, facility, *IN_A).status_code == 403
    assert client.get("/sanitation/tickets", headers=facility).status_code == 403
    assert client.get("/sanitation/tickets", headers=citizen).status_code == 403
    assert client.post("/sanitation/tickets/1/status", json={"status": "IN_PROGRESS"}, headers=citizen).status_code == 403


def test_citizens_only_see_their_own_reports(client, citizen):
    with SessionLocal() as db:
        db.add(User(username="citizen2", role=Role.CITIZEN, name="Other", household_id=2, password_hash=hash_password(seed.PASSWORD)))
        db.commit()
    other = login(client, "citizen2")
    a = report(client, citizen, *IN_A).json()["id"]
    b = report(client, other, *IN_B).json()["id"]
    assert [r["id"] for r in client.get("/citizen/sanitation-reports", headers=citizen).json()] == [a]
    assert [r["id"] for r in client.get("/citizen/sanitation-reports", headers=other).json()] == [b]
    assert client.get(f"/sanitation/tickets/{b}/verify-integrity", headers=citizen).status_code == 403
    assert client.get(f"/sanitation/tickets/{a}/verify-integrity", headers=citizen).json()["valid"] is True


# ================================================================ ticket lifecycle + audit
def test_status_flow_and_note_privacy(client, citizen, admin):
    t = report(client, citizen, *IN_A).json()["id"]
    bad = client.post(f"/sanitation/tickets/{t}/status", json={"status": "RESOLVED", "note": "done done"}, headers=admin)
    assert bad.status_code == 409 and bad.json()["detail"]["allowed_status"] == "IN_PROGRESS"
    assert client.post(f"/sanitation/tickets/{t}/status", json={"status": "IN_PROGRESS"}, headers=admin).json()["status"] == "IN_PROGRESS"
    assert client.post(f"/sanitation/tickets/{t}/status", json={"status": "RESOLVED"}, headers=admin).status_code == 422   # note required
    secret = "Crew cleared the pile with the excavator"
    assert client.post(f"/sanitation/tickets/{t}/status", json={"status": "RESOLVED", "note": secret}, headers=admin).json()["status"] == "RESOLVED"
    assert client.post(f"/sanitation/tickets/{t}/status", json={"status": "IN_PROGRESS"}, headers=admin).status_code == 409   # terminal
    ev = events(client, admin, t)
    assert [e["event_type"] for e in ev][-2:] == ["SANITATION_STATUS_CHANGED"] * 2
    assert secret not in json.dumps(ev), "free-text notes must not be written into the immutable chain"
    assert ev[-1]["payload"]["note_sha256"] and client.get(f"/sanitation/tickets/{t}", headers=admin).json()["resolution_note"] == secret
    assert client.get(f"/sanitation/tickets/{t}/verify-integrity", headers=admin).json()["valid"] is True


def test_manual_reroute_of_unroutable_ticket(client, citizen, admin):
    t = report(client, citizen, *OUTSIDE).json()["id"]
    wb = next(f["properties"]["id"] for f in client.get("/geo/wards", headers=admin).json()["features"] if f["properties"]["code"] == "DEMO-B")
    assert client.post(f"/sanitation/tickets/{t}/reroute", json={"ward_id": wb, "reason": "no"}, headers=admin).status_code == 422
    assert client.post(f"/sanitation/tickets/{t}/reroute", json={"ward_id": 999, "reason": "operator decision"}, headers=admin).status_code == 404
    r = client.post(f"/sanitation/tickets/{t}/reroute", json={"ward_id": wb, "reason": "Caller confirmed it is on the Ward B boundary road"}, headers=admin).json()
    assert r["status"] == "ROUTED" and r["ward"]["code"] == "DEMO-B"
    assert [h["method"] for h in r["routing_history"]] == ["POINT_IN_POLYGON", "MANUAL_OVERRIDE"]
    assert r["routing_history"][1]["decided_by_user_id"] is not None and r["routing_history"][0]["decided_by_user_id"] is None
    assert [e["event_type"] for e in events(client, admin, t)] == ["SANITATION_SUBMITTED", "SANITATION_UNROUTABLE", "SANITATION_REROUTED"]
    client.post(f"/sanitation/tickets/{t}/status", json={"status": "IN_PROGRESS"}, headers=admin)
    assert client.post(f"/sanitation/tickets/{t}/reroute", json={"reason": "too late to move it"}, headers=admin).status_code == 409


def test_automatic_reroute_reruns_point_in_polygon(client, citizen, admin):
    t = client.post("/citizen/sanitation-reports", json={"description": "no gps at first"}, headers=citizen).json()["id"]
    r = client.post(f"/sanitation/tickets/{t}/reroute", json={"reason": "retry after boundary reload"}, headers=admin).json()
    assert r["status"] == "UNROUTABLE" and len(r["routing_history"]) == 2 and r["routing_history"][1]["method"] == "POINT_IN_POLYGON"


def test_ticket_chain_detects_tampering_and_load_chains_are_independent(client, citizen, admin):
    t = report(client, citizen, *IN_C).json()["id"]
    client.post(f"/sanitation/tickets/{t}/status", json={"status": "IN_PROGRESS"}, headers=admin)
    ev = events(client, admin, t)
    assert len(ev) == 3
    # the load-only admin corrupt endpoint refuses ticket events
    assert client.post(f"/admin/loads/DL-1002/corrupt-event/{ev[1]['id']}", headers=admin).status_code == 404
    with SessionLocal() as db:   # direct DB tamper: change the routed ward in the stored payload
        row = db.get(EventLog, ev[1]["id"])
        row.payload_json = {**row.payload_json, "ward_code": "DEMO-A"}
        db.commit()
    v = client.get(f"/sanitation/tickets/{t}/verify-integrity", headers=admin).json()
    assert v["valid"] is False and v["broken_at_index"] == 1 and v["broken_event_id"] == ev[1]["id"] and v["load_id"] is None
    for lid in ("DL-1001", "DL-1002", "DL-1003"):
        assert client.get(f"/loads/{lid}/verify-integrity", headers=admin).json()["valid"] is True


def test_reports_geojson_for_the_map(client, citizen, admin):
    report(client, citizen, *IN_A)
    report(client, citizen, *OUTSIDE)
    client.post("/citizen/sanitation-reports", json={"description": "no gps on this report"}, headers=citizen)
    fc = client.get("/geo/reports", headers=admin).json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 2 and fc["without_location"] == 1
    p = fc["features"][0]["properties"]
    assert p["location_verified"] is False and "not independently verified" in p["location_note"]
    assert {f["geometry"]["type"] for f in fc["features"]} == {"Point"}
    assert client.get("/geo/reports", params={"status": "ROUTED"}, headers=admin).json()["features"][0]["properties"]["status"] == "ROUTED"
    assert client.get("/geo/reports", params={"status": "bogus"}, headers=admin).status_code == 422


def test_seeded_demo_tickets_are_routed_and_chained(client, admin):
    with SessionLocal() as db:
        seed.seed_sanitation(db)
    rows = client.get("/sanitation/tickets", headers=admin).json()
    assert len(rows) == 6 and all(r["description"].startswith("[DEMO/SYNTHETIC]") for r in rows)
    by_status = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(r)
        assert client.get(f"/sanitation/tickets/{r['id']}/verify-integrity", headers=admin).json()["valid"] is True
    assert {k: len(v) for k, v in by_status.items()} == {"ROUTED": 3, "IN_PROGRESS": 1, "RESOLVED": 1, "UNROUTABLE": 1}
    assert {r["ward"]["code"] for r in rows if r["ward"]} == {"DEMO-A", "DEMO-B", "DEMO-C"}
    # load scenarios untouched by the sanitation seeding
    ev = client.get("/loads/DL-1002/events", headers=admin).json()
    assert any(e["event_type"] == "RECEIVING_RECORDED" for e in ev)
