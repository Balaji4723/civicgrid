"""Audit selection: WHICH loads get an independent audit, and WHY.

Two automatic methods plus MANUAL (see audits.create_manual_audit). Nothing is selected without a stored reason.

ELIGIBLE  a load that has a facility receiving record (status VERIFIED or DISPUTED), has no open audit, and (for
          RANDOM / RISK_BASED) was not audited to completion within `cooldown_days`.

RANDOM      k = max(1, round(pct% x N)) loads drawn without replacement with random.Random(seed). The seed is
            stored, so the exact draw can be reproduced. It is a plain uniform sample: it makes no claim to be
            statistically optimal, and it does not look at risk at all.

RISK_BASED  score(load) = sum_i  weight_i / sum(weights) x min(raw_i / cap_i, 1)      -> a number in [0, 1]
            Loads with score >= risk_threshold are selected, highest first, at most risk_max_selected.
            Every factor's raw value, cap, normalised value, weight, contribution and a plain-English
            explanation are stored with the audit. This is a transparent ranking, NOT a validated statistical
            model; weights and thresholds are policy choices for the municipality (CONFIGURABLE).
            A deterministic ranking can be gamed by anyone who learns the rule - run RANDOM as well.

Factors (all configurable in settings.AuditConfig):
  quantity_variance                  |received - declared| / declared for THIS load
  stream_mismatch                    this load's stream was flagged (declared segregated but facility says unacceptable)
  prior_corroborated_discrepancies   the worker's OTHER recent discrepancies that were corroborated and are still open,
                                     or were resolved as attributable to the worker (process/facility findings do NOT count)
  adverse_audit_history              share of the worker's recent completed audits that supported the facility's record
  repeat_complaints                  MISSED_COLLECTION sanitation tickets in the route's ward (an area-level, weak proxy)
  segregation_pattern_deviation      how far this load's segregated share is from the worker's own usual share
"""
from __future__ import annotations

import math
import random
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .crosscheck import quantity_mismatch, signals_agree
from .errors import ServiceError
from .models import (Audit, AuditStatus, CollectionEvent, CollectionStatus, DigitalLoad, DiscrepancyEvent, DiscrepancyStatus,
                     DiscrepancyType, IssueType, LoadStatus, ReceivingRecord, Route, SanitationReport, utcnow)
from .services import build_declaration
from .settings import AuditConfig

FACTOR_LABELS = {
    "quantity_variance": "Quantity variance (received vs declared)",
    "stream_mismatch": "Stream mismatch",
    "prior_corroborated_discrepancies": "Worker's prior corroborated discrepancies",
    "adverse_audit_history": "Adverse audit history",
    "repeat_complaints": "Repeat collection complaints in the ward",
    "segregation_pattern_deviation": "Unusual segregation pattern",
}
ATTRIBUTABLE_OPEN = (DiscrepancyStatus.CORROBORATED, DiscrepancyStatus.INVESTIGATING)


# ---------------------------------------------------------------- eligibility
def eligible_loads(db: Session, cfg: AuditConfig, now: datetime, ignore_cooldown: bool = False) -> list[DigitalLoad]:
    loads = db.scalars(select(DigitalLoad).where(DigitalLoad.status.in_([LoadStatus.VERIFIED, LoadStatus.DISPUTED])).order_by(DigitalLoad.id)).all()
    out = []
    for load in loads:
        if not db.scalars(select(ReceivingRecord.id).where(ReceivingRecord.load_id == load.id)).first():
            continue
        if db.scalars(select(Audit.id).where(Audit.load_id == load.id, Audit.status.in_([AuditStatus.PENDING, AuditStatus.IN_PROGRESS]))).first():
            continue
        if not ignore_cooldown and cfg.cooldown_days:
            recent = db.scalars(select(Audit.id).where(Audit.load_id == load.id, Audit.status == AuditStatus.COMPLETED,
                                                       Audit.completed_at >= now - timedelta(days=cfg.cooldown_days))).first()
            if recent:
                continue
        out.append(load)
    return out


# ---------------------------------------------------------------- risk
def _factor(key: str, raw: float, cap: float, weight: float, total_weight: float, raw_text: str, why: str) -> dict[str, Any]:
    normalised = min(max(raw, 0.0) / cap, 1.0) if cap else 0.0
    contribution = (weight / total_weight) * normalised if total_weight else 0.0
    return {"key": key, "label": FACTOR_LABELS[key], "raw": round(raw, 4), "raw_text": raw_text, "cap": cap,
            "normalised": round(normalised, 4), "weight": weight, "weight_share": round(weight / total_weight, 4) if total_weight else 0.0,
            "contribution": round(contribution, 4), "explanation": why}


def _segregated_share(db: Session, load_id: str) -> Optional[float]:
    evs = db.scalars(select(CollectionEvent.status).where(CollectionEvent.load_id == load_id)).all()
    return sum(1 for s in evs if s == CollectionStatus.SEGREGATED) / len(evs) if evs else None


def compute_risk(db: Session, load: DigitalLoad, cfg: AuditConfig, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or utcnow()
    since = now - timedelta(days=cfg.lookback_days)
    route = db.get(Route, load.route_id)
    worker_id = route.worker_id if route else None
    rec = db.scalars(select(ReceivingRecord).where(ReceivingRecord.load_id == load.id).order_by(ReceivingRecord.id)).first()
    decl = build_declaration(db, load)
    W, C = cfg.weights, cfg.caps
    tw = sum(W.values())
    f: list[dict[str, Any]] = []

    # 1 quantity variance
    var = abs(rec.quantity - decl["quantity"]) / decl["quantity"] if rec and decl["quantity"] else 0.0
    f.append(_factor("quantity_variance", var, C["quantity_variance"], W["quantity_variance"], tw,
                     f"{var:.1%}" + (f" ({rec.quantity} kg received vs {decl['quantity']} kg declared)" if rec else ""),
                     f"Received differs from declared by {var:.1%}; {C['quantity_variance']:.0%} or more scores the maximum."))
    # 2 stream mismatch
    has_stream = bool(db.scalars(select(DiscrepancyEvent.id).where(DiscrepancyEvent.load_id == load.id, DiscrepancyEvent.type == DiscrepancyType.STREAM)).first())
    f.append(_factor("stream_mismatch", 1.0 if has_stream else 0.0, 1.0, W["stream_mismatch"], tw, "yes" if has_stream else "no",
                     "The facility marked a load declared as segregated as unacceptable." if has_stream else "No stream mismatch on this load."))
    # 3 prior corroborated discrepancies (worker-attributable only)
    prior = 0
    if worker_id:
        rows = db.execute(select(DiscrepancyEvent).join(DigitalLoad, DigitalLoad.id == DiscrepancyEvent.load_id)
                          .join(Route, Route.id == DigitalLoad.route_id)
                          .where(Route.worker_id == worker_id, DiscrepancyEvent.load_id != load.id, DiscrepancyEvent.created_at >= since)).scalars().all()
        for d in rows:
            if d.status in ATTRIBUTABLE_OPEN:
                prior += 1
            elif d.status in (DiscrepancyStatus.RESOLVED, DiscrepancyStatus.CLOSED) and ((d.details_json or {}).get("resolution") or {}).get("attributed_to") == "WORKER":
                prior += 1
    f.append(_factor("prior_corroborated_discrepancies", prior, C["prior_corroborated_discrepancies"], W["prior_corroborated_discrepancies"], tw,
                     f"{prior} in {cfg.lookback_days} days",
                     "Counts this worker's other discrepancies that are corroborated and still open, or were resolved as worker-attributable. "
                     "A flagged-but-uncorroborated discrepancy, or one resolved as process/facility, does not count."))
    # 4 adverse audit history
    done = db.scalars(select(Audit).where(Audit.worker_id == worker_id, Audit.status == AuditStatus.COMPLETED,
                                          Audit.completed_at >= since, Audit.load_id != load.id)).all() if worker_id else []
    adverse = sum(1 for a in done if (a.result_json or {}).get("overall") == "SUPPORTS_FACILITY")
    ratio = adverse / len(done) if done else 0.0
    f.append(_factor("adverse_audit_history", ratio, 1.0, W["adverse_audit_history"], tw, f"{adverse} of {len(done)} recent audits",
                     "Share of this worker's recent completed audits that supported the facility's record." if done else "No completed audits in the window."))
    # 5 repeat complaints (ward level)
    n_c = 0
    if route and route.ward_id:
        n_c = len(db.scalars(select(SanitationReport.id).where(SanitationReport.ward_id == route.ward_id,
                                                                SanitationReport.issue_type == IssueType.MISSED_COLLECTION,
                                                                SanitationReport.created_at >= since)).all())
    f.append(_factor("repeat_complaints", n_c, C["repeat_complaints"], W["repeat_complaints"], tw, f"{n_c} in {cfg.lookback_days} days",
                     "Missed-collection tickets in the route's ward. This is an area-level signal, not proof about one worker."))
    # 6 segregation pattern deviation
    share = _segregated_share(db, load.id)
    others = []
    if worker_id:
        for l2 in db.scalars(select(DigitalLoad).join(Route, Route.id == DigitalLoad.route_id)
                             .where(Route.worker_id == worker_id, DigitalLoad.id != load.id, DigitalLoad.status != LoadStatus.COLLECTING,
                                    DigitalLoad.generated_at >= since)).all():
            s2 = _segregated_share(db, l2.id)
            if s2 is not None:
                others.append(s2)
    if share is not None and len(others) >= 2:
        dev = abs(share - sum(others) / len(others))
        f.append(_factor("segregation_pattern_deviation", dev, C["segregation_pattern_deviation"], W["segregation_pattern_deviation"], tw,
                         f"{dev:.0%} from the worker's usual {sum(others) / len(others):.0%}", "Difference between this load's segregated share and the worker's own average."))
    else:
        f.append(_factor("segregation_pattern_deviation", 0.0, C["segregation_pattern_deviation"], W["segregation_pattern_deviation"], tw,
                         f"insufficient history ({len(others)} other loads)", "Needs at least 2 other loads from this worker to compare; scored 0."))

    score = round(sum(x["contribution"] for x in f), 4)
    return {"load_id": load.id, "worker_id": worker_id, "score": score, "factors": f,
            "top": [x["label"] for x in sorted(f, key=lambda x: -x["contribution"]) if x["contribution"] > 0][:3]}


def risk_reason(r: dict, threshold: float) -> str:
    parts = [f"{x['label']} {x['raw_text']} (+{x['contribution']:.2f})" for x in sorted(r["factors"], key=lambda x: -x["contribution"]) if x["contribution"] > 0][:3]
    return f"Risk score {r['score']:.2f} >= threshold {threshold:.2f}. Main factors: " + ("; ".join(parts) or "none") + "."


# ---------------------------------------------------------------- random
def random_sample_size(n: int, pct: float) -> int:
    if n == 0 or pct <= 0:
        return 0
    return min(n, max(1, math.floor(pct / 100.0 * n + 0.5)))     # round half up; at least one when pct > 0


def draw_random(load_ids: list[str], pct: float, seed: int) -> tuple[list[str], int]:
    k = random_sample_size(len(load_ids), pct)
    return random.Random(seed).sample(sorted(load_ids), k), k


def new_seed() -> int:
    return secrets.randbits(62)


def random_reason(k: int, n: int, pct: float, seed: int) -> str:
    return f"Random sample: {k} of {n} eligible loads ({pct:g}%), uniform draw with seed {seed}. Not risk-informed."


def check_method_params(pct: Optional[float], threshold: Optional[float]) -> None:
    if pct is not None and not (0 <= pct <= 100):
        raise ServiceError(422, "BAD_PERCENT", "random_sample_pct must be between 0 and 100.")
    if threshold is not None and not (0 <= threshold <= 1):
        raise ServiceError(422, "BAD_THRESHOLD", "risk_threshold must be between 0 and 1.")
