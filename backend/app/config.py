import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://civicgrid:civicgrid@localhost:5432/civicgrid",
)
JWT_SECRET = os.getenv("JWT_SECRET", "demo-only-secret-change-me")
JWT_ALG = "HS256"
JWT_EXPIRE_MINUTES = 12 * 60
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

# Hash chain: fixed genesis "previous hash" for the first event of every load.
GENESIS_HASH = "0" * 64

# Cross-check engine thresholds (assumptions - see README "What is real vs simplified").
QUANTITY_TOLERANCE = float(os.getenv("QUANTITY_TOLERANCE", "0.10"))   # 10% weighing tolerance
SEGREGATED_SHARE_THRESHOLD = float(os.getenv("SEGREGATED_SHARE_THRESHOLD", "0.75"))

# ---- Geospatial (Phase 1)
# Ward boundaries are loaded from a GeoJSON FeatureCollection. The bundled default is SYNTHETIC DEMO DATA.
# Point WARD_BOUNDARY_SOURCE at an official municipal GeoJSON (EPSG:4326 / WGS84) to replace it - see README.
WARD_BOUNDARY_SOURCE = os.getenv(
    "WARD_BOUNDARY_SOURCE",
    os.path.join(os.path.dirname(__file__), "data", "demo_wards.geojson"),
)
LOCATION_NOTE = "Location reported by device — not independently verified."
LOCATION_NOTES = {
    "DEVICE_REPORTED": LOCATION_NOTE,   # browser/OS geolocation
    "CITIZEN_PLACED": "Location placed by the citizen on a map — not independently verified.",
}
MAX_QUERY_RADIUS_M = 50_000
