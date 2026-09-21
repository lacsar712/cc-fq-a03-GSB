from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.auth import authenticate_user, create_access_token, get_current_user, require_bioops
from app.database import SessionLocal, get_db
from app.models import Job, JobStage, Sample
from app.pipeline.runner import create_job_stages, run_pipeline_sync
from app.pipeline.timing import STAGE_ORDER
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
    TimingOverviewOut,
    TokenResponse,
)
from app import timing_service


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


# ---------------------------------------------------------------------------
# 耗时台 / 超时门禁（耗时与是否超时一律由服务端计算返回）
# ---------------------------------------------------------------------------


@router.get("/timing/config", response_model=list[TimeoutConfigOut])
def get_timeout_configs(
    _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """审计员可读,仅运维可改(见 PUT)。"""
    return timing_service.list_timeout_configs(db)


@router.put("/timing/config", response_model=list[TimeoutConfigOut])
def put_timeout_configs(
    body: TimeoutConfigUpdate,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    known = set(STAGE_ORDER)
    unknown = [item.actor_name for item in body.items if item.actor_name not in known]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知 Actor: {', '.join(unknown)}")
    items = {item.actor_name: item.timeout_ms for item in body.items}
    return timing_service.update_timeout_configs(db, items, user["username"])


@router.get("/timing/overview", response_model=TimingOverviewOut)
def get_timing_overview(
    window: int = Query(default=10, ge=1, le=100),
    _user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """最近 window 个成功作业的各阶段平均耗时(服务端聚合)。"""
    return timing_service.get_averages(db, window)


@router.get("/timing/timeouts", response_model=list[TimeoutJobOut])
def get_timeout_list(
    _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """超时作业清单,每行内联标出超限阶段。审计员可见。"""
    return timing_service.get_timeout_jobs(db)


@router.get("/jobs/{job_id}/timing", response_model=JobTimingOut)
def get_job_timing(
    job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """单作业四阶段服务端耗时与门禁判定。"""
    job = timing_service.get_job_timing(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return timing_service.build_job_timing(job)
