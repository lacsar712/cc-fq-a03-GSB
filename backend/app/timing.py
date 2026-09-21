"""耗时与超时门禁的服务端计算：默认配置、单作业耗时、均值汇总、超时清单。

所有耗时与超时判定都在服务端完成并落库，前端只负责展示这里返回的结果。
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models import ActorTimeoutConfig, Job, JobStage
from app.pipeline.actors import ACTOR_CHAIN

# 每个 Actor 的默认超时上限（毫秒）；0 表示"任何非零耗时即判超时"（门禁演练用）
DEFAULT_TIMEOUT_MS = 5000

ACTOR_ORDER = {cls.name: order for order, cls in enumerate(ACTOR_CHAIN)}


def ensure_default_timeout_configs(db: Session) -> None:
    """为缺失的 Actor 写入默认超时配置（幂等）。"""
    existing = {row.actor_name for row in db.query(ActorTimeoutConfig).all()}
    for cls in ACTOR_CHAIN:
        if cls.name not in existing:
            db.add(
                ActorTimeoutConfig(
                    actor_name=cls.name,
                    timeout_ms=DEFAULT_TIMEOUT_MS,
                    updated_by="system",
                )
            )
    db.commit()


def load_timeouts(db: Session) -> dict[str, int]:
    """读取当前生效的 {actor_name: timeout_ms}。"""
    return {row.actor_name: row.timeout_ms for row in db.query(ActorTimeoutConfig).all()}


def list_timeout_configs(db: Session) -> list[ActorTimeoutConfig]:
    """按流水线阶段顺序返回全部超时配置。"""
    rows = db.query(ActorTimeoutConfig).all()
    return sorted(rows, key=lambda r: ACTOR_ORDER.get(r.actor_name, len(ACTOR_ORDER)))


def compute_job_timing(db: Session, job_id: int) -> dict | None:
    """单作业四阶段毫秒耗时（服务端已落库的 duration_ms 直接汇总返回）。"""
    job = (
        db.query(Job)
        .options(selectinload(Job.stages))
        .filter(Job.id == job_id)
        .first()
    )
    if job is None:
        return None
    stages = sorted(job.stages, key=lambda s: s.stage_order)
    durations = [s.duration_ms for s in stages if s.duration_ms is not None]
    total = round(sum(durations), 3) if durations else None
    return {
        "job_id": job.id,
        "sample_name": job.sample_name,
        "status": job.status,
        "timed_out": job.timed_out,
        "total_duration_ms": total,
        "stages": [
            {
                "actor_name": s.actor_name,
                "stage_order": s.stage_order,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "timeout_ms_limit": s.timeout_ms_limit,
                "timed_out": s.timed_out,
            }
            for s in stages
        ],
    }


def compute_timing_summary(db: Session, window: int) -> dict:
    """最近 window 个成功作业的各阶段平均/最大耗时（服务端聚合）。"""
    recent_ids = [
        row[0]
        for row in db.query(Job.id)
        .filter(Job.status == "success")
        .order_by(Job.id.desc())
        .limit(window)
        .all()
    ]
    if not recent_ids:
        return {"window": window, "job_count": 0, "stages": []}

    rows = (
        db.query(
            JobStage.actor_name,
            func.avg(JobStage.duration_ms),
            func.max(JobStage.duration_ms),
            func.count(JobStage.id),
        )
        .filter(
            JobStage.job_id.in_(recent_ids),
            JobStage.status == "success",
            JobStage.duration_ms.isnot(None),
        )
        .group_by(JobStage.actor_name)
        .all()
    )
    stages = [
        {
            "actor_name": name,
            "stage_order": ACTOR_ORDER.get(name, len(ACTOR_CHAIN)),
            "avg_duration_ms": round(avg, 3) if avg is not None else None,
            "max_duration_ms": round(mx, 3) if mx is not None else None,
            "sample_size": cnt,
        }
        for name, avg, mx, cnt in rows
    ]
    stages.sort(key=lambda s: s["stage_order"])
    return {"window": window, "job_count": len(recent_ids), "stages": stages}


def list_timeout_jobs(db: Session) -> list[dict]:
    """超时清单：任一阶段超限的作业，行内带超限阶段明细。"""
    jobs = (
        db.query(Job)
        .options(selectinload(Job.stages))
        .filter(Job.timed_out.is_(True))
        .order_by(Job.id.desc())
        .all()
    )
    result = []
    for job in jobs:
        exceeded = sorted(
            (s for s in job.stages if s.timed_out),
            key=lambda s: s.stage_order,
        )
        result.append(
            {
                "job_id": job.id,
                "sample_name": job.sample_name,
                "status": job.status,
                "created_by": job.created_by,
                "created_at": job.created_at,
                "finished_at": job.finished_at,
                "exceeded_stages": [
                    {
                        "actor_name": s.actor_name,
                        "duration_ms": s.duration_ms,
                        "timeout_ms_limit": s.timeout_ms_limit,
                    }
                    for s in exceeded
                ],
            }
        )
    return result
