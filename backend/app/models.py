from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Boolean, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(512), default="")
    is_broken: Mapped[bool] = mapped_column(Boolean, default=False)
    fastq_content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_id: Mapped[int | None] = mapped_column(ForeignKey("samples.id"), nullable=True)
    sample_name: Mapped[str] = mapped_column(String(128), default="自定义输入")
    # pending/running/success/failed/timeout
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # 是否存在超时阶段(服务端门禁判定,非前端估算)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    fastq_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stages: Mapped[list["JobStage"]] = relationship(
        "JobStage", back_populates="job", cascade="all, delete-orphan", order_by="JobStage.stage_order"
    )
    sample: Mapped[Sample | None] = relationship("Sample")


class JobStage(Base):
    __tablename__ = "job_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    stage_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/running/success/failed/skipped
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 服务端测量的阶段执行耗时(毫秒)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 该作业运行时生效的超时上限快照(毫秒);None 表示未启用门禁
    timeout_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 该阶段执行是否超过 timeout_ms(由服务端判定)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    job: Mapped[Job] = relationship("Job", back_populates="stages")


class ActorTimeoutConfig(Base):
    """每个 Actor 的可配置超时上限(毫秒),运维可改、落库。"""

    __tablename__ = "actor_timeout_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), default="system")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
