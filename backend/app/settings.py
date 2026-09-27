"""Runtime settings for evidence + audit selection.

Read at CALL time (not import time) so tests and operators can change behaviour through the environment
without re-importing the app.

REQUIRE_FILE_EVIDENCE
    true  (default; docker-compose sets it explicitly) - the workflow needs REAL files:
          * FLAGGED -> EVIDENCE_PENDING needs at least one uploaded FILE_EVIDENCE item
          * corroboration needs a completed, independent audit that carries file evidence
          * the legacy note-only / manual-audit-number paths are refused
    false - legacy paths are accepted for backward compatibility (used by the Phase 0/1 tests and by the
          DL-1003 seed). They are recorded as NOTE / LEGACY_MANUAL_ENTRY and are NEVER presented as
          evidence-backed.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

_TRUE = {"1", "true", "yes", "on"}


def require_file_evidence() -> bool:
    return os.getenv("REQUIRE_FILE_EVIDENCE", "true").strip().lower() in _TRUE


def evidence_storage_backend() -> str:
    return os.getenv("EVIDENCE_STORAGE_BACKEND", "local")


def evidence_storage_dir() -> str:
    return os.getenv("EVIDENCE_STORAGE_DIR", str(Path(__file__).resolve().parents[1] / "storage" / "evidence"))


def max_image_bytes() -> int:
    return int(os.getenv("EVIDENCE_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))


def max_video_bytes() -> int:
    return int(os.getenv("EVIDENCE_MAX_VIDEO_BYTES", str(50 * 1024 * 1024)))


def max_image_pixels() -> int:
    return int(os.getenv("EVIDENCE_MAX_IMAGE_PIXELS", "40000000"))


def public_evidence_config() -> dict[str, Any]:
    return {
        "require_file_evidence": require_file_evidence(),
        "max_image_bytes": max_image_bytes(),
        "max_video_bytes": max_video_bytes(),
        "allowed_types": {
            "image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"], "image/webp": [".webp"],
            "video/mp4": [".mp4", ".m4v"], "video/quicktime": [".mov"], "video/webm": [".webm"],
        },
        "gps_note": "GPS is reported by the uploader's device and is UNVERIFIED: it can be wrong or spoofed.",
    }


# --------------------------------------------------------------------------- audit selection
DEFAULT_WEIGHTS = {
    "quantity_variance": 0.40,
    "stream_mismatch": 0.20,
    "prior_corroborated_discrepancies": 0.20,
    "adverse_audit_history": 0.10,
    "repeat_complaints": 0.05,
    "segregation_pattern_deviation": 0.05,
}
DEFAULT_CAPS = {
    "quantity_variance": 0.30,            # a |received-declared|/declared of 30% or more scores the maximum
    "prior_corroborated_discrepancies": 3,  # 3 or more scores the maximum
    "repeat_complaints": 3,
    "segregation_pattern_deviation": 0.50,
}


@dataclass
class AuditConfig:
    """Everything the selection engine uses. Transparent on purpose: GET /audit-center/config returns this."""
    random_sample_pct: float = 20.0      # RANDOM: % of eligible loads audited per run
    risk_threshold: float = 0.30         # RISK_BASED: loads scoring >= this are selected ...
    risk_max_selected: int = 5           # ... at most this many per run (highest scores first)
    cooldown_days: int = 7               # RANDOM/RISK: skip loads audited (completed) within this many days. MANUAL ignores it.
    lookback_days: int = 90              # history window for the history-based factors
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    caps: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CAPS))

    def validate(self) -> "AuditConfig":
        if not (0 <= self.random_sample_pct <= 100):
            raise ValueError("random_sample_pct must be between 0 and 100")
        if not (0 <= self.risk_threshold <= 1):
            raise ValueError("risk_threshold must be between 0 and 1")
        if not (1 <= self.risk_max_selected <= 50):
            raise ValueError("risk_max_selected must be between 1 and 50")
        if not (0 <= self.cooldown_days <= 365) or not (1 <= self.lookback_days <= 730):
            raise ValueError("cooldown_days must be 0-365 and lookback_days 1-730")
        unknown = set(self.weights) - set(DEFAULT_WEIGHTS)
        if unknown:
            raise ValueError(f"unknown risk factors in weights: {sorted(unknown)}")
        if any(w < 0 for w in self.weights.values()) or sum(self.weights.values()) <= 0:
            raise ValueError("weights must be non-negative and not all zero")
        if any(c <= 0 for c in self.caps.values()):
            raise ValueError("caps must be positive")
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_audit_config(overrides: Optional[dict[str, Any]] = None) -> AuditConfig:
    """defaults <- optional JSON file (AUDIT_CONFIG_PATH) <- per-run overrides (scalars only)."""
    cfg = AuditConfig()
    path = os.getenv("AUDIT_CONFIG_PATH")
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for k, v in data.items():
            if k in ("weights", "caps"):
                getattr(cfg, k).update(v)
            elif hasattr(cfg, k):
                setattr(cfg, k, v)
            else:
                raise ValueError(f"unknown audit config key '{k}' in {path}")
    for k in ("random_sample_pct", "risk_threshold", "risk_max_selected", "cooldown_days"):
        if overrides and overrides.get(k) is not None:
            setattr(cfg, k, overrides[k])
    return cfg.validate()
