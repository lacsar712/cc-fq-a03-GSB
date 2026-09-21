"""Integration tests for the timing console and timeout gate (server-side)."""

import pytest

from app.pipeline.timing import DEFAULT_ACTOR_TIMEOUTS


GOOD_FASTQ = """@SEQ1
ACGTACGT
+
IIIIHHHH
@SEQ2
NNNNACGT
+
IIIIIIII
"""


def _submit_good(client, headers) -> int:
    resp = client.post("/api/jobs", json={"fastqText": GOOD_FASTQ}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _restore_defaults(client, headers):
    items = [{"actor_name": k, "timeout_ms": v} for k, v in DEFAULT_ACTOR_TIMEOUTS.items()]
    client.put("/api/timing/config", json={"items": items}, headers=headers)


def test_default_timeout_config_seeded(client, bioops_headers):
    resp = client.get("/api/timing/config", headers=bioops_headers)
    assert resp.status_code == 200
    cfgs = {row["actor_name"]: row["timeout_ms"] for row in resp.json()}
    assert cfgs == DEFAULT_ACTOR_TIMEOUTS


def test_unauthenticated_rejected(client):
    assert client.get("/api/timing/timeouts").status_code == 401
    assert client.get("/api/timing/overview").status_code == 401


def test_auditor_can_read_but_not_edit_config(client, auditor_headers):
    assert client.get("/api/timing/config", headers=auditor_headers).status_code == 200
    assert client.get("/api/timing/timeouts", headers=auditor_headers).status_code == 200
    assert client.get("/api/timing/overview", headers=auditor_headers).status_code == 200
    body = {"items": [{"actor_name": "ParseActor", "timeout_ms": 1}]}
    resp = client.put("/api/timing/config", json=body, headers=auditor_headers)
    assert resp.status_code == 403


def test_bioops_can_edit_config(client, bioops_headers):
    body = {"items": [{"actor_name": "ParseActor", "timeout_ms": 1234}]}
    resp = client.put("/api/timing/config", json=body, headers=bioops_headers)
    assert resp.status_code == 200
    cfgs = {r["actor_name"]: r for r in resp.json()}
    assert cfgs["ParseActor"]["timeout_ms"] == 1234
    assert cfgs["ParseActor"]["updated_by"] == "bioops"
    _restore_defaults(client, bioops_headers)


def test_config_rejects_unknown_actor_and_nonpositive(client, bioops_headers):
    bad_name = {"items": [{"actor_name": "NopeActor", "timeout_ms": 100}]}
    assert client.put("/api/timing/config", json=bad_name, headers=bioops_headers).status_code == 400
    bad_val = {"items": [{"actor_name": "ParseActor", "timeout_ms": 0}]}
    assert client.put("/api/timing/config", json=bad_val, headers=bioops_headers).status_code == 422


@pytest.mark.usefixtures("bioops_headers")
def test_low_parse_timeout_marks_good_job_timeout_and_lists_it(
    client, bioops_headers, auditor_headers, run_job
):
    # Self-test password: turn the Parse gate way down, rerun the passing sample.
    low = {"items": [{"actor_name": "ParseActor", "timeout_ms": 1}]}
    assert client.put("/api/timing/config", json=low, headers=bioops_headers).status_code == 200
    try:
        job_id = _submit_good(client, bioops_headers)
        job = run_job(job_id)

        # Server decided the outcome.
        assert job.status == "timeout"
        assert job.timed_out is True

        detail = client.get(f"/api/jobs/{job_id}", headers=auditor_headers).json()
        parse = next(s for s in detail["stages"] if s["actor_name"] == "ParseActor")
        later = [s for s in detail["stages"] if s["actor_name"] != "ParseActor"]
        assert parse["status"] == "failed"
        assert parse["timed_out"] is True
        assert parse["duration_ms"] is not None and parse["duration_ms"] > parse["timeout_ms"]
        assert parse["timeout_ms"] == 1
        assert all(s["status"] == "skipped" for s in later)

        # Timeout list (auditor-visible) contains the job with the offending stage inline.
        rows = client.get("/api/timing/timeouts", headers=auditor_headers).json()
        mine = next(r for r in rows if r["id"] == job_id)
        assert mine["timed_out"] is True
        assert [s["actor_name"] for s in mine["over_stages"]] == ["ParseActor"]
        over = mine["over_stages"][0]
        assert over["duration_ms"] > over["timeout_ms"]

        # Single-job server timing endpoint is reachable for the auditor.
        timing = client.get(f"/api/jobs/{job_id}/timing", headers=auditor_headers).json()
        assert timing["timed_out"] is True
        t_parse = next(s for s in timing["stages"] if s["actor_name"] == "ParseActor")
        assert t_parse["timed_out"] is True
        assert t_parse["duration_ms"] > 1
    finally:
        _restore_defaults(client, bioops_headers)


def test_recent_success_averages_are_server_computed(client, bioops_headers, run_job):
    ids = [run_job(_submit_good(client, bioops_headers)).id for _ in range(3)]
    resp = client.get("/api/timing/overview?window=10", headers=bioops_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_count"] >= 3
    assert set(ids).issubset(set(data["recent_success_job_ids"]))
    by_actor = {a["actor_name"]: a for a in data["averages"]}
    parse = by_actor["ParseActor"]
    assert parse["sample_count"] >= 3
    assert parse["avg_duration_ms"] > 0
    assert parse["min_duration_ms"] is not None
    # The simulated Parse latency floor is reflected in the measured average.
    assert parse["avg_duration_ms"] >= 12
