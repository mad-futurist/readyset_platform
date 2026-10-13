import argparse
import logging
import signal
import threading
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.database import SessionLocal, engine
from app.knowledge.ingestion import IngestionProcessor
from app.knowledge.jobs import ClaimedJob, LostLease, claim, renew
from app.knowledge.models import IngestionJob, JobStatus
from app.knowledge.providers import create_embedding_provider
from app.storage import S3ObjectStorage

HEALTH_FILE = Path("/tmp/readyset-worker.health")


def queue_metrics(db: Session) -> dict[str, int]:
    counts: dict[JobStatus, int] = {status: count for status, count in db.execute(
        select(IngestionJob.status, func.count()).group_by(IngestionJob.status)
    )}
    retries = db.scalar(select(func.coalesce(func.sum(IngestionJob.attempt_count - 1), 0)).where(IngestionJob.attempt_count > 1)) or 0
    return {"pending_jobs": counts.get(JobStatus.PENDING, 0), "failed_jobs": counts.get(JobStatus.FAILED, 0),
            "retryable_jobs": counts.get(JobStatus.RETRYABLE, 0), "running_jobs": counts.get(JobStatus.RUNNING, 0),
            "retry_count": retries}


class LeaseHeartbeat:
    def __init__(self, factory: sessionmaker[Session], job: ClaimedJob, settings: Settings) -> None:
        self.factory, self.job, self.settings = factory, job, settings
        self.stop, self.lost = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.wait(self.settings.worker_lease_seconds / 3):
            try:
                with self.factory() as db:
                    if not renew(db, self.job, self.settings):
                        self.lost.set()
                        return
                HEALTH_FILE.write_text(str(time.time()))
            except Exception:
                self.lost.set()
                return

    def check(self) -> None:
        if self.lost.is_set():
            raise LostLease()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.health:
        try:
            age = time.time() - float(HEALTH_FILE.read_text())
        except (OSError, ValueError):
            raise SystemExit(1) from None
        raise SystemExit(0 if age < max(settings.worker_lease_seconds, settings.worker_poll_seconds * 3) else 1)
    if not settings.ai_enabled:
        raise SystemExit("Worker requires AI_ENABLED=true")
    if engine.dialect.name != "postgresql":
        raise SystemExit("Worker requires PostgreSQL")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Keep confidential provider payloads and parser diagnostics out of ordinary logs.
    for name in ("httpx", "httpcore", "pypdf", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    shutdown = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: shutdown.set())
    storage = S3ObjectStorage(settings)
    storage.ensure_bucket()
    processor = IngestionProcessor(SessionLocal, storage, create_embedding_provider(settings), settings)
    next_metrics = 0.0
    while not shutdown.is_set():
        HEALTH_FILE.write_text(str(time.time()))
        try:
            with SessionLocal() as db:
                if time.monotonic() >= next_metrics:
                    import json
                    logging.getLogger("readyset.worker").info(json.dumps({"stage": "queue_metrics", **queue_metrics(db)}))
                    next_metrics = time.monotonic() + 30
                job = claim(db, settings)
            if job:
                heartbeat = LeaseHeartbeat(SessionLocal, job, settings)
                heartbeat.thread.start()
                try:
                    processor.process(job, heartbeat.check)
                finally:
                    heartbeat.stop.set()
                    heartbeat.thread.join(timeout=5)
        except Exception:
            logging.getLogger("readyset.worker").warning('{"stage":"claim","error_code":"database_unavailable"}')
        if args.once:
            return
        shutdown.wait(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
