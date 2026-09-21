from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.database import Base, SessionLocal, engine
from app.timing import ensure_default_timeout_configs


# 老库升级：create_all 只建新表不补列，这里为已有表补齐耗时/超时列
_COLUMN_MIGRATIONS = [
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS timed_out BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE job_stages ADD COLUMN IF NOT EXISTS duration_ms DOUBLE PRECISION",
    "ALTER TABLE job_stages ADD COLUMN IF NOT EXISTS timed_out BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE job_stages ADD COLUMN IF NOT EXISTS timeout_ms_limit INTEGER",
]


def _ensure_columns() -> None:
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        for stmt in _COLUMN_MIGRATIONS:
            conn.exec_driver_sql(stmt)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    db = SessionLocal()
    try:
        ensure_default_timeout_configs(db)
    finally:
        db.close()
    yield


app = FastAPI(title="FASTQ QC Pipeline Console", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
