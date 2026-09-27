"""PostGIS layer: ward boundary loading, ward assignment, and the spatial queries behind /geo/*.

Conventions
  * All coordinates are WGS84 (EPSG:4326), order lng,lat (GeoJSON / PostGIS), stored as
      - geography(POINT)        households, facilities, sanitation reports  (metre-based distance queries)
      - geometry(MULTIPOLYGON)  wards                                       (point-in-polygon)
      - geometry(LINESTRING)    route paths
  * Every spatial column has a GiST index (see the migration).

CLI:  python -m app.geo load-wards [--file PATH]
      python -m app.geo assign          # recompute household/route ward_id from locations
      python -m app.geo route-backfill  # route legacy reports that have a location but no routing decision
      python -m app.geo status
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from typing import Any, Optional

from geoalchemy2 import Geography, Geometry
from shapely.geometry import MultiPolygon, Polygon, shape
from sqlalchemy import cast, func, select, text
from sqlalchemy.orm import Session

from .config import MAX_QUERY_RADIUS_M, WARD_BOUNDARY_SOURCE
from .errors import ServiceError
from .models import (AuthorityQueue, Facility, Household, Route, SanitationReport, Ward, utcnow)


# ------------------------------------------------------------------ input validation
def validate_lat_lng(lat: float, lng: float) -> None:
    """Raise ServiceError(422) unless this is a plausible, usable WGS84 coordinate."""
    for name, v, lim in (("latitude", lat, 90), ("longitude", lng, 180)):
        if v is None or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
            raise ServiceError(422, "BAD_COORDINATES", f"{name} must be a finite number.")
        if abs(v) > lim:
            raise ServiceError(422, "BAD_COORDINATES", f"{name} must be between -{lim} and {lim}.")
    if lat == 0 and lng == 0:
        raise ServiceError(422, "BAD_COORDINATES", "0,0 is treated as 'no GPS fix', not a real location.")


def point_wkt(lat: float, lng: float) -> str:
    return f"SRID=4326;POINT({lng:.7f} {lat:.7f})"


def _pt(lat: float, lng: float):
    return func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)


def _geog(lat: float, lng: float):
    return cast(_pt(lat, lng), Geography(geometry_type="POINT", srid=4326))


# ------------------------------------------------------------------ ward loading
class WardSourceError(ValueError):
    pass


def parse_ward_source(path: str) -> dict[str, Any]:
    """Read + validate a ward GeoJSON file. Nothing touches the database here."""
    try:
        with open(path, encoding="utf-8") as f:
            fc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise WardSourceError(f"Cannot read ward source '{path}': {e}") from e
    if fc.get("type") != "FeatureCollection" or not fc.get("features"):
        raise WardSourceError("Ward source must be a GeoJSON FeatureCollection with at least one feature.")

    meta = fc.get("civicgrid_source") or {}
    for key in ("name", "label", "version"):
        if not meta.get(key):
            raise WardSourceError(f"'civicgrid_source.{key}' is required so every ward states where it came from.")
    is_official = bool(meta.get("is_official", False))

    wards, seen = [], set()
    for i, feat in enumerate(fc["features"]):
        props = feat.get("properties") or {}
        code, name, queue = props.get("code"), props.get("name"), props.get("queue") or {}
        if not code or not name:
            raise WardSourceError(f"Feature {i}: properties.code and properties.name are required.")
        if code in seen:
            raise WardSourceError(f"Duplicate ward code '{code}'.")
        seen.add(code)
        if not queue.get("code") or not queue.get("name"):
            raise WardSourceError(f"Ward {code}: properties.queue.code and .name are required (routing needs a queue).")
        geom_json = feat.get("geometry") or {}
        if geom_json.get("type") not in ("Polygon", "MultiPolygon"):
            raise WardSourceError(f"Ward {code}: geometry must be Polygon or MultiPolygon.")
        try:
            g = shape(geom_json)
        except Exception as e:  # shapely raises several error types for malformed rings
            raise WardSourceError(f"Ward {code}: malformed geometry ({e}).") from e
        minx, miny, maxx, maxy = g.bounds
        if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
            raise WardSourceError(f"Ward {code}: coordinates outside WGS84 range - source must be EPSG:4326 (lng,lat).")
        if g.is_empty or not g.is_valid:
            from shapely.validation import explain_validity
            raise WardSourceError(f"Ward {code}: invalid geometry - {explain_validity(g)}.")
        if isinstance(g, Polygon):
            g = MultiPolygon([g])
        wards.append({"code": code, "name": name, "geom": g, "queue": queue})

    for a in range(len(wards)):
        for b in range(a + 1, len(wards)):
            if wards[a]["geom"].intersection(wards[b]["geom"]).area > 1e-12:
                raise WardSourceError(
                    f"Wards {wards[a]['code']} and {wards[b]['code']} overlap. Point-in-ward would be ambiguous; fix the source.")
    return {"meta": {"name": meta["name"], "label": meta["label"], "version": str(meta["version"]), "is_official": is_official},
            "wards": wards}


def load_wards(db: Session, path: Optional[str] = None) -> dict:
    """Upsert wards (and their authority queues) by code from the configured GeoJSON source."""
    path = path or WARD_BOUNDARY_SOURCE
    parsed = parse_ward_source(path)
    meta = parsed["meta"]
    now = utcnow()
    created = updated = 0
    for w in parsed["wards"]:
        q = db.execute(select(AuthorityQueue).where(AuthorityQueue.code == w["queue"]["code"])).scalar_one_or_none()
        if q is None:
            q = AuthorityQueue(code=w["queue"]["code"], name=w["queue"]["name"], description=w["queue"].get("description", ""))
            db.add(q)
            db.flush()
        else:
            q.name = w["queue"]["name"]
        ward = db.execute(select(Ward).where(Ward.code == w["code"])).scalar_one_or_none()
        boundary = f"SRID=4326;{w['geom'].wkt}"
        if ward is None:
            ward = Ward(code=w["code"], name=w["name"], boundary=boundary, queue_id=q.id)
            db.add(ward)
            created += 1
        else:
            ward.name, ward.boundary, ward.queue_id = w["name"], boundary, q.id
            updated += 1
        ward.source_name, ward.source_label = meta["name"], meta["label"]
        ward.source_version, ward.is_official, ward.loaded_at = meta["version"], meta["is_official"], now
    db.flush()
    bad = db.execute(text("SELECT code FROM wards WHERE NOT ST_IsValid(boundary)")).scalars().all()
    if bad:
        raise WardSourceError(f"PostGIS reports invalid boundaries for {bad}; nothing committed.")
    db.commit()
    return {"created": created, "updated": updated, "source": meta, "path": path}


def assign_wards(db: Session) -> dict:
    """Derive ward_id (and the legacy ward label) for households and routes from geometry - never by hand."""
    hh = db.execute(text(
        "UPDATE households h SET ward_id = w.id, ward = w.name FROM wards w "
        "WHERE h.location IS NOT NULL AND ST_Covers(w.boundary, h.location::geometry)")).rowcount
    # A route belongs to the ward that contains most of its households.
    rt = db.execute(text(
        "UPDATE routes r SET ward_id = x.ward_id, ward = w.name FROM ("
        "  SELECT DISTINCT ON (route_id) route_id, ward_id FROM ("
        "    SELECT route_id, ward_id, count(*) n FROM households "
        "    WHERE ward_id IS NOT NULL AND route_id IS NOT NULL GROUP BY route_id, ward_id) t "
        "  ORDER BY route_id, n DESC, ward_id) x JOIN wards w ON w.id = x.ward_id WHERE r.id = x.route_id")).rowcount
    db.commit()
    return {"households_assigned": hh, "routes_assigned": rt}


def build_route_paths(db: Session) -> int:
    """Route geometry = its located households in stop order (household id order; a demo simplification)."""
    n = db.execute(text(
        "UPDATE routes r SET path = ST_SetSRID(ST_MakeLine(ARRAY("
        "  SELECT h.location::geometry FROM households h "
        "  WHERE h.route_id = r.id AND h.location IS NOT NULL ORDER BY h.id)), 4326) "
        "WHERE (SELECT count(*) FROM households h WHERE h.route_id = r.id AND h.location IS NOT NULL) >= 2")).rowcount
    db.commit()
    return n


# ------------------------------------------------------------------ queries
def ward_source_summary(db: Session) -> dict:
    rows = db.execute(select(Ward.source_name, Ward.source_label, Ward.source_version, Ward.is_official,
                             func.count()).group_by(Ward.source_name, Ward.source_label, Ward.source_version, Ward.is_official)).all()
    return {"sources": [{"name": r[0], "label": r[1], "version": r[2], "is_official": r[3], "ward_count": r[4]} for r in rows],
            "all_official": bool(rows) and all(r[3] for r in rows),
            "label": rows[0][1] if len(rows) == 1 else " / ".join(sorted({r[1] for r in rows}))}


def wards_geojson(db: Session) -> dict:
    rows = db.execute(select(Ward, func.ST_AsGeoJSON(Ward.boundary), AuthorityQueue)
                      .outerjoin(AuthorityQueue, AuthorityQueue.id == Ward.queue_id).order_by(Ward.code)).all()
    feats = [{"type": "Feature", "geometry": json.loads(gj), "properties": {
        "id": w.id, "code": w.code, "name": w.name, "queue_code": q.code if q else None, "queue_name": q.name if q else None,
        "source_name": w.source_name, "source_version": w.source_version, "is_official": w.is_official, "source_label": w.source_label}}
        for w, gj, q in rows]
    return {"type": "FeatureCollection", "features": feats, "source": ward_source_summary(db)}


def ward_at(db: Session, lat: float, lng: float) -> dict:
    """Point-in-polygon. Returns every ward covering the point (normally exactly one)."""
    validate_lat_lng(lat, lng)
    rows = db.execute(select(Ward, AuthorityQueue).outerjoin(AuthorityQueue, AuthorityQueue.id == Ward.queue_id)
                      .where(func.ST_Covers(Ward.boundary, _pt(lat, lng))).order_by(Ward.id)).all()
    wards = [{"id": w.id, "code": w.code, "name": w.name, "queue": {"id": q.id, "code": q.code, "name": q.name} if q else None,
              "source_label": w.source_label, "is_official": w.is_official} for w, q in rows]
    outcome = "ROUTABLE" if len(wards) == 1 and wards[0]["queue"] else ("OUTSIDE_ALL_WARDS" if not wards else "AMBIGUOUS_OR_NO_QUEUE")
    return {"latitude": lat, "longitude": lng, "outcome": outcome, "wards": wards, "ward": wards[0] if len(wards) == 1 else None}


def _radius(radius_m: float) -> float:
    if radius_m <= 0 or radius_m > MAX_QUERY_RADIUS_M:
        raise ServiceError(422, "BAD_RADIUS", f"radius_m must be between 1 and {MAX_QUERY_RADIUS_M}.")
    return radius_m


def nearby_reports(db: Session, lat: float, lng: float, radius_m: float, limit: int = 50, status: Optional[str] = None) -> list[dict]:
    validate_lat_lng(lat, lng)
    pt = _geog(lat, lng)
    dist = func.ST_Distance(SanitationReport.location, pt)
    stmt = (select(SanitationReport, dist.label("d")).where(SanitationReport.location.is_not(None),
            func.ST_DWithin(SanitationReport.location, pt, _radius(radius_m))).order_by(dist).limit(min(limit, 200)))
    if status:
        stmt = stmt.where(SanitationReport.status == status)
    return [{"id": r.id, "issue_type": r.issue_type.value, "status": r.status.value, "ward_id": r.ward_id,
             "distance_m": round(d, 1), "created_at": r.created_at.isoformat()} for r, d in db.execute(stmt).all()]


def nearby_households(db: Session, lat: float, lng: float, radius_m: float, limit: int = 100) -> list[dict]:
    """Household ids + coordinates only (no owner names or addresses: home locations are sensitive)."""
    validate_lat_lng(lat, lng)
    pt = _geog(lat, lng)
    dist = func.ST_Distance(Household.location, pt)
    rows = db.execute(select(Household.id, Household.ward_id, Household.route_id, dist.label("d"),
                             func.ST_Y(cast(Household.location, Geometry)), func.ST_X(cast(Household.location, Geometry)))
                      .where(Household.location.is_not(None), func.ST_DWithin(Household.location, pt, _radius(radius_m)))
                      .order_by(dist).limit(min(limit, 500))).all()
    return [{"id": i, "ward_id": w, "route_id": r, "distance_m": round(d, 1), "latitude": la, "longitude": lo}
            for i, w, r, d, la, lo in rows]


def utm_srid(lat: float, lng: float) -> int:
    """UTM zone for a point, so DBSCAN's eps can be given in metres."""
    return (32600 if lat >= 0 else 32700) + int((lng + 180) // 6) + 1


def household_clusters(db: Session, ward_id: Optional[int], eps_m: float = 250, min_points: int = 2) -> dict:
    """Density clusters (ST_ClusterDBSCAN) of located households, eps in metres via a UTM projection."""
    if not (10 <= eps_m <= 5000) or not (1 <= min_points <= 50):
        raise ServiceError(422, "BAD_CLUSTER_PARAMS", "eps_m must be 10-5000 and min_points 1-50.")
    where = "location IS NOT NULL" + (" AND ward_id = :ward" if ward_id else "")
    params: dict[str, Any] = {"eps": eps_m, "minpts": min_points}
    if ward_id:
        params["ward"] = ward_id
    c = db.execute(text(f"SELECT avg(ST_Y(location::geometry)), avg(ST_X(location::geometry)) FROM households WHERE {where}"), params).one()
    if c[0] is None:
        return {"srid_used": None, "eps_m": eps_m, "min_points": min_points, "clusters": [], "unclustered": 0}
    srid = utm_srid(c[0], c[1])
    params["srid"] = srid
    rows = db.execute(text(f"""
        SELECT cid, count(*) AS n, array_agg(id ORDER BY id) AS ids,
               ST_AsGeoJSON(ST_Centroid(ST_Collect(geom))) AS centroid
        FROM (SELECT id, location::geometry AS geom,
                     ST_ClusterDBSCAN(ST_Transform(location::geometry, :srid), eps := :eps, minpoints := :minpts) OVER () AS cid
              FROM households WHERE {where}) t
        GROUP BY cid ORDER BY cid NULLS LAST"""), params).all()
    clusters = [{"cluster": r.cid, "size": r.n, "household_ids": list(r.ids), "centroid": json.loads(r.centroid)}
                for r in rows if r.cid is not None]
    return {"srid_used": srid, "eps_m": eps_m, "min_points": min_points, "clusters": clusters,
            "unclustered": sum(r.n for r in rows if r.cid is None)}


def facilities_geojson(db: Session) -> dict:
    rows = db.execute(select(Facility, func.ST_AsGeoJSON(cast(Facility.location, Geometry))).where(Facility.location.is_not(None)).order_by(Facility.id)).all()
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": json.loads(gj), "properties": {"id": f.id, "name": f.name, "kind": f.kind}} for f, gj in rows]}


def nearest_facilities(db: Session, lat: float, lng: float, limit: int = 3, kind: Optional[str] = None) -> list[dict]:
    validate_lat_lng(lat, lng)
    pt = _geog(lat, lng)
    dist = func.ST_Distance(Facility.location, pt)
    stmt = select(Facility, dist.label("d")).where(Facility.location.is_not(None)).order_by(dist).limit(max(1, min(limit, 20)))
    if kind:
        stmt = stmt.where(Facility.kind.ilike(f"%{kind}%"))
    out = []
    for f, d in db.execute(stmt).all():
        w = ward_at(db, *_facility_latlng(db, f.id)) if f.location is not None else None
        out.append({"id": f.id, "name": f.name, "kind": f.kind, "distance_m": round(d, 1),
                    "ward": w["ward"]["name"] if w and w["ward"] else None})
    return out


def _facility_latlng(db: Session, facility_id: int) -> tuple[float, float]:
    r = db.execute(select(func.ST_Y(cast(Facility.location, Geometry)), func.ST_X(cast(Facility.location, Geometry)))
                   .where(Facility.id == facility_id)).one()
    return r[0], r[1]


def route_detail(db: Session, route_id: int) -> dict:
    route = db.get(Route, route_id)
    if not route:
        raise ServiceError(404, "ROUTE_NOT_FOUND", f"No route {route_id}.")
    length = db.scalar(select(func.ST_Length(cast(Route.path, Geography))).where(Route.id == route_id))
    path = db.scalar(select(func.ST_AsGeoJSON(Route.path)).where(Route.id == route_id))
    stops = db.execute(select(Household.id, func.ST_Y(cast(Household.location, Geometry)), func.ST_X(cast(Household.location, Geometry)))
                       .where(Household.route_id == route_id, Household.location.is_not(None)).order_by(Household.id)).all()
    crossed = db.execute(select(Ward.id, Ward.code, Ward.name).where(func.ST_Intersects(
        Ward.boundary, select(Route.path).where(Route.id == route_id).scalar_subquery())).order_by(Ward.id)).all()
    home = db.get(Ward, route.ward_id) if route.ward_id else None
    return {"id": route.id, "ward": {"id": home.id, "code": home.code, "name": home.name} if home else None,
            "length_m": round(length, 1) if length else None, "path": json.loads(path) if path else None,
            "stops": [{"household_id": i, "latitude": la, "longitude": lo} for i, la, lo in stops],
            "wards_crossed": [{"id": i, "code": c, "name": n} for i, c, n in crossed]}


def parse_area(geojson: dict) -> str:
    """Validate a user-supplied Polygon/MultiPolygon and return its EWKT. Rejects anything malformed or huge."""
    if not isinstance(geojson, dict) or geojson.get("type") not in ("Polygon", "MultiPolygon"):
        raise ServiceError(422, "BAD_AREA", "area must be a GeoJSON Polygon or MultiPolygon geometry.")
    try:
        g = shape(geojson)
    except Exception as e:
        raise ServiceError(422, "BAD_AREA", f"Malformed geometry: {e}") from e
    n = sum(len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors) for p in (g.geoms if hasattr(g, "geoms") else [g]))
    if n > 1000:
        raise ServiceError(422, "BAD_AREA", "Area has too many vertices (max 1000).")
    minx, miny, maxx, maxy = g.bounds
    if g.is_empty or not (-180 <= minx and maxx <= 180 and -90 <= miny and maxy <= 90):
        raise ServiceError(422, "BAD_AREA", "Area is empty or outside WGS84 range.")
    if not g.is_valid:
        raise ServiceError(422, "BAD_AREA", "Area geometry is not valid (self-intersecting or degenerate).")
    if (maxx - minx) > 2 or (maxy - miny) > 2:
        raise ServiceError(422, "BAD_AREA", "Area is larger than 2 degrees in either direction.")
    return f"SRID=4326;{g.wkt}"


def area_query(db: Session, geojson: dict) -> dict:
    """What is inside/crossing an arbitrary area: households, sanitation reports, facilities, routes, wards."""
    ewkt = parse_area(geojson)
    area = func.ST_GeomFromEWKT(ewkt)
    hh = db.scalar(select(func.count()).select_from(Household).where(func.ST_Covers(area, cast(Household.location, Geometry))))
    rep = db.execute(select(SanitationReport.status, func.count()).where(func.ST_Covers(area, cast(SanitationReport.location, Geometry)))
                     .group_by(SanitationReport.status)).all()
    fac = db.execute(select(Facility.id, Facility.name).where(func.ST_Covers(area, cast(Facility.location, Geometry)))).all()
    routes = db.execute(select(Route.id).where(func.ST_Intersects(area, Route.path)).order_by(Route.id)).scalars().all()
    wards = db.execute(select(Ward.id, Ward.code, Ward.name).where(func.ST_Intersects(area, Ward.boundary)).order_by(Ward.id)).all()
    return {"households": hh or 0, "sanitation_reports_by_status": {s.value: n for s, n in rep},
            "facilities": [{"id": i, "name": n} for i, n in fac], "route_ids": list(routes),
            "wards": [{"id": i, "code": c, "name": n} for i, c, n in wards]}


# ------------------------------------------------------------------ CLI
def _cli(argv: list[str]) -> int:
    from .db import SessionLocal
    cmd = argv[0] if argv else "status"
    with SessionLocal() as db:
        if cmd == "load-wards":
            path = argv[argv.index("--file") + 1] if "--file" in argv else None
            try:
                r = load_wards(db, path)
            except WardSourceError as e:
                print(f"REFUSED: {e}")
                return 2
            print(f"Wards: {r['created']} created, {r['updated']} updated from {r['path']}")
            print(f"Source: {r['source']['name']} v{r['source']['version']} | official={r['source']['is_official']} | {r['source']['label']}")
            print("Assignments:", assign_wards(db))
        elif cmd == "assign":
            print(assign_wards(db))
        elif cmd == "route-backfill":
            from .sanitation import route_backfill
            print(route_backfill(db))
        elif cmd == "status":
            print(json.dumps(ward_source_summary(db), indent=2))
        else:
            print(__doc__)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
