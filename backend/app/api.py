from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.auth import authenticate_user, create_access_token, get_current_user, require_bioops
from app.database import SessionLocal, get_db
from app.models import ActorTimeoutConfig, Job, JobStage, Sample
from app.pipeline.actors import ACTOR_CHAIN
from app.pipeline.runner import create_job_stages, run_pipeline_sync
from app.schemas import (
    HealthOut,
    JobCreate,
    JobListItem,
    JobOut,
    JobTimingOut,
    LoginRequest,
    SampleOut,
    StageOut,
    TimeoutConfigOut,
    TimeoutConfigUpdate,
    TimeoutJobOut,
    TimingSummaryOut,
    TokenResponse,
)
from app.timing import (
    compute_job_timing,
    compute_timing_summary,
    ensure_default_timeout_configs,
    list_timeout_configs,
    list_timeout_jobs,
)


router = APIRouter(prefix="/api")


def _run_job_background(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            run_pipeline_sync(db, job)
    finally:
        db.close()


@router.get("/health", response_model=HealthOut)
def health():
    return HealthOut(status="ok", service="fastq-qc-pipeline")


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user = authenticate_user(body.username.strip(), body.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user["username"], user["role"])
    return TokenResponse(
        access_token=token,
        username=user["username"],
        role=user["role"],
    )


@router.get("/samples", response_model=list[SampleOut])
def list_samples(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Sample).order_by(Sample.id).all()


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    body: JobCreate,
    background: BackgroundTasks,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    sample_id = body.sampleId
    fastq_text = (body.fastqText or "").strip() if body.fastqText else ""
    sample_name = "自定义输入"
    sample = None

    if sample_id is not None:
        sample = db.query(Sample).filter(Sample.id == sample_id).first()
        if not sample:
            raise HTTPException(status_code=404, detail="样例不存在")
        fastq_text = sample.fastq_content
        sample_name = sample.name
    elif not fastq_text:
        raise HTTPException(status_code=400, detail="请提供 sampleId 或 fastqText")

    job = Job(
        sample_id=sample.id if sample else None,
        sample_name=sample_name,
        status="pending",
        created_by=user["username"],
        fastq_snapshot=fastq_text,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    create_job_stages(db, job.id)
    background.add_task(_run_job_background, job.id)

    job = (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job.id)
        .first()
    )
    return job


@router.get("/jobs", response_model=list[JobListItem])
def list_jobs(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Job).order_by(Job.id.desc()).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return job


@router.get("/jobs/{job_id}/stages", response_model=list[StageOut])
def get_job_stages(
    job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return (
        db.query(JobStage)
        .filter(JobStage.job_id == job_id)
        .order_by(JobStage.stage_order)
        .all()
    )


# ---------- 耗时与超时门禁台 ----------


@router.get("/timing/config", response_model=list[TimeoutConfigOut])
def get_timeout_configs(
    _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """查看每个 Actor 的超时上限（运维与审计员均可读）。"""
    ensure_default_timeout_configs(db)
    return list_timeout_configs(db)


@router.put("/timing/config/{actor_name}", response_model=TimeoutConfigOut)
def update_timeout_config(
    actor_name: str,
    body: TimeoutConfigUpdate,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    """运维修改某 Actor 的超时毫秒上限并落库；审计员调用返回 403。"""
    valid_names = {cls.name for cls in ACTOR_CHAIN}
    if actor_name not in valid_names:
        raise HTTPException(status_code=404, detail=f"未知 Actor: {actor_name}")
    row = (
        db.query(ActorTimeoutConfig)
        .filter(ActorTimeoutConfig.actor_name == actor_name)
        .first()
    )
    if row is None:
        row = ActorTimeoutConfig(actor_name=actor_name, timeout_ms=body.timeout_ms)
        db.add(row)
    row.timeout_ms = body.timeout_ms
    row.updated_by = user["username"]
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


@router.get("/timing/summary", response_model=TimingSummaryOut)
def get_timing_summary(
    limit: int = Query(default=20, ge=1, le=200),
    _user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """最近 limit 个成功作业的各阶段平均耗时（服务端聚合）。"""
    return compute_timing_summary(db, limit)


@router.get("/timing/timeouts", response_model=list[TimeoutJobOut])
def get_timeout_jobs(
    _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """超时清单：任一阶段超限的作业，行内带超限阶段明细。"""
    return list_timeout_jobs(db)


@router.get("/timing/jobs/{job_id}", response_model=JobTimingOut)
def get_job_timing(
    job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """单作业四阶段毫秒耗时与超限标记（全部服务端计算）。"""
    timing = compute_job_timing(db, job_id)
    if timing is None:
        raise HTTPException(status_code=404, detail="作业不存在")
    return timing
