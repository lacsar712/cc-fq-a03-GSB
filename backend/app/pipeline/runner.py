"""Orchestrate Actor chain with asyncio queues and persist stage status.

Server-side timing: each stage is wall-clock timed (perf_counter, integer ms)
around its actor execution, including a small simulated processing latency so
the microsecond-fast toy workload yields non-zero, gate-able durations. The
per-actor timeout ceiling is snapshotted from the persisted config when the
job starts; a stage whose measured duration exceeds its ceiling is marked
timed_out, the chain stops, and the job is recorded as a timeout. Nothing here
is estimated by the frontend.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Job, JobStage
from app.pipeline.actors import (
    ACTOR_CHAIN,
    NContentActor,
    ParseActor,
    PipelineContext,
    QualityHistActor,
    QueueMessage,
    ReportActor,
)
from app.pipeline.timing import SIMULATED_STAGE_LATENCY_MS, load_timeout_map


STAGE_NAMES = [cls.name for cls in ACTOR_CHAIN]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _run_chain(
    fastq_text: str,
    timeouts: dict[str, int | None],
) -> tuple[bool, PipelineContext, dict[str, dict]]:
    """
    Run Parse → QualityHist → NContent → Report via asyncio queues.
    Returns (success, context, stage_status keyed by actor name).

    A stage whose measured duration exceeds its (snapshotted) ceiling is marked
    timed_out and treated as a failure that halts the chain.
    """
    actors = [ParseActor(), QualityHistActor(), NContentActor(), ReportActor()]
    queues: list[asyncio.Queue] = [asyncio.Queue() for _ in range(len(actors) + 1)]
    stage_status: dict[str, dict] = {
        a.name: {
            "status": "pending",
            "message": None,
            "duration_ms": None,
            "timeout_ms": timeouts.get(a.name),
            "timed_out": False,
        }
        for a in actors
    }

    ctx = PipelineContext(fastq_text=fastq_text)
    await queues[0].put(QueueMessage(ok=True, context=ctx))

    final = QueueMessage(ok=False, context=ctx, error="流水线未执行")
    # Queue-driven chain: each actor consumes from queues[i] and produces to queues[i+1]
    for i, actor in enumerate(actors):
        stage_status[actor.name]["status"] = "running"

        latency = SIMULATED_STAGE_LATENCY_MS.get(actor.name, 0) / 1000.0
        started = time.perf_counter()
        await asyncio.sleep(latency)  # simulated work, inside the measured window
        await actor.run(queues[i], queues[i + 1])
        result: QueueMessage = await queues[i + 1].get()
        duration_ms = int(round((time.perf_counter() - started) * 1000))

        ceiling = timeouts.get(actor.name)
        over_limit = ceiling is not None and duration_ms > ceiling
        stage_status[actor.name]["duration_ms"] = duration_ms

        final = result
        if over_limit:
            # Timeout gate wins regardless of the actor's own outcome.
            msg = f"阶段耗时 {duration_ms} ms 超过上限 {ceiling} ms（超时门禁）"
            stage_status[actor.name].update(
                status="failed", message=msg, timed_out=True
            )
            ctx.failed_actor = actor.name
            ctx.error = msg
            final = QueueMessage(ok=False, context=ctx, error=msg)
            for later in actors[i + 1 :]:
                stage_status[later.name]["status"] = "skipped"
                stage_status[later.name]["message"] = f"因 {actor.name} 超时被跳过"
            break
        if result.ok:
            stage_status[actor.name]["status"] = "success"
            stage_status[actor.name]["message"] = "完成"
            # Forward to next actor's input (same queue slot for the next hop)
            if i + 1 < len(actors):
                await queues[i + 1].put(result)
        else:
            stage_status[actor.name]["status"] = "failed"
            stage_status[actor.name]["message"] = result.error or "失败"
            for later in actors[i + 1 :]:
                stage_status[later.name]["status"] = "skipped"
                stage_status[later.name]["message"] = f"因 {actor.name} 失败而跳过"
            break

    return final.ok, final.context, stage_status


def run_pipeline_sync(db: Session, job: Job) -> Job:
    """Execute pipeline for a job and update DB stages/metrics/timing."""
    stages = (
        db.query(JobStage)
        .filter(JobStage.job_id == job.id)
        .order_by(JobStage.stage_order)
        .all()
    )
    stage_by_name = {s.actor_name: s for s in stages}

    # Snapshot the configured ceilings for this run.
    timeouts = load_timeout_map(db)
    for name, st in stage_by_name.items():
        st.timeout_ms = timeouts.get(name)

    job.status = "running"
    db.commit()

    success, ctx, stage_status = asyncio.run(_run_chain(job.fastq_snapshot, timeouts))

    any_timeout = False
    for name, info in stage_status.items():
        st = stage_by_name[name]
        st.status = info["status"]
        st.message = info["message"]
        st.duration_ms = info["duration_ms"]
        st.timeout_ms = info["timeout_ms"]
        st.timed_out = info["timed_out"]
        if info["timed_out"]:
            any_timeout = True
        if info["status"] in ("running", "success", "failed"):
            st.started_at = st.started_at or _utcnow()
        if info["status"] in ("success", "failed", "skipped"):
            st.finished_at = _utcnow()
            if info["status"] == "skipped" and st.started_at is None:
                st.started_at = st.finished_at

    job.timed_out = any_timeout
    if any_timeout:
        job.status = "timeout"
        job.metrics = ctx.metrics or None
        job.error_message = ctx.error or "阶段超时"
    elif success:
        job.status = "success"
        job.metrics = ctx.metrics
        job.error_message = None
    else:
        job.status = "failed"
        job.metrics = ctx.metrics or None
        job.error_message = ctx.error or "流水线失败"
    job.finished_at = _utcnow()
    db.commit()
    db.refresh(job)
    return job


def create_job_stages(db: Session, job_id: int) -> list[JobStage]:
    # Make sure a ceiling exists for every actor before stages are created.
    timeouts = load_timeout_map(db)
    stages = []
    for order, cls in enumerate(ACTOR_CHAIN):
        st = JobStage(
            job_id=job_id,
            actor_name=cls.name,
            stage_order=order,
            status="pending",
            timeout_ms=timeouts.get(cls.name),
        )
        db.add(st)
        stages.append(st)
    db.commit()
    return stages
