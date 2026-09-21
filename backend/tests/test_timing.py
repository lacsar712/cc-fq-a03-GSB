"""耗时与超时门禁：服务端计时、超时判定、配置权限、汇总与清单。

使用 SQLite 内存库，不依赖 Postgres。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import router
from app.database import Base, get_db
from app.models import ActorTimeoutConfig, Job, JobStage
from app.pipeline.runner import create_job_stages, run_pipeline_sync
from app.timing import (
    compute_job_timing,
    compute_timing_summary,
    ensure_default_timeout_configs,
    list_timeout_jobs,
)

GOOD_FASTQ = """@SEQ1
ACGTACGT
+
IIIIHHHH
@SEQ2
NNNNACGT
+
IIIIIIII
"""


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    ensure_default_timeout_configs(db)
    db.close()
    return factory


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture()
def client(session_factory, monkeypatch):
    # 后台任务走的是 app.api.SessionLocal，替换为测试库
    monkeypatch.setattr("app.api.SessionLocal", session_factory)
    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _make_job(db, fastq=GOOD_FASTQ):
    job = Job(
        sample_name="ut-sample",
        status="pending",
        created_by="bioops",
        fastq_snapshot=fastq,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    create_job_stages(db, job.id)
    return job


def _set_timeout(db, actor_name, timeout_ms):
    row = (
        db.query(ActorTimeoutConfig)
        .filter(ActorTimeoutConfig.actor_name == actor_name)
        .first()
    )
    row.timeout_ms = timeout_ms
    db.commit()


def _auth(client, username, password):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------- 服务端计时与超时判定 ----------


def test_runner_records_server_side_duration(db):
    job = _make_job(db)
    run_pipeline_sync(db, job)

    stages = (
        db.query(JobStage)
        .filter(JobStage.job_id == job.id)
        .order_by(JobStage.stage_order)
        .all()
    )
    assert len(stages) == 4
    for st in stages:
        assert st.status == "success"
        assert st.duration_ms is not None and st.duration_ms >= 0
        assert st.timed_out is False  # 默认 5000ms 上限不会触发
        assert st.timeout_ms_limit == 5000
        assert st.started_at is not None and st.finished_at is not None
    db.refresh(job)
    assert job.timed_out is False


def test_low_parse_timeout_marks_stage_and_job(db):
    _set_timeout(db, "ParseActor", 0)  # 0ms：任何非零耗时即判超时
    job = _make_job(db)
    run_pipeline_sync(db, job)

    stages = {
        s.actor_name: s
        for s in db.query(JobStage).filter(JobStage.job_id == job.id).all()
    }
    assert stages["ParseActor"].timed_out is True
    assert stages["ParseActor"].timeout_ms_limit == 0
    assert stages["ParseActor"].duration_ms is not None
    # 其余阶段上限仍为默认，不应超限
    assert stages["QualityHistActor"].timed_out is False
    assert stages["ReportActor"].timed_out is False
    db.refresh(job)
    assert job.timed_out is True
    assert job.status == "success"  # 超时只标记，不阻断流水线


def test_timeout_jobs_list_marks_exceeded_stage(db):
    _set_timeout(db, "ParseActor", 0)
    job = _make_job(db)
    run_pipeline_sync(db, job)

    rows = list_timeout_jobs(db)
    assert len(rows) == 1
    assert rows[0]["job_id"] == job.id
    exceeded = rows[0]["exceeded_stages"]
    assert [s["actor_name"] for s in exceeded] == ["ParseActor"]
    assert exceeded[0]["timeout_ms_limit"] == 0


def test_timing_summary_averages_recent_successful_jobs(db):
    for _ in range(2):
        job = _make_job(db)
        run_pipeline_sync(db, job)

    summary = compute_timing_summary(db, 10)
    assert summary["job_count"] == 2
    assert [s["actor_name"] for s in summary["stages"]] == [
        "ParseActor",
        "QualityHistActor",
        "NContentActor",
        "ReportActor",
    ]
    for s in summary["stages"]:
        assert s["sample_size"] == 2
        assert s["avg_duration_ms"] is not None and s["avg_duration_ms"] >= 0
        assert s["max_duration_ms"] is not None


def test_job_timing_detail(db):
    job = _make_job(db)
    run_pipeline_sync(db, job)

    timing = compute_job_timing(db, job.id)
    assert timing["job_id"] == job.id
    assert timing["timed_out"] is False
    assert len(timing["stages"]) == 4
    assert timing["total_duration_ms"] is not None
    stage_sum = round(sum(s["duration_ms"] for s in timing["stages"]), 3)
    assert timing["total_duration_ms"] == stage_sum


# ---------- API：权限与自测口令链路 ----------


def test_auditor_can_read_but_cannot_update_config(client):
    auditor = _auth(client, "auditor", "audit123456")

    resp = client.get("/api/timing/config", headers=auditor)
    assert resp.status_code == 200
    assert {c["actor_name"] for c in resp.json()} == {
        "ParseActor",
        "QualityHistActor",
        "NContentActor",
        "ReportActor",
    }

    resp = client.put(
        "/api/timing/config/ParseActor", json={"timeout_ms": 100}, headers=auditor
    )
    assert resp.status_code == 403

    # 审计员可读清单与单作业耗时
    assert client.get("/api/timing/timeouts", headers=auditor).status_code == 200
    assert client.get("/api/timing/summary", headers=auditor).status_code == 200


def test_bioops_can_update_config_and_validation(client):
    ops = _auth(client, "bioops", "fastq123456")

    resp = client.put("/api/timing/config/ParseActor", json={"timeout_ms": 250}, headers=ops)
    assert resp.status_code == 200
    assert resp.json()["timeout_ms"] == 250
    assert resp.json()["updated_by"] == "bioops"

    # 落库校验：再次读取仍是 250
    resp = client.get("/api/timing/config", headers=ops)
    parse_cfg = next(c for c in resp.json() if c["actor_name"] == "ParseActor")
    assert parse_cfg["timeout_ms"] == 250

    # 非法值与未知 Actor
    assert (
        client.put("/api/timing/config/ParseActor", json={"timeout_ms": -1}, headers=ops).status_code
        == 422
    )
    assert (
        client.put("/api/timing/config/NoSuchActor", json={"timeout_ms": 1}, headers=ops).status_code
        == 404
    )


def test_timing_endpoints_require_login(client):
    assert client.get("/api/timing/config").status_code == 401
    assert client.get("/api/timing/timeouts").status_code == 401
    assert client.get("/api/timing/summary").status_code == 401
    assert client.get("/api/timing/jobs/1").status_code == 401


def test_selftest_flow_low_parse_timeout_lands_in_timeout_list(client):
    """自测口令：把解析超时调很低 → 重跑合格样例 → 超时清单出现该单且可进详情。"""
    ops = _auth(client, "bioops", "fastq123456")

    # 1) 运维把 ParseActor 超时调到 0ms
    resp = client.put("/api/timing/config/ParseActor", json={"timeout_ms": 0}, headers=ops)
    assert resp.status_code == 200

    # 2) 重跑合格样例（后台任务在 TestClient 内同步执行）
    resp = client.post("/api/jobs", json={"fastqText": GOOD_FASTQ}, headers=ops)
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    # 后台流水线已执行完毕，作业被服务端标记为超时
    resp = client.get(f"/api/jobs/{job_id}", headers=ops)
    assert resp.json()["timed_out"] is True
    assert resp.json()["status"] == "success"

    # 3) 超时清单出现该单，行内标出超限阶段
    resp = client.get("/api/timing/timeouts", headers=ops)
    assert resp.status_code == 200
    entry = next((r for r in resp.json() if r["job_id"] == job_id), None)
    assert entry is not None
    assert [s["actor_name"] for s in entry["exceeded_stages"]] == ["ParseActor"]
    assert entry["exceeded_stages"][0]["duration_ms"] is not None

    # 4) 可进详情：单作业四阶段耗时由服务端返回
    resp = client.get(f"/api/timing/jobs/{job_id}", headers=ops)
    assert resp.status_code == 200
    timing = resp.json()
    assert timing["timed_out"] is True
    assert len(timing["stages"]) == 4
    parse_stage = timing["stages"][0]
    assert parse_stage["actor_name"] == "ParseActor"
    assert parse_stage["timed_out"] is True
    assert parse_stage["duration_ms"] is not None
    assert parse_stage["timeout_ms_limit"] == 0

    # 5) 作业详情接口同样带服务端耗时字段
    resp = client.get(f"/api/jobs/{job_id}/stages", headers=ops)
    assert resp.status_code == 200
    assert all("duration_ms" in s for s in resp.json())
    assert resp.json()[0]["timed_out"] is True

    # 6) 汇总接口覆盖该成功作业
    resp = client.get("/api/timing/summary?limit=5", headers=ops)
    assert resp.status_code == 200
    assert resp.json()["job_count"] == 1
    assert len(resp.json()["stages"]) == 4
