from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


class SampleOut(BaseModel):
    id: int
    name: str
    description: str
    is_broken: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class JobCreate(BaseModel):
    sampleId: int | None = None
    fastqText: str | None = Field(default=None, alias="fastqText")

    model_config = {"populate_by_name": True}


class StageOut(BaseModel):
    id: int
    actor_name: str
    stage_order: int
    status: str
    message: str | None
    duration_ms: float | None = None
    timed_out: bool = False
    timeout_ms_limit: int | None = None
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: int
    sample_id: int | None
    sample_name: str
    status: str
    created_by: str
    timed_out: bool = False
    metrics: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None
    stages: list[StageOut] = []

    model_config = {"from_attributes": True}


class JobListItem(BaseModel):
    id: int
    sample_id: int | None
    sample_name: str
    status: str
    created_by: str
    timed_out: bool = False
    metrics: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class HealthOut(BaseModel):
    status: str
    service: str


# ---------- 耗时与超时门禁台 ----------


class TimeoutConfigOut(BaseModel):
    actor_name: str
    timeout_ms: int
    updated_by: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class TimeoutConfigUpdate(BaseModel):
    # 0 表示"任何非零耗时即判超时"，用于门禁演练/自测
    timeout_ms: int = Field(ge=0, le=3_600_000)


class StageTimingOut(BaseModel):
    actor_name: str
    stage_order: int
    status: str
    duration_ms: float | None
    timeout_ms_limit: int | None
    timed_out: bool


class JobTimingOut(BaseModel):
    job_id: int
    sample_name: str
    status: str
    timed_out: bool
    total_duration_ms: float | None
    stages: list[StageTimingOut]


class StageAvgTimingOut(BaseModel):
    actor_name: str
    stage_order: int
    avg_duration_ms: float | None
    max_duration_ms: float | None
    sample_size: int


class TimingSummaryOut(BaseModel):
    window: int  # 统计窗口：最近 N 个成功作业
    job_count: int  # 窗口内实际成功作业数
    stages: list[StageAvgTimingOut]


class ExceededStageOut(BaseModel):
    actor_name: str
    duration_ms: float | None
    timeout_ms_limit: int | None


class TimeoutJobOut(BaseModel):
    job_id: int
    sample_name: str
    status: str
    created_by: str
    created_at: datetime
    finished_at: datetime | None
    exceeded_stages: list[ExceededStageOut]
