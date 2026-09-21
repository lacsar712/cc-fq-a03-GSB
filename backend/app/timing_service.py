"""Server-side aggregation for the timing console.

Every figure here — per-stage durations, averages over recent successful jobs,
and the timeout list with its offending stages — is computed from persisted
rows on the server. The frontend only renders what these return.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import ActorTimeoutConfig, Job, JobStage
from app.pipeline.timing import STAGE_ORDER, seed_default_timeouts
from app.schemas import (
    StageAverageOut,
    StageTimingOut,
    TimeoutJobOut,
    TimeoutStageOut,
    TimingOverviewOut,
    JobTimingOut,
)

DEFAULT_SUCCESS_WINDOW = 10
MAX_SUCCESS_WINDOW = 100


def list_timeout_configs(db: Session) -> list[ActorTimeoutConfig]:
    seed_default_timeouts(db)
    by_name = {row.actor_name: row for row in db.query(ActorTimeoutConfig).all()}
    return [by_name[name] for name in STAGE_ORDER if name in by_name]


def update_timeout_configs(
    db: Session, items: dict[str, int], username: str
) -> list[ActorTimeoutConfig]:
    seed_default_timeouts(db)
    by_name = {row.actor_name: row for row in db.query(ActorTimeoutConfig).all()}
    for name, value in items.items():
        if name not in STAGE_ORDER:
            continue
        row = by_name.get(name)
        if row is None:
            row = ActorTimeoutConfig(actor_name=name, timeout_ms=value, updated_by=username)
            db.add(row)
        else:
            row.timeout_ms = value
            row.updated_by = username
    db.commit()
    return list_timeout_configs(db)


def _total_duration(stages: list[JobStage]) -> int | None:
    done = [s.duration_ms for s in stages if s.duration_ms is not None]
    return sum(done) if done else None


def get_job_timing(db: Session, job_id: int) -> Job | None:
    return (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job_id)
        .first()
    )


def build_job_timing(job: Job) -> JobTimingOut:
    ordered = sorted(job.stages, key=lambda s: s.stage_order)
    return JobTimingOut(
        job_id=job.id,
        sample_name=job.sample_name,
        status=job.status,
        timed_out=job.timed_out,
        created_at=job.created_at,
        finished_at=job.finished_at,
        total_duration_ms=_total_duration(ordered),
        stages=[
            StageTimingOut(
                actor_name=s.actor_name,
                stage_order=s.stage_order,
                status=s.status,
                duration_ms=s.duration_ms,
                timeout_ms=s.timeout_ms,
                timed_out=s.timed_out,
            )
            for s in ordered
        ],
    )


def get_averages(db: Session, window: int) -> TimingOverviewOut:
    window = max(1, min(window, MAX_SUCCESS_WINDOW))
    recent_success_ids = [
        row.id
        for row in db.execute(
            select(Job.id)
            .where(Job.status == "success")
            .order_by(Job.id.desc())
            .limit(window)
        ).all()
    ]
    stages: list[JobStage] = []
    if recent_success_ids:
        stages = (
            db.query(JobStage)
            .filter(JobStage.job_id.in_(recent_success_ids))
            .all()
        )

    by_actor: dict[str, list[JobStage]] = {name: [] for name in STAGE_ORDER}
    for st in stages:
        if st.actor_name in by_actor and st.duration_ms is not None:
            by_actor[st.actor_name].append(st)

    averages: list[StageAverageOut] = []
    for order, name in enumerate(STAGE_ORDER):
        rows = by_actor[name]
        durations = [r.duration_ms for r in rows]
        averages.append(
            StageAverageOut(
                actor_name=name,
                stage_order=order,
                sample_count=len(rows),
                avg_duration_ms=round(sum(durations) / len(durations), 2) if durations else 0.0,
                min_duration_ms=min(durations) if durations else None,
                max_duration_ms=max(durations) if durations else None,
            )
        )

    return TimingOverviewOut(
        success_window=window,
        job_count=len(recent_success_ids),
        averages=averages,
        recent_success_job_ids=list(recent_success_ids),
    )


def get_timeout_jobs(db: Session) -> list[TimeoutJobOut]:
    jobs = (
        db.query(Job)
        .filter(Job.timed_out.is_(True))
        .order_by(Job.id.desc())
        .all()
    )
    result: list[TimeoutJobOut] = []
    for job in jobs:
        stages = (
            db.query(JobStage)
            .filter(JobStage.job_id == job.id, JobStage.timed_out.is_(True))
            .order_by(JobStage.stage_order)
            .all()
        )
        result.append(
            TimeoutJobOut(
                id=job.id,
                sample_name=job.sample_name,
                status=job.status,
                timed_out=job.timed_out,
                created_by=job.created_by,
                created_at=job.created_at,
                finished_at=job.finished_at,
                over_stages=[
                    TimeoutStageOut(
                        actor_name=s.actor_name,
                        stage_order=s.stage_order,
                        duration_ms=s.duration_ms if s.duration_ms is not None else 0,
                        timeout_ms=s.timeout_ms if s.timeout_ms is not None else 0,
                    )
                    for s in stages
                ],
            )
        )
    return result
