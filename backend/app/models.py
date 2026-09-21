from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Boolean, JSON, func
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
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/running/success/failed
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)  # 任一阶段超限时由服务端置 True
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
    # 以下三个字段均由服务端在流水线运行时计算并落库，前端只读展示
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)  # 阶段实际耗时（毫秒）
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否超出运行时生效的超时上限
    timeout_ms_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 运行时生效的超时上限快照
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[Job] = relationship("Job", back_populates="stages")


class ActorTimeoutConfig(Base):
    """每个 Actor 的超时上限（毫秒），运维可改，落库持久化。"""

    __tablename__ = "actor_timeout_configs"

    actor_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), default="system")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
