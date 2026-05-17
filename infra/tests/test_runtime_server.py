"""Offline contract test for the AgentCore async shim (runtime/server.py).

No socket, no AWS: the request logic is exposed as functions. Asserts
the async contract — /invocations is non-blocking, /ping reports busy
during a run — and the critical product nuance that a valid
no-grounded-findings run (no output/2-report.md) is a SUCCESS, not an
infrastructure failure.
"""
import threading
import time

import pytest

from runtime import server


class _FakeS3:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str]] = []

    def upload_file(self, path: str, bucket: str, key: str) -> None:
        self.uploads.append((path, bucket, key))


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Fresh run state, a temp cwd for output/, a fake S3, a bucket."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    monkeypatch.setenv("REPORT_BUCKET", "test-report-bucket")
    fake = _FakeS3()
    monkeypatch.setattr(server, "_s3_client", lambda: fake)
    server._RUN.update(
        thread=None, id=None, state="idle", grounded=False,
        artifacts=[], error=None,
    )
    yield fake
    t = server._RUN["thread"]
    if t is not None and t.is_alive():
        t.join(timeout=5)


def _join():
    t = server._RUN["thread"]
    assert t is not None
    t.join(timeout=5)
    assert not t.is_alive(), "run thread did not finish"


def _write(name: str) -> None:
    with open(f"output/{name}", "w", encoding="utf-8") as fh:
        fh.write("x")


def test_invocations_is_nonblocking_and_ping_reports_busy(_isolate, monkeypatch):
    release = threading.Event()

    def fake_run():
        release.wait(timeout=5)
        _write("1-requirements.md")
        _write("2-report.md")

    monkeypatch.setattr(server, "_run_crew", fake_run)

    start = time.perf_counter()
    code, body = server.start_invocation()
    elapsed = time.perf_counter() - start

    assert code == 202 and body["run_id"]
    assert elapsed < 0.5, f"/invocations blocked for {elapsed:.2f}s"
    assert server.ping() == {"status": "HealthyBusy"}  # run still in flight

    release.set()
    _join()

    assert server.ping() == {"status": "Healthy"}
    st = server.status()
    assert st["state"] == "completed"
    assert st["grounded"] is True
    assert len(st["artifacts"]) == 2
    assert len(_isolate.uploads) == 2


def test_no_grounded_findings_run_is_success_not_failure(_isolate, monkeypatch):
    # ConditionalTask skipped -> only 1-requirements.md exists. This is a
    # correct not-found-honesty outcome and must NOT be an infra failure.
    def fake_run():
        _write("1-requirements.md")

    monkeypatch.setattr(server, "_run_crew", fake_run)

    server.start_invocation()
    _join()

    st = server.status()
    assert st["state"] == "completed"
    assert st["grounded"] is False
    assert st["artifacts"] == ["reports/%s/1-requirements.md" % st["run_id"]]
    assert st["error"] is None
    assert len(_isolate.uploads) == 1


def test_crew_failure_is_surfaced_never_silent_success(_isolate, monkeypatch):
    def fake_run():
        raise RuntimeError("crew blew up")

    monkeypatch.setattr(server, "_run_crew", fake_run)

    server.start_invocation()
    _join()

    st = server.status()
    assert st["state"] == "failed"
    assert "crew blew up" in st["error"]
    assert server.ping() == {"status": "Healthy"}


def test_concurrent_invocation_is_rejected(_isolate, monkeypatch):
    release = threading.Event()

    def fake_run():
        release.wait(timeout=5)
        _write("1-requirements.md")

    monkeypatch.setattr(server, "_run_crew", fake_run)

    code1, _ = server.start_invocation()
    code2, body2 = server.start_invocation()
    assert code1 == 202
    assert code2 == 409 and "in flight" in body2["error"]

    release.set()
    _join()
