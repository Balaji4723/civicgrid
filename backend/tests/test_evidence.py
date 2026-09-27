"""Phase 2 - real evidence capture."""
import hashlib
import io
import os
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import evidence_storage, seed
from app.db import SessionLocal
from app.evidence_storage import LocalEvidenceStorage
from app.hashchain import verify_chain
from app.models import Evidence, EventLog, Role, User
from app.auth import hash_password
from tests.conftest import login

D = 1                      # DL-1002 / discrepancy #1, seeded FLAGGED (worker2's load, received at facility 1)
UP = f"/discrepancy/{D}/evidence"


# ----------------------------------------------------------------------------- sample bytes
def _img(fmt, color=(200, 30, 30), size=(8, 8)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, fmt)
    return b.getvalue()


def png(color=(200, 30, 30), size=(8, 8)): return _img("PNG", color, size)
def jpeg(color=(20, 120, 200), size=(8, 8)): return _img("JPEG", color, size)
def webp(color=(20, 200, 90)): return _img("WEBP", color)


MP4 = bytes.fromhex("00000018667479706973 6f6d0000020069736f6d6d703431".replace(" ", "")) + b"\x00" * 64
WEBM = bytes([0x1A, 0x45, 0xDF, 0xA3, 0x9F, 0x42, 0x86, 0x81, 0x01, 0x42, 0xF7, 0x81, 0x01, 0x42, 0x82, 0x84]) + b"webm" + b"\x00" * 64


def upload(client, headers, data, filename="photo.png", ctype="auto", path=UP, **form):
    ct = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "mp4": "video/mp4", "webm": "video/webm"}.get(
        filename.rsplit(".", 1)[-1].lower(), "application/octet-stream") if ctype == "auto" else ctype
    files = {"file": (filename, data, ct)} if ct else {"file": (filename, data)}
    return client.post(path, files=files, data={"description": "load photo at the receiving bay", **form}, headers=headers)


@pytest.fixture()
def worker(client): return login(client, "worker2")          # responsible worker for DL-1002
@pytest.fixture()
def other_worker(client): return login(client, "worker1")
@pytest.fixture()
def fac1(client): return login(client, "facility1")          # recorded the receiving record, facility 1
@pytest.fixture()
def fac2(client): return login(client, "facility2")          # different facility
@pytest.fixture()
def admin(client): return login(client, "admin1")
@pytest.fixture()
def citizen(client): return login(client, "citizen1")


def stored_files():
    root = Path(os.environ["EVIDENCE_STORAGE_DIR"])
    return [p for p in root.rglob("*") if p.is_file()]


# ============================================================================ valid uploads
@pytest.mark.parametrize("name,data", [("photo.png", png()), ("photo.jpg", jpeg()), ("photo.jpeg", jpeg()), ("photo.webp", webp())])
def test_valid_image_upload(client, worker, name, data):
    r = upload(client, worker, data, name)
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["id"].startswith("ev_") and e["kind"] == "FILE_EVIDENCE" and e["side"] == "WORKER"
    assert e["media_type"] in ("image/png", "image/jpeg", "image/webp") and e["size_bytes"] == len(data)
    assert e["sha256"] == hashlib.sha256(data).hexdigest()
    assert e["uploader"]["role"] == "WORKER" and e["uploader"]["actor"].startswith("worker:") and e["created_at"]
    assert e["load_id"] == "DL-1002" and e["discrepancy_id"] == D
    assert len(stored_files()) == 1


@pytest.mark.parametrize("name,data,mt", [("walk.mp4", MP4, "video/mp4"), ("walk.webm", WEBM, "video/webm")])
def test_valid_video_upload(client, worker, name, data, mt):
    r = upload(client, worker, data, name, category="VIDEO_WALKTHROUGH")
    assert r.status_code == 200, r.text
    assert r.json()["media_type"] == mt and r.json()["sha256"] == hashlib.sha256(data).hexdigest() and r.json()["category"] == "VIDEO_WALKTHROUGH"


def test_response_never_exposes_paths_or_storage_keys(client, worker, admin):
    e = upload(client, worker, png(), "a.png").json()
    blob = str(e) + str(client.get(f"/evidence/{e['id']}", headers=admin).json()) + str(client.get(f"/discrepancy/{D}", headers=admin).json())
    root = os.environ["EVIDENCE_STORAGE_DIR"]
    with SessionLocal() as db:
        key = db.query(Evidence.storage_key).filter(Evidence.public_id == e["id"]).scalar()   # (the seeded DL-1003 NOTE row has no file)
    assert key and key not in blob and root not in blob and "storage_key" not in blob and "/tmp" not in blob and "evidence/" not in blob.replace("/evidence/ev_", "")


# ============================================================================ content validation
def test_executable_renamed_to_png_is_refused_by_content(client, worker):
    r = upload(client, worker, b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 200, "photo.png")
    assert r.status_code == 415 and r.json()["detail"]["error"] == "UNSUPPORTED_CONTENT" and "Windows executable" in r.json()["detail"]["message"]
    assert stored_files() == []


@pytest.mark.parametrize("data,expect", [
    (b"\x7fELF\x02\x01\x01" + b"\x00" * 100, "Linux executable"), (b"#!/bin/sh\nrm -rf /\n", "script"),
    (b"PK\x03\x04" + b"\x00" * 50, "archive"), (b"%PDF-1.7\n", "PDF"), (b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>", "SVG"),
    (b"<html><script>alert(1)</script></html>", "HTML"), (b"<?php system($_GET['c']); ?>", "PHP"),
    (b"just some plain text pretending to be a photo", "unsupported")])
def test_dangerous_or_unsupported_content_refused(client, worker, data, expect):
    r = upload(client, worker, data, "photo.jpg")
    assert r.status_code == 415, r.text
    assert expect.lower() in r.json()["detail"]["message"].lower()
    assert stored_files() == []


def test_extension_content_mismatch(client, worker):
    r = upload(client, worker, png(), "photo.jpg", ctype="image/jpeg")       # PNG bytes, .jpg name
    assert r.status_code == 415 and r.json()["detail"]["error"] == "EXTENSION_CONTENT_MISMATCH"
    r = upload(client, worker, jpeg(), "photo.mp4", ctype="video/mp4")
    assert r.status_code == 415 and r.json()["detail"]["error"] == "EXTENSION_CONTENT_MISMATCH"
    assert upload(client, worker, png(), "no_extension", ctype="image/png").status_code == 415
    assert stored_files() == []


def test_declared_content_type_must_match_content(client, worker):
    r = upload(client, worker, png(), "photo.png", ctype="image/jpeg")
    assert r.status_code == 415 and r.json()["detail"]["error"] == "CONTENT_TYPE_MISMATCH"
    assert upload(client, worker, png(), "photo.png", ctype="application/octet-stream").status_code == 200   # unspecified is fine


def test_corrupt_truncated_and_empty_files(client, worker):
    good = png(size=(64, 64))
    r = upload(client, worker, good[: len(good) // 2], "photo.png")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "CORRUPT_IMAGE"
    r = upload(client, worker, b"\xff\xd8\xff\xe0" + b"\x00" * 30, "photo.jpg")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "CORRUPT_IMAGE"
    r = upload(client, worker, b"", "photo.png")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "EMPTY_FILE"
    assert stored_files() == []


def test_image_pixel_bomb_refused(client, worker, monkeypatch):
    monkeypatch.setenv("EVIDENCE_MAX_IMAGE_PIXELS", "1000000")
    big = _img("PNG", (0, 0, 0), (2000, 2000))                    # 4 M pixels, compresses to a few KB
    assert len(big) < 200_000
    r = upload(client, worker, big, "big.png")
    assert r.status_code == 413 and r.json()["detail"]["error"] == "IMAGE_TOO_LARGE" and stored_files() == []


def test_double_extension_and_dangerous_names_refused(client, worker):
    for name in ["photo.php.jpg", "evil.exe.png", "run.sh.jpg", "page.html.png", "x.svg.png"]:
        r = upload(client, worker, png(), name)
        assert r.status_code == 415 and r.json()["detail"]["error"] == "UNSAFE_FILENAME", name
    assert stored_files() == []


# ============================================================================ size limits
def test_oversized_image_refused_and_limit_is_configurable(client, worker, monkeypatch):
    data = png(size=(120, 120))
    monkeypatch.setenv("EVIDENCE_MAX_IMAGE_BYTES", str(len(data) - 1))
    r = upload(client, worker, data, "photo.png")
    assert r.status_code == 413 and r.json()["detail"]["error"] == "FILE_TOO_LARGE" and stored_files() == []
    monkeypatch.setenv("EVIDENCE_MAX_IMAGE_BYTES", str(len(data)))
    assert upload(client, worker, data, "photo.png").status_code == 200


def test_video_has_its_own_larger_limit(client, worker, monkeypatch):
    monkeypatch.setenv("EVIDENCE_MAX_IMAGE_BYTES", "50")
    monkeypatch.setenv("EVIDENCE_MAX_VIDEO_BYTES", "100000")
    assert upload(client, worker, MP4, "walk.mp4").status_code == 200
    monkeypatch.setenv("EVIDENCE_MAX_VIDEO_BYTES", "40")
    assert upload(client, worker, MP4, "walk2.mp4").status_code == 413


def test_declared_content_length_over_the_cap_is_refused_early(client, worker, monkeypatch):
    monkeypatch.setenv("EVIDENCE_MAX_VIDEO_BYTES", "1000")
    r = client.post(UP, content=b"x" * 10, headers={**worker, "Content-Length": str(5 * 1024 * 1024), "Content-Type": "multipart/form-data; boundary=x"})
    assert r.status_code in (413, 400, 422)      # refused before/at parsing - never stored
    assert stored_files() == []


# ============================================================================ malicious filenames
def test_path_traversal_filenames_are_neutralised(client, worker):
    root = Path(os.environ["EVIDENCE_STORAGE_DIR"]).resolve()
    outside_before = set(root.parent.glob("*"))
    seen = set()
    for i, name in enumerate(["../../etc/passwd.png", "..\\..\\windows\\system32\\x.png", "/absolute/path/shot.png", "a\x00b.png", "ünï cödé 名前.png", ("a" * 400) + ".png"]):
        r = upload(client, worker, png(color=(i * 30, 10, 10)), name)
        if r.status_code == 200:
            fn = r.json()["filename"]
            assert "/" not in fn and "\\" not in fn and "\x00" not in fn and ".." not in fn and len(fn) <= 120 and fn.endswith(".png")
            seen.add(fn)
        else:
            assert r.status_code in (415, 422)
    assert {"passwd.png", "x.png", "shot.png"} <= seen
    assert all(root in p.resolve().parents for p in stored_files())
    assert set(root.parent.glob("*")) == outside_before, "nothing may be written outside the storage root"
    with SessionLocal() as db:
        assert all(k.startswith("evidence/") and len(k.split("/")[-1]) == 32 for (k,) in db.query(Evidence.storage_key).filter(Evidence.storage_key.is_not(None)).all()), "server-generated keys only"


# ============================================================================ hashing + integrity
def test_sha256_is_of_the_real_bytes_and_is_in_the_immutable_event(client, worker, admin):
    data = jpeg(size=(40, 30))
    e = upload(client, worker, data, "load.jpg").json()
    assert e["sha256"] == hashlib.sha256(data).hexdigest()
    events = client.get("/loads/DL-1002/events", headers=admin).json()
    ev = next(x for x in events if x["event_type"] == "EVIDENCE_ADDED")
    p = ev["payload"]
    assert p["sha256"] == e["sha256"] and p["evidence_id"] == e["id"] and p["uploader"] == e["uploader"]["actor"] and p["size_bytes"] == len(data)
    assert p["side"] == "WORKER" and p["media_type"] == "image/jpeg" and p["discrepancy_id"] == D
    assert e["audit_event_id"] == ev["id"]
    assert client.get("/loads/DL-1002/verify-integrity", headers=admin).json()["valid"] is True
    v = client.get(f"/evidence/{e['id']}/verify", headers=admin).json()
    assert v["valid"] is True and v["file_matches_database"] and v["database_matches_audit_chain"] and v["computed_sha256"] == e["sha256"]


def test_download_returns_identical_bytes_with_safe_headers(client, worker):
    data = png(size=(30, 30))
    e = upload(client, worker, data, "shot.png").json()
    r = client.get(f"/evidence/{e['id']}/content", headers=worker)
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in r.headers["cache-control"] and 'filename="shot.png"' in r.headers["content-disposition"]
    assert "sandbox" in r.headers["content-security-policy"] and r.headers["x-evidence-sha256"] == e["sha256"]


def test_tampering_with_the_stored_file_is_detected(client, worker, admin):
    e = upload(client, worker, png(size=(30, 30)), "shot.png").json()
    f = stored_files()[0]
    f.write_bytes(f.read_bytes() + b"\x00tampered")
    v = client.get(f"/evidence/{e['id']}/verify", headers=admin).json()
    assert v["valid"] is False and v["file_matches_database"] is False and v["database_matches_audit_chain"] is True
    r = client.get(f"/evidence/{e['id']}/content", headers=admin)
    assert r.status_code == 500 and r.json()["detail"]["error"] == "EVIDENCE_TAMPERED"


def test_tampering_with_the_database_hash_is_detected_against_the_chain(client, worker, admin):
    e = upload(client, worker, png(), "shot.png").json()
    with SessionLocal() as db:
        db.execute(text("update evidence set sha256 = :h where public_id = :i"), {"h": "a" * 64, "i": e["id"]})
        db.commit()
    v = client.get(f"/evidence/{e['id']}/verify", headers=admin).json()
    assert v["valid"] is False and v["database_matches_audit_chain"] is False


# ============================================================================ duplicates
def test_same_file_twice_by_same_user_on_same_load_is_refused(client, worker):
    data = png(color=(1, 2, 3))
    first = upload(client, worker, data, "a.png").json()
    r = upload(client, worker, data, "b.png")
    assert r.status_code == 409 and r.json()["detail"]["error"] == "DUPLICATE_EVIDENCE" and r.json()["detail"]["existing_evidence_id"] == first["id"]
    assert len(stored_files()) == 1


def test_same_bytes_from_another_uploader_is_kept_but_flagged_as_not_independent(client, worker, fac1, admin):
    data = png(color=(9, 9, 9))
    first = upload(client, worker, data, "a.png").json()
    second = upload(client, fac1, data, "same.png")
    assert second.status_code == 200
    s = second.json()
    assert s["sha256"] == first["sha256"] and s["duplicate_of"] == first["id"]
    assert s["independence"]["independent"] is False and any("Identical file content" in x for x in s["independence"]["reasons"])
    assert first["duplicate_of"] is None
    assert len(stored_files()) == 2 and s["side"] == "FACILITY"


# ============================================================================ authorisation + roles
def test_upload_requires_login_and_a_permitted_role(client, worker, citizen, other_worker, fac2):
    assert client.post(UP, files={"file": ("a.png", png(), "image/png")}, data={"description": "abc"}).status_code == 401
    assert upload(client, citizen, png(), "a.png").status_code == 403
    r = upload(client, other_worker, png(), "a.png")
    assert r.status_code == 403 and r.json()["detail"]["error"] == "NOT_YOUR_LOAD"
    r = upload(client, fac2, png(), "a.png")
    assert r.status_code == 403 and r.json()["detail"]["error"] == "NOT_YOUR_FACILITY"
    assert stored_files() == []


def test_side_classification_is_constrained_by_the_uploaders_relationship(client, worker, fac1, admin):
    assert upload(client, worker, png(color=(1, 1, 1)), "a.png", side="FACILITY").status_code == 422
    assert upload(client, worker, png(color=(1, 1, 2)), "a.png", side="NEUTRAL").status_code == 422
    assert upload(client, fac1, png(color=(1, 1, 3)), "a.png", side="WORKER").status_code == 422
    assert upload(client, worker, png(color=(1, 1, 4)), "a.png").json()["side"] == "WORKER"
    assert upload(client, fac1, png(color=(1, 1, 5)), "a.png").json()["side"] == "FACILITY"
    for i, side in enumerate(["WORKER", "FACILITY", "NEUTRAL"]):
        assert upload(client, admin, png(color=(2, 2, i)), "a.png", side=side).json()["side"] == side
    assert upload(client, admin, png(color=(2, 2, 9)), "a.png").json()["side"] == "NEUTRAL"
    assert upload(client, admin, png(color=(2, 2, 10)), "a.png", side="GUILTY").status_code == 422


def test_who_can_view_or_download(client, worker, other_worker, fac1, fac2, admin, citizen):
    e = upload(client, fac1, png(color=(5, 5, 5)), "f.png").json()          # facility 1's evidence
    w = upload(client, worker, png(color=(6, 6, 6)), "w.png").json()        # worker2's evidence
    for who, eid, ok in [(admin, e["id"], 200), (fac1, e["id"], 200), (fac2, e["id"], 403), (worker, e["id"], 403), (other_worker, e["id"], 403), (citizen, e["id"], 403),
                         (worker, w["id"], 200), (other_worker, w["id"], 403), (fac1, w["id"], 200), (fac2, w["id"], 403)]:
        assert client.get(f"/evidence/{eid}", headers=who).status_code == ok, (eid, ok)
        assert client.get(f"/evidence/{eid}/content", headers=who).status_code == ok
        assert client.get(f"/evidence/{eid}/verify", headers=who).status_code == ok
    assert client.get(f"/evidence/{e['id']}").status_code == 401
    assert client.get("/evidence/ev_doesnotexist", headers=admin).status_code == 404


def test_no_delete_or_update_through_the_api(client, worker, admin):
    e = upload(client, worker, png(), "a.png").json()
    for method in ("delete", "put", "patch"):
        for who in (worker, admin):
            assert getattr(client, method)(f"/evidence/{e['id']}", headers=who).status_code == 405, method
    assert getattr(client, "delete")(f"/discrepancy/{D}/evidence", headers=admin).status_code == 405
    assert len(stored_files()) == 1


def test_evidence_only_while_the_discrepancy_is_open(client, worker, fac1):
    with SessionLocal() as db:
        db.execute(text("update discrepancy_events set status = 'CLOSED' where id = 1"))
        db.commit()
    r = upload(client, worker, png(), "a.png")
    assert r.status_code == 409 and r.json()["detail"]["error"] == "DISCREPANCY_CLOSED_FOR_EVIDENCE"


# ============================================================================ GPS
def test_gps_is_stored_but_always_unverified(client, worker, admin):
    e = upload(client, worker, png(), "a.png", latitude="19.0712", longitude="72.9010", accuracy_m="8.5").json()
    assert e["gps"]["latitude"] == pytest.approx(19.0712) and e["gps"]["longitude"] == pytest.approx(72.9010)
    assert e["gps"]["verified"] is False and e["gps"]["source"] == "DEVICE_REPORTED" and "UNVERIFIED" in e["gps"]["label"]
    assert "UNVERIFIED" in e["gps_unverified_note"]
    p = next(x for x in client.get("/loads/DL-1002/events", headers=admin).json() if x["event_type"] == "EVIDENCE_ADDED")["payload"]
    assert p["location"]["verified"] is False and "UNVERIFIED" in p["location"]["note"]
    assert upload(client, worker, png(color=(3, 3, 3)), "b.png").json()["gps"] is None
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            db.execute(text("update evidence set location_verified = true where public_id = :i"), {"i": e["id"]})
            db.commit()


@pytest.mark.parametrize("form", [{"latitude": "91", "longitude": "72"}, {"latitude": "19", "longitude": "181"}, {"latitude": "19"}, {"longitude": "72"},
                                  {"latitude": "0", "longitude": "0"}, {"latitude": "nan", "longitude": "72"}, {"latitude": "abc", "longitude": "72"}])
def test_bad_gps_rejected_and_nothing_stored(client, worker, form):
    assert upload(client, worker, png(), "a.png", **form).status_code == 422
    assert stored_files() == []


# ============================================================================ persistence + REQUIRE_FILE_EVIDENCE
def test_metadata_persisted(client, worker):
    e = upload(client, worker, png(size=(20, 20)), "a.png", category="WEIGHBRIDGE_SLIP", description="slip shows 520 kg").json()
    with SessionLocal() as db:
        row = db.query(Evidence).filter(Evidence.public_id == e["id"]).one()
        assert (row.kind.value, row.side.value, row.category.value, row.load_id, row.discrepancy_id) == ("FILE_EVIDENCE", "WORKER", "WEIGHBRIDGE_SLIP", "DL-1002", D)
        assert row.uploader_id is not None and row.uploader_role == "WORKER" and row.description == "slip shows 520 kg" and row.media_type == "image/png"
        assert row.storage_backend == "local" and row.location_verified is False and row.created_at is not None and row.event_id is not None


def test_file_evidence_is_required_when_configured(client, worker, fac1, file_evidence_required):
    r = client.post(f"/discrepancy/{D}/add-evidence", json={"note": "just a note, no file attached"}, headers=fac1)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "FILE_EVIDENCE_REQUIRED"
    assert client.get(f"/discrepancy/{D}", headers=fac1).json()["status"] == "FLAGGED"
    e = upload(client, fac1, png(color=(7, 7, 7)), "slip.png").json()
    r = client.post(f"/discrepancy/{D}/add-evidence", json={"note": "weighbridge slip attached"}, headers=fac1)
    assert r.status_code == 200 and r.json()["status"] == "EVIDENCE_PENDING"
    d = client.get(f"/discrepancy/{D}", headers=fac1).json()
    assert d["evidence_mode"] == "FILE_BACKED" and d["evidence_summary"]["files"] == 1
    ev = next(x for x in d["trail"] if x["event_type"] == "DISCREPANCY_EVIDENCE_ADDED")["payload"]
    assert ev["evidence_backed"] is True and ev["evidence"] == [{"id": e["id"], "sha256": e["sha256"]}]


def test_legacy_note_only_path_is_labelled_and_never_equivalent_to_a_file(client, fac1):
    r = client.post(f"/discrepancy/{D}/add-evidence", json={"note": "legacy note only", "evidence_ref": "IMG_1.jpg"}, headers=fac1)
    assert r.status_code == 200
    d = client.get(f"/discrepancy/{D}", headers=fac1).json()
    assert d["evidence_mode"] == "LEGACY_NOTE_ONLY" and d["evidence_summary"] == {"files": 0, "notes": 1, "independent_files": 0}
    note = d["evidence"][0]
    assert note["kind"] == "NOTE" and note["evidence_backed"] is False and note["sha256"] is None and note["content_url"] is None
    assert note["independence"]["independent"] is False
    assert next(x for x in d["trail"] if x["event_type"] == "DISCREPANCY_EVIDENCE_ADDED")["payload"]["evidence_backed"] is False


def test_seeded_dl1003_is_shown_as_legacy_not_evidence_backed(client, fac1):
    d = client.get("/discrepancy/2", headers=fac1).json()
    assert d["status"] == "INVESTIGATING" and d["evidence_mode"] == "LEGACY_NOTE_ONLY" and d["corroboration_path"] == "LEGACY_MANUAL_ENTRY"
    assert d["corroboration_evidence_backed"] is False


def test_config_endpoint_states_limits_and_flag(client, worker, monkeypatch):
    c = client.get("/config/evidence", headers=worker).json()
    assert c["require_file_evidence"] is False and c["max_image_bytes"] == 10 * 1024 * 1024 and "image/png" in c["allowed_types"] and "UNVERIFIED" in c["gps_note"]
    monkeypatch.setenv("REQUIRE_FILE_EVIDENCE", "true")
    assert client.get("/config/evidence", headers=worker).json()["require_file_evidence"] is True


# ============================================================================ storage abstraction
class MemoryStorage:
    """A different backend: proves the evidence workflow depends only on the EvidenceStorage interface."""
    backend = "memory"

    def __init__(self): self.blobs, self.n = {}, 0
    def new_key(self): self.n += 1; return f"evidence/{self.n:02x}/{self.n:032x}"
    def put(self, key, fileobj): fileobj.seek(0); self.blobs[key] = fileobj.read(); return len(self.blobs[key])
    def open(self, key): return io.BytesIO(self.blobs[key])
    def exists(self, key): return key in self.blobs
    def delete(self, key): self.blobs.pop(key, None)


def test_workflow_runs_unchanged_on_another_storage_backend(client, worker, admin):
    mem = MemoryStorage()
    evidence_storage.set_storage(mem)
    try:
        data = png(color=(11, 22, 33))
        e = upload(client, worker, data, "a.png").json()
        assert len(mem.blobs) == 1 and stored_files() == []
        assert client.get(f"/evidence/{e['id']}/content", headers=admin).content == data
        assert client.get(f"/evidence/{e['id']}/verify", headers=admin).json()["valid"] is True
        with SessionLocal() as db:
            assert db.query(Evidence.storage_backend).filter(Evidence.public_id == e["id"]).scalar() == "memory"
    finally:
        evidence_storage.set_storage(None)


def test_local_storage_rejects_unsafe_keys_and_overwrites(tmp_path):
    s = LocalEvidenceStorage(tmp_path)
    for bad in ["../x", "/etc/passwd", "evidence/../../x", "evidence/ab/short", "evidence/AB/" + "a" * 32, "evidence/ab/" + "g" * 32]:
        with pytest.raises(ValueError):
            s.put(bad, io.BytesIO(b"x"))
    key = s.new_key()
    assert s.put(key, io.BytesIO(b"hello")) == 5 and s.exists(key) and s.open(key).read() == b"hello"
    with pytest.raises(FileExistsError):
        s.put(key, io.BytesIO(b"overwrite"))
    if os.name != "nt":
        assert (tmp_path / key).stat().st_mode & 0o007 == 0, "not world-accessible"


def test_a_failed_database_write_leaves_no_orphan_file(client, worker, monkeypatch):
    import app.evidence as ev_mod

    def boom(*a, **k): raise RuntimeError("db exploded")
    monkeypatch.setattr(ev_mod, "append_event", boom)
    with pytest.raises(RuntimeError):
        upload(client, worker, png(), "a.png")
    assert stored_files() == []


def test_load_chain_stays_valid_after_uploads(client, worker, fac1, admin):
    upload(client, worker, png(color=(1, 0, 0)), "a.png"); upload(client, fac1, png(color=(0, 1, 0)), "b.png")
    assert client.get("/loads/DL-1002/verify-integrity", headers=admin).json()["valid"] is True
    types = [e["event_type"] for e in client.get("/loads/DL-1002/events", headers=admin).json()]
    assert types.count("EVIDENCE_ADDED") == 2
