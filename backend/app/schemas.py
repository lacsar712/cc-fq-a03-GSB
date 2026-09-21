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
    started_at: datetime | None
    finished_at: datetime | None
    # 服务端计算并返回的耗时/门禁字段
    duration_ms: int | None
    timeout_ms: int | None
    timed_out: bool

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: int
    sample_id: int | None
    sample_name: str
    status: str
    timed_out: bool
    created_by: str
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
    timed_out: bool
    created_by: str
    metrics: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


# ---- 耗时台 / 超时门禁 ----


class TimeoutConfigOut(BaseModel):
    actor_name: str
    timeout_ms: int
    updated_by: str
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class TimeoutConfigItem(BaseModel):
    actor_name: str
    timeout_ms: int = Field(ge=1, le=24 * 60 * 60 * 1000)


class TimeoutConfigUpdate(BaseModel):
    items: list[TimeoutConfigItem]


class StageTimingOut(BaseModel):
    """单作业某阶段的服务端耗时与门禁结果。"""

    actor_name: str
    stage_order: int
    status: str
    duration_ms: int | None
    timeout_ms: int | None
    timed_out: bool


class JobTimingOut(BaseModel):
    job_id: int
    sample_name: str
    status: str
    timed_out: bool
    created_at: datetime
    finished_at: datetime | None
    total_duration_ms: int | None
    stages: list[StageTimingOut]


class StageAverageOut(BaseModel):
    actor_name: str
    stage_order: int
    sample_count: int
    avg_duration_ms: float
    min_duration_ms: int | None
    max_duration_ms: int | None


class TimingOverviewOut(BaseModel):
    success_window: int
    job_count: int
    averages: list[StageAverageOut]
    recent_success_job_ids: list[int]


class TimeoutStageOut(BaseModel):
    actor_name: str
    stage_order: int
    duration_ms: int
    timeout_ms: int


class TimeoutJobOut(BaseModel):
    """超时清单中的一行:作业 + 行内标出的超限阶段。"""

    id: int
    sample_name: str
    status: str
    timed_out: bool
    created_by: str
    created_at: datetime
    finished_at: datetime | None
    over_stages: list[TimeoutStageOut]


class HealthOut(BaseModel):
    status: str
    service: str
