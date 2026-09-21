from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api import router
from app.database import Base, engine, SessionLocal
from app.pipeline.timing import seed_default_timeouts


# Columns added after the initial release; applied idempotently so an existing
# database picks them up without a manual migration (portable across PG/SQLite).
_ADDED_COLUMNS = [
    ("jobs", "timed_out", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("job_stages", "duration_ms", "INTEGER"),
    ("job_stages", "timeout_ms", "INTEGER"),
    ("job_stages", "timed_out", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def _ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    present = {table: {col["name"] for col in inspector.get_columns(table)}
               for table in {t for t, _, _ in _ADDED_COLUMNS}
               if inspector.has_table(table)}
    with engine.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            if column not in present.get(table, set()):
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    db = SessionLocal()
    try:
        seed_default_timeouts(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _ensure_schema()
    yield


app = FastAPI(title="FASTQ QC Pipeline Console", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
