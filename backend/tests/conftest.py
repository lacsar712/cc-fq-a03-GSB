"""Pytest fixtures: run the API against a throwaway SQLite file database.

DATABASE_URL must be set before any ``app.*`` module is imported so that
``app.config`` picks it up; hence the environment mutation at import time here.
"""

import os
import tempfile
from pathlib import Path

_DB_PATH = Path(tempfile.gettempdir()) / "fq_pipeline_pytest.sqlite3"
if _DB_PATH.exists():
    _DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.pipeline.runner import run_pipeline_sync  # noqa: E402
from app.models import Job  # noqa: E402


@pytest.fixture(scope="session")
def client():
    # Make the POST /jobs background task a no-op: tests drive the pipeline
    # explicitly so execution is deterministic and not thread/race dependent.
    import app.api as api_module

    api_module._run_job_background = lambda job_id: None
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def token_factory(client):
    def _token(username: str, password: str) -> str:
        resp = client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]

    return _token


@pytest.fixture()
def bioops_headers(token_factory):
    return {"Authorization": f"Bearer {token_factory('bioops', 'fastq123456')}"}


@pytest.fixture()
def auditor_headers(token_factory):
    return {"Authorization": f"Bearer {token_factory('auditor', 'audit123456')}"}


GOOD_FASTQ = """@SEQ1
ACGTACGT
+
IIIIHHHH
@SEQ2
NNNNACGT
+
IIIIIIII
"""


@pytest.fixture()
def run_job():
    """Create-helper closure: run a submitted job synchronously in this thread."""

    def _run(job_id: int):
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            run_pipeline_sync(db, job)
            db.refresh(job)
            return job
        finally:
            db.close()

    return _run
