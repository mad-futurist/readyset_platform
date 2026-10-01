import time

import pytest

from app.knowledge import worker

pytestmark = pytest.mark.worker


def test_worker_health_reports_missing_fresh_and_stale_heartbeat(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    health = tmp_path / "worker.health"
    monkeypatch.setattr(worker, "HEALTH_FILE", health)
    monkeypatch.setattr("sys.argv", ["worker", "--health"])
    with pytest.raises(SystemExit) as missing:
        worker.main()
    assert missing.value.code == 1
    health.write_text(str(time.time()))
    with pytest.raises(SystemExit) as fresh:
        worker.main()
    assert fresh.value.code == 0
    health.write_text(str(time.time() - 7200))
    with pytest.raises(SystemExit) as stale:
        worker.main()
    assert stale.value.code == 1


def test_queue_metrics_contain_counts_without_source_data(db_factory) -> None:
    with db_factory() as db:
        assert worker.queue_metrics(db) == {"pending_jobs": 0, "failed_jobs": 0, "retryable_jobs": 0, "running_jobs": 0, "retry_count": 0}


def test_heartbeat_loss_prevents_continued_processing(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    # Exercise the actual renewal thread without sleeps: the first wait permits
    # a renewal; a rejected lease stops the thread and invalidates the processor.
    monkeypatch.setattr(worker, "renew", lambda *_: False)
    heartbeat = worker.LeaseHeartbeat(db_factory, None, worker.Settings())
    monkeypatch.setattr(heartbeat.stop, "wait", lambda _: False)
    heartbeat._run()
    with pytest.raises(worker.LostLease):
        heartbeat.check()
