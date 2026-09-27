"""Phase 2 - audit selection engine (RANDOM, RISK_BASED, MANUAL) and the Audit Center API."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import audit_selection as sel
from app import settings
from app.db import SessionLocal
from app.models import Audit, AuditMethod, AuditSelectionRun, AuditStatus, DiscrepancyEvent, DigitalLoad, EventLog, utcnow
from tests.conftest import login

# seeded: DL-1001 VERIFIED (12 kg / 2.5% off), DL-1002 DISPUTED (25% short), DL-1003 DISPUTED (stream rejection)


@pytest.fixture()
def admin(client): return login(client, "admin1")
@pytest.fixture()
def fac1(client): return login(client, "facility1")
@pytest.fixture()
def fac2(client): return login(client, "facility2")
@pytest.fixture()
def worker(client): return login(client, "worker2")


def run(client, user=None, **body):
    headers = login(client, "facility2")
    r = client.post("/audit-center/selection-runs", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def chain_events(client, admin, load, t):
    return [e for e in client.get(f"/loads/{load}/events", headers=admin).json() if e["event_type"] == t]


# ================================================================ configuration
def test_default_config_is_transparent_and_valid(client, admin):
    c = client.get("/audit-center/config", headers=admin).json()
    assert c["random_sample_pct"] == 20.0 and c["risk_threshold"] == 0.30 and c["cooldown_days"] == 7
    assert set(c["weights"]) == set(sel.FACTOR_LABELS) and abs(sum(c["weights"].values()) - 1.0) < 1e-9


def test_config_file_and_overrides_are_validated(tmp_path, monkeypatch):
    f = tmp_path / "audit.json"
    f.write_text(json.dumps({"random_sample_pct": 35, "weights": {"quantity_variance": 0.9}, "caps": {"repeat_complaints": 10}}))
    monkeypatch.setenv("AUDIT_CONFIG_PATH", str(f))
    cfg = settings.load_audit_config({"risk_threshold": 0.5})
    assert cfg.random_sample_pct == 35 and cfg.weights["quantity_variance"] == 0.9 and cfg.caps["repeat_complaints"] == 10 and cfg.risk_threshold == 0.5
    for bad in [{"random_sample_pct": 101}, {"weights": {"nonsense": 1}}, {"weights": {k: 0 for k in settings.DEFAULT_WEIGHTS}}, {"caps": {"repeat_complaints": 0}}, {"bogus_key": 1}]:
        f.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            settings.load_audit_config()


def test_selection_run_rejects_bad_parameters(client, fac2):
    for body in [{"method": "RANDOM", "random_sample_pct": 150}, {"method": "RISK_BASED", "risk_threshold": 2}, {"method": "MANUAL"}, {"method": "RANDOM", "random_sample_pct": "abc"}]:
        assert client.post("/audit-center/selection-runs", json=body, headers=fac2).status_code == 422, body


# ================================================================ eligibility
def test_eligible_loads_are_received_and_unaudited(client, admin):
    with SessionLocal() as db:
        cfg = settings.load_audit_config()
        assert [l.id for l in sel.eligible_loads(db, cfg, utcnow())] == ["DL-1001", "DL-1002", "DL-1003"]
    out = run(client, admin, method="RANDOM", random_sample_pct=100, seed=1)
    assert out["eligible_count"] == 3 and out["selected_count"] == 3
    with SessionLocal() as db:   # now every load has an open audit -> none eligible
        assert sel.eligible_loads(db, settings.load_audit_config(), utcnow()) == []
    assert run(client, admin, method="RANDOM", random_sample_pct=100, seed=1)["eligible_count"] == 0


def test_only_received_loads_are_eligible(client, fac2):
    w = login(client, "worker1")
    for h in client.get("/worker/route", headers=w).json()["households"]:
        client.post("/worker/collections", json={"household_id": h["id"], "status": "SEGREGATED"}, headers=w)       # a COLLECTING load
    with SessionLocal() as db:
        ids = [l.id for l in sel.eligible_loads(db, settings.load_audit_config(), utcnow())]
    assert ids == ["DL-1001", "DL-1002", "DL-1003"]
    lid = client.get("/worker/route", headers=w).json()["active_load"]["id"]
    r = client.post("/audit-center/audits", json={"load_id": lid, "reason": "trying to audit a load that is not received"}, headers=fac2)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "LOAD_NOT_AUDITABLE"


# ================================================================ RANDOM
@pytest.mark.parametrize("n,pct,k", [(0, 20, 0), (3, 0, 0), (3, 100, 3), (3, 34, 1), (3, 20, 1), (10, 25, 3), (10, 24, 2), (200, 5, 10), (3, 50, 2)])
def test_random_sample_size(n, pct, k):
    assert sel.random_sample_size(n, pct) == k


def test_draw_is_reproducible_from_the_seed_and_independent_of_input_order():
    ids = [f"DL-{i}" for i in range(1001, 1041)]
    a, _ = sel.draw_random(ids, 25, 12345)
    b, _ = sel.draw_random(list(reversed(ids)), 25, 12345)
    c, _ = sel.draw_random(ids, 25, 54321)
    assert a == b and len(a) == 10 and len(set(a)) == 10 and a != c and set(a) <= set(ids)


def test_random_run_is_deterministic_persisted_and_explained(client, admin):
    preview1 = run(client, admin, method="RANDOM", random_sample_pct=34, seed=7, dry_run=True)
    preview2 = run(client, admin, method="RANDOM", random_sample_pct=34, seed=7, dry_run=True)
    assert [c["load_id"] for c in preview1["candidates"] if c["selected"]] == [c["load_id"] for c in preview2["candidates"] if c["selected"]]
    assert preview1["dry_run"] is True and preview1["run_id"] is None and preview1["audits"] == []
    with SessionLocal() as db:
        assert db.query(Audit).count() == 0 and db.query(AuditSelectionRun).count() == 0, "a dry run persists nothing"
    out = run(client, admin, method="RANDOM", random_sample_pct=34, seed=7)
    assert out["selected_count"] == 1 and out["seed"] == 7 and out["run_id"] and out["config"]["random_sample_pct"] == 34
    picked = [c["load_id"] for c in out["candidates"] if c["selected"]]
    a = out["audits"][0]
    assert [a["load_id"]] == picked == [c["load_id"] for c in preview1["candidates"] if c["selected"]]
    assert a["method"] == "RANDOM" and a["risk_score"] is None and a["status"] == "PENDING" and a["auditor"] is None
    assert "Random sample: 1 of 3 eligible loads (34%)" in a["selection_reason"] and "seed 7" in a["selection_reason"] and "Not risk-informed" in a["selection_reason"]
    assert a["selected_by"].startswith("Meera Joshi") and a["selected_at"]
    with SessionLocal() as db:
        run_row = db.get(AuditSelectionRun, out["run_id"])
        assert run_row.method == AuditMethod.RANDOM and run_row.seed == 7 and run_row.eligible_count == 3 and run_row.selected_count == 1
        assert run_row.config_json["random_sample_pct"] == 34 and len(run_row.details_json["candidates"]) == 3
    ev = chain_events(client, admin, a["load_id"], "AUDIT_SELECTED")
    assert len(ev) == 1 and ev[0]["payload"]["method"] == "RANDOM" and ev[0]["payload"]["audit_id"] == a["id"] and "seed 7" in ev[0]["payload"]["selection_reason"]
    assert client.get(f"/loads/{a['load_id']}/verify-integrity", headers=admin).json()["valid"] is True


def test_random_run_without_a_seed_stores_the_generated_seed_so_it_can_be_replayed(client, admin, fac2):
    out = run(client, admin, method="RANDOM", random_sample_pct=34)
    assert isinstance(out["seed"], int) and out["seed"] > 0
    chosen = out["audits"][0]
    # restore the original eligible set (cancel the audit), then replay the stored seed: the draw must be identical
    assert client.post(f"/audit-center/audits/{chosen['id']}/cancel", json={"reason": "cancelled to replay the stored seed"}, headers=fac2).status_code == 200
    replay = run(client, admin, method="RANDOM", random_sample_pct=34, seed=out["seed"], dry_run=True)
    assert replay["eligible_count"] == 3
    assert [c["load_id"] for c in replay["candidates"] if c["selected"]] == [chosen["load_id"]]
    assert client.get("/audit-center/selection-runs", headers=admin).json()[0]["seed"] == out["seed"]


def test_cooldown_applies_to_automatic_selection_but_not_to_manual(client, admin, fac2):
    aid = run(client, admin, method="RANDOM", random_sample_pct=100, seed=3)["audits"][0]["id"]
    for a in client.get("/audit-center/audits", headers=admin).json():          # complete the audit on DL-1002 to trigger the cooldown
        if a["load_id"] == "DL-1002":
            aid = a["id"]
    client.post(f"/audit-center/audits/{aid}/start", headers=fac2)
    import io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (8, 8), (1, 2, 3)).save(b, "PNG")
    client.post(f"/audit-center/audits/{aid}/evidence", files={"file": ("a.png", b.getvalue(), "image/png")}, data={"description": "audit photo"}, headers=fac2)
    with SessionLocal() as db:
        db.execute(text("update audits set status='CANCELLED' where load_id <> 'DL-1002'"))
        db.commit()
    assert client.post(f"/audit-center/audits/{aid}/complete", json={"quantity": 385, "condition": "ACCEPTABLE", "observations": "checked"}, headers=fac2).status_code == 200
    with SessionLocal() as db:
        ids = [l.id for l in sel.eligible_loads(db, settings.load_audit_config(), utcnow())]
    assert ids == ["DL-1001", "DL-1003"], "DL-1002 was audited moments ago"
    manual = client.post("/audit-center/audits", json={"load_id": "DL-1002", "reason": "Manual re-audit is exempt from the cooldown"}, headers=fac2)
    assert manual.status_code == 200 and manual.json()["method"] == "MANUAL"


# ================================================================ RISK_BASED
def test_risk_scores_rank_the_seeded_loads_and_select_the_shortfall(client, admin):
    out = run(client, admin, method="RISK_BASED", dry_run=True)
    scores = {c["load_id"]: c["risk_score"] for c in out["candidates"]}
    assert scores["DL-1002"] == pytest.approx(0.3333, abs=1e-3) and scores["DL-1003"] < 0.30 and scores["DL-1001"] < 0.05
    assert [c["load_id"] for c in out["candidates"] if c["selected"]] == ["DL-1002"]
    assert [c["load_id"] for c in out["candidates"]] == ["DL-1002", "DL-1003", "DL-1001"], "highest score first"


def test_risk_score_is_fully_explained(client, admin):
    out = run(client, admin, method="RISK_BASED")
    a = out["audits"][0]
    assert a["load_id"] == "DL-1002" and a["method"] == "RISK_BASED" and a["risk_score"] == pytest.approx(0.3333, abs=1e-3) and a["run_id"] == out["run_id"]
    detail = client.get(f"/audit-center/audits/{a['id']}", headers=admin).json()
    f = detail["risk_factors"]
    assert [x["key"] for x in f] == list(sel.FACTOR_LABELS)
    assert sum(x["contribution"] for x in f) == pytest.approx(a["risk_score"], abs=1e-3)
    assert sum(x["weight_share"] for x in f) == pytest.approx(1.0, abs=1e-3)
    q = next(x for x in f if x["key"] == "quantity_variance")
    assert q["raw"] == pytest.approx(0.25, abs=1e-3) and q["normalised"] == pytest.approx(0.8333, abs=1e-3) and q["weight"] == 0.4
    assert q["contribution"] == pytest.approx(0.3333, abs=1e-3) and "390 kg received vs 520 kg declared" in q["raw_text"]
    assert all(x["explanation"] and x["label"] for x in f)
    assert a["selection_reason"].startswith("Risk score 0.33 >= threshold 0.30") and "Quantity variance (received vs declared)" in a["selection_reason"]
    assert detail["run"]["config"]["weights"]["quantity_variance"] == 0.4 and detail["run"]["method"] == "RISK_BASED"
    # reproducible: recomputing from the stored configuration gives the same number
    with SessionLocal() as db:
        cfg = settings.AuditConfig(**{k: v for k, v in detail["run"]["config"].items()})
        assert sel.compute_risk(db, db.get(DigitalLoad, "DL-1002"), cfg)["score"] == pytest.approx(a["risk_score"], abs=1e-3)


def test_threshold_and_max_selected_are_configurable_per_run(client, admin):
    low = run(client, admin, method="RISK_BASED", risk_threshold=0.2, dry_run=True)
    assert [c["load_id"] for c in low["candidates"] if c["selected"]] == ["DL-1002", "DL-1003"]
    capped = run(client, admin, method="RISK_BASED", risk_threshold=0.0, risk_max_selected=1, dry_run=True)
    assert [c["load_id"] for c in capped["candidates"] if c["selected"]] == ["DL-1002"]
    none = run(client, admin, method="RISK_BASED", risk_threshold=0.9, dry_run=True)
    assert none["selected_count"] == 0 and len(none["candidates"]) == 3, "non-selected loads keep their explanations"


def test_weights_are_configurable(client, admin, tmp_path, monkeypatch):
    f = tmp_path / "w.json"
    f.write_text(json.dumps({"weights": {"quantity_variance": 0.0, "stream_mismatch": 1.0, "prior_corroborated_discrepancies": 0, "adverse_audit_history": 0,
                                         "repeat_complaints": 0, "segregation_pattern_deviation": 0}}))
    monkeypatch.setenv("AUDIT_CONFIG_PATH", str(f))
    out = run(client, admin, method="RISK_BASED", dry_run=True)
    assert [c["load_id"] for c in out["candidates"] if c["selected"]] == ["DL-1003"], "only the stream mismatch matters under these weights"


def test_prior_corroborated_discrepancies_count_only_worker_attributable_history(client, admin):
    cfg = settings.load_audit_config()

    def factor():
        with SessionLocal() as db:
            # DL-1003 belongs to worker3; give worker3's *other* history by pointing at DL-1002's worker instead: score DL-1002's sibling is n/a,
            # so we score DL-1002 against worker2's discrepancies on OTHER loads -> create one on a new load below.
            return next(x for x in sel.compute_risk(db, db.get(DigitalLoad, NEW), cfg)["factors"] if x["key"] == "prior_corroborated_discrepancies")

    w = login(client, "worker2")
    for h in client.get("/worker/route", headers=w).json()["households"]:
        client.post("/worker/collections", json={"household_id": h["id"], "status": "SEGREGATED"}, headers=w)
    NEW = client.get("/worker/route", headers=w).json()["active_load"]["id"]
    client.post(f"/loads/{NEW}/declare", json={"declared_quantity_kg": 600}, headers=w)
    client.post(f"/loads/{NEW}/receiving", json={"quantity": 590, "condition": "ACCEPTABLE"}, headers=login(client, "facility1"))
    assert factor()["raw"] == 0                                                        # DL-1002's discrepancy is only FLAGGED
    with SessionLocal() as db:
        d = db.get(DiscrepancyEvent, 1)
        d.status = "CORROBORATED"
        db.commit()
    assert factor()["raw"] == 1                                                        # corroborated and still open -> counts
    with SessionLocal() as db:
        d = db.get(DiscrepancyEvent, 1)
        d.status = "RESOLVED"
        d.details_json = {**d.details_json, "resolution": {"attributed_to": "PROCESS"}}
        db.commit()
    assert factor()["raw"] == 0                                                        # resolved as a process problem -> does NOT count against the worker
    with SessionLocal() as db:
        d = db.get(DiscrepancyEvent, 1)
        d.details_json = {**d.details_json, "resolution": {"attributed_to": "WORKER"}}
        db.commit()
    assert factor()["raw"] == 1                                                        # resolved as worker-attributable -> counts


def test_repeat_complaints_use_the_phase1_sanitation_tickets(client, admin):
    c = login(client, "citizen1")
    for i in range(2):   # Demo Ward B = worker2's route ward
        r = client.post("/citizen/sanitation-reports", json={"description": "collection skipped again", "issue_type": "MISSED_COLLECTION",
                                                             "latitude": 19.070 + i * 0.001, "longitude": 72.902, "location_source": "CITIZEN_PLACED"}, headers=c)
        assert r.json()["ward"]["code"] == "DEMO-B"
    client.post("/citizen/sanitation-reports", json={"description": "bin overflowing here", "issue_type": "OVERFLOWING_BIN", "latitude": 19.07, "longitude": 72.902}, headers=c)
    out = run(client, admin, method="RISK_BASED", dry_run=True)
    f = next(x for x in next(c for c in out["candidates"] if c["load_id"] == "DL-1002")["factors"] if x["key"] == "repeat_complaints")
    assert f["raw"] == 2 and f["normalised"] == pytest.approx(0.6667, abs=1e-3) and "area-level" in f["explanation"]


def test_adverse_audit_history_and_segregation_history_factors(client, admin):
    with SessionLocal() as db:
        cfg = settings.load_audit_config()
        seg = next(x for x in sel.compute_risk(db, db.get(DigitalLoad, "DL-1002"), cfg)["factors"] if x["key"] == "segregation_pattern_deviation")
        assert seg["raw"] == 0 and "insufficient history" in seg["raw_text"]
        # two completed audits of worker2's OTHER loads: one supported the facility, one the worker
        for i, overall in enumerate(["SUPPORTS_FACILITY", "SUPPORTS_WORKER"]):
            db.execute(text("insert into digital_loads (id, route_id, generated_at, status) values (:i, 2, now(), 'SETTLED')"), {"i": f"DL-90{i}"})
            db.execute(text("insert into audits (load_id, worker_id, method, selection_reason, selected_at, status, completed_at, result_json, risk_factors) "
                            "values (:i, 2, 'MANUAL', 'seeded history for the test', now(), 'COMPLETED', now(), cast(:r as json), '{}')"),
                       {"i": f"DL-90{i}", "r": json.dumps({"overall": overall})})
        db.commit()
        f = next(x for x in sel.compute_risk(db, db.get(DigitalLoad, "DL-1002"), cfg)["factors"] if x["key"] == "adverse_audit_history")
        assert f["raw"] == 0.5 and f["raw_text"] == "1 of 2 recent audits" and f["contribution"] == pytest.approx(0.05, abs=1e-3)


# ================================================================ MANUAL
def test_manual_audit_needs_a_reason_and_records_who_and_why(client, admin, fac1, fac2, worker):
    assert client.post("/audit-center/audits", json={"load_id": "DL-1002", "reason": "too short"}, headers=fac2).status_code == 422
    assert client.post("/audit-center/audits", json={"load_id": "DL-1002", "reason": "   " * 10}, headers=fac2).status_code in (422,)
    for who in (admin, worker):
        assert client.post("/audit-center/audits", json={"load_id": "DL-1002", "reason": "admin or worker cannot select audits"}, headers=who).status_code == 403
    assert client.post("/audit-center/audits", json={"load_id": "DL-4040", "reason": "load that does not exist at all"}, headers=fac2).status_code == 404
    r = client.post("/audit-center/audits", json={"load_id": "dl-1002", "reason": "Complaint received about this load from the ward officer"}, headers=fac2)
    assert r.status_code == 200
    a = r.json()
    assert a["method"] == "MANUAL" and a["selection_reason"].startswith("Complaint received") and a["selected_by"].startswith("Meera Joshi") and a["run_id"] is None
    assert a["risk_score"] == pytest.approx(0.3333, abs=1e-3), "informational score is still recorded for a manual audit"
    ev = chain_events(client, admin, "DL-1002", "AUDIT_SELECTED")[0]["payload"]
    assert ev["method"] == "MANUAL" and ev["selection_reason_sha256"] and "selection_reason" not in ev, "free-text manual reasons go into the chain as a hash only"
    dup = client.post("/audit-center/audits", json={"load_id": "DL-1002", "reason": "a second open audit on the same load"}, headers=fac2)
    assert dup.status_code == 409 and dup.json()["detail"]["error"] == "AUDIT_ALREADY_OPEN"


def test_no_audit_can_exist_without_a_recorded_reason_and_only_one_may_be_open(client, admin):
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            db.execute(text("insert into audits (load_id, method, selection_reason, selected_at, status, risk_factors) values ('DL-1001','MANUAL','short',now(),'PENDING','{}')"))
            db.commit()
    with SessionLocal() as db:
        db.execute(text("insert into audits (load_id, method, selection_reason, selected_at, status, risk_factors) values ('DL-1001','MANUAL','a proper recorded reason',now(),'PENDING','{}')"))
        db.commit()
        with pytest.raises(IntegrityError):
            db.execute(text("insert into audits (load_id, method, selection_reason, selected_at, status, risk_factors) values ('DL-1001','MANUAL','another proper recorded reason',now(),'PENDING','{}')"))
            db.commit()


def test_every_selected_audit_has_a_reason_and_a_chain_event(client, admin):
    run(client, admin, method="RANDOM", random_sample_pct=100, seed=11)
    audits = client.get("/audit-center/audits", headers=admin).json()
    assert len(audits) == 3 and all(len(a["selection_reason"]) >= 10 and a["method"] == "RANDOM" for a in audits)
    for a in audits:
        assert len(chain_events(client, admin, a["load_id"], "AUDIT_SELECTED")) == 1
        assert client.get(f"/loads/{a['load_id']}/verify-integrity", headers=admin).json()["valid"] is True


# ================================================================ cancel + listing + RBAC
def test_cancel_needs_a_reason_and_frees_the_load(client, admin, fac2):
    aid = client.post("/audit-center/audits", json={"load_id": "DL-1002", "reason": "audit that will later be cancelled"}, headers=fac2).json()["id"]
    assert client.post(f"/audit-center/audits/{aid}/cancel", json={"reason": "short"}, headers=fac2).status_code == 422
    assert client.post(f"/audit-center/audits/{aid}/cancel", json={"reason": "Selected in error, load already re-weighed"}, headers=admin).status_code == 403
    r = client.post(f"/audit-center/audits/{aid}/cancel", json={"reason": "Selected in error, load already re-weighed"}, headers=fac2)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED" and r.json()["auditor"] is None
    assert client.post(f"/audit-center/audits/{aid}/start", headers=fac2).status_code == 409
    assert client.post(f"/audit-center/audits/{aid}/cancel", json={"reason": "cancelling something twice over"}, headers=fac2).status_code == 409
    assert len(chain_events(client, admin, "DL-1002", "AUDIT_CANCELLED")) == 1
    assert client.post("/audit-center/audits", json={"load_id": "DL-1002", "reason": "a fresh audit after the cancellation"}, headers=fac2).status_code == 200


def test_listing_filters_summary_and_recusal(client, admin, fac1, fac2, worker):
    run(client, fac2, method="RANDOM", random_sample_pct=100, seed=5)
    assert len(client.get("/audit-center/audits", headers=admin).json()) == 3
    assert client.get("/audit-center/audits", params={"method": "RANDOM"}, headers=admin).json().__len__() == 3
    assert client.get("/audit-center/audits", params={"method": "RISK_BASED"}, headers=admin).json() == []
    assert len(client.get("/audit-center/audits", params={"status": "PENDING"}, headers=admin).json()) == 3
    assert client.get("/audit-center/audits", params={"status": "bogus"}, headers=admin).status_code == 422
    assert len(client.get("/audit-center/audits", headers=fac2).json()) == 3, "facility 2 is independent of every seeded load"
    assert client.get("/audit-center/audits", headers=fac1).json() == [], "facility 1 recorded every seeded receiving record"
    s = client.get("/audit-center/summary", headers=admin).json()
    assert s == {"total": 3, "by_status": {"PENDING": 3}, "by_method": {"RANDOM": 3}}
    assert client.get("/audit-center/summary", headers=fac1).json()["total"] == 0
    assert client.get("/audit-center/audits").status_code == 401
    assert client.post("/audit-center/selection-runs", json={"method": "RANDOM"}, headers=admin).status_code == 403
    assert client.post("/audit-center/selection-runs", json={"method": "RANDOM"}, headers=worker).status_code == 403
    assert len(client.get("/audit-center/selection-runs", headers=admin).json()) == 1


def test_audit_evidence_status_and_detail_for_the_auditor(client, admin, fac2):
    import io
    from PIL import Image
    aid = client.post("/audit-center/audits", json={"load_id": "DL-1002", "reason": "Audit for the evidence status test"}, headers=fac2).json()["id"]
    d = client.get(f"/audit-center/audits/{aid}", headers=fac2).json()
    assert d["evidence_status"] == {"files": 0, "independent_files": 0, "has_result": False} and d["can_conduct"] is True
    assert d["declaration"]["quantity"] == 520 and d["receiving"]["quantity"] == 390 and d["worker"] == "Sunita Jadhav" and d["facility"] == "Eastern Processing Facility"
    assert d["discrepancies"] == [{"id": 1, "type": "QUANTITY", "status": "FLAGGED"}]
    client.post(f"/audit-center/audits/{aid}/start", headers=fac2)
    b = io.BytesIO(); Image.new("RGB", (8, 8), (9, 8, 7)).save(b, "PNG")
    assert client.post(f"/audit-center/audits/{aid}/evidence", files={"file": ("a.png", b.getvalue(), "image/png")}, data={"description": "scale display"}, headers=fac2).status_code == 200
    d = client.get(f"/audit-center/audits/{aid}", headers=fac2).json()
    assert d["evidence_status"]["files"] == 1 and d["evidence_status"]["independent_files"] == 1 and d["auditor"]["role"] == "FACILITY"
    case = client.get(f"/audit-center/audits/{aid}/evidence", headers=fac2).json()
    assert len(case) == 1 and case[0]["audit_id"] == aid
