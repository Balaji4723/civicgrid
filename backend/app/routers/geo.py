"""PostGIS-backed spatial queries. Household coordinates are sensitive, so household endpoints are municipal-admin only
and return ids + coordinates (no names or addresses)."""
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import geo
from ..auth import current_user, require_roles
from ..db import get_db
from ..models import Role, TicketStatus, User
from ..sanitation import ticket_rows

router = APIRouter(prefix="/geo", tags=["geo (PostGIS)"])
admin = require_roles(Role.MUNICIPAL_ADMIN)
staff = require_roles(Role.FACILITY, Role.MUNICIPAL_ADMIN)

Lat = Query(..., ge=-90, le=90, allow_inf_nan=False)
Lng = Query(..., ge=-180, le=180, allow_inf_nan=False)


class AreaIn(BaseModel):
    area: dict[str, Any]  # GeoJSON Polygon / MultiPolygon


@router.get("/wards")
def wards(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Ward polygons as GeoJSON. Includes the boundary source label - the default set is SYNTHETIC DEMO DATA."""
    return geo.wards_geojson(db)


@router.get("/ward-lookup")
def ward_lookup(lat: float = Lat, lng: float = Lng, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Point-in-polygon preview: which ward / authority queue would a report at this point be routed to?"""
    return geo.ward_at(db, lat, lng)


@router.get("/reports")
def reports_geojson(status: Optional[TicketStatus] = None, ward_id: Optional[int] = None, user: User = Depends(admin), db: Session = Depends(get_db)):
    rows = ticket_rows(db, ward_id=ward_id, status=status)
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["location"]["longitude"], r["location"]["latitude"]]},
              "properties": {k: r[k] for k in ("id", "issue_type", "status", "description", "created_at", "ward", "queue", "photo_name")}
                            | {"location_source": r["location"]["source"], "location_verified": r["location"]["verified"],
                               "location_note": r["location"]["note"]}}
             for r in rows if r["location"]]
    return {"type": "FeatureCollection", "features": feats, "without_location": sum(1 for r in rows if not r["location"])}


@router.get("/reports/nearby")
def reports_nearby(lat: float = Lat, lng: float = Lng, radius_m: float = Query(500, gt=0, le=geo.MAX_QUERY_RADIUS_M),
                   limit: int = Query(50, ge=1, le=200), user: User = Depends(admin), db: Session = Depends(get_db)):
    return geo.nearby_reports(db, lat, lng, radius_m, limit)


@router.get("/households/nearby")
def households_nearby(lat: float = Lat, lng: float = Lng, radius_m: float = Query(500, gt=0, le=geo.MAX_QUERY_RADIUS_M),
                      limit: int = Query(100, ge=1, le=500), user: User = Depends(admin), db: Session = Depends(get_db)):
    return geo.nearby_households(db, lat, lng, radius_m, limit)


@router.get("/households/clusters")
def households_clusters(ward_id: Optional[int] = Query(None, ge=1), eps_m: float = Query(250, ge=10, le=5000),
                        min_points: int = Query(2, ge=1, le=50), user: User = Depends(admin), db: Session = Depends(get_db)):
    return geo.household_clusters(db, ward_id, eps_m, min_points)


@router.get("/facilities")
def facilities(user: User = Depends(staff), db: Session = Depends(get_db)):
    return geo.facilities_geojson(db)


@router.get("/facilities/nearest")
def facilities_nearest(lat: float = Lat, lng: float = Lng, limit: int = Query(3, ge=1, le=20), kind: Optional[str] = Query(None, max_length=40),
                       user: User = Depends(staff), db: Session = Depends(get_db)):
    return geo.nearest_facilities(db, lat, lng, limit, kind)


@router.get("/routes/{route_id}")
def route(route_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    return geo.route_detail(db, route_id)


@router.post("/area/query")
def area(body: AreaIn, user: User = Depends(admin), db: Session = Depends(get_db)):
    return geo.area_query(db, body.area)
