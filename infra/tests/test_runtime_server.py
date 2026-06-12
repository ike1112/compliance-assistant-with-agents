"""Offline contract test for the AgentCore async shim (runtime/server.py).

No socket, no AWS: the request logic is exposed as functions. Asserts
the async contract — /invocations is non-blocking, /ping reports busy
during a run — and the critical product nuance that a valid
no-grounded-findings run (no output/2-report.md) is a SUCCESS, not an
infrastructure failure.
"""
import io
import json
import threading
import time

import pytest

from runtime import server


class _FakeS3:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str]] = []
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload_file(self, path: str, bucket: str, key: str) -> None:
        self.uploads.append((path, bucket, key))
        with open(path, "rb") as fh:
            self.objects[(bucket, key)] = fh.read()

    def put_object(self, *, Bucket: str, Key: str, Body: bytes | str,
                   ContentType: str | None = None) -> None:
        del ContentType
        if isinstance(Body, str):
            Body = Body.encode("utf-8")
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        body = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(body)}


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
        artifacts=[], error=None, updated_at=None,
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
    assert st["updated_at"]
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
    manifest = json.loads(_isolate.objects[
        ("test-report-bucket", f"runs/{st['run_id']}/manifest.json")
    ])
    assert manifest["state"] == "completed"
    assert manifest["grounded"] is False


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
    manifest = json.loads(_isolate.objects[
        ("test-report-bucket", f"runs/{st['run_id']}/manifest.json")
    ])
    assert manifest["state"] == "failed"
    assert manifest["error"] == st["error"]


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


class _FakeThread:
    """A Thread that is never alive: it isolates the pre-start window
    (state set under the lock, OS thread not yet running)."""

    def __init__(self, target=None, args=(), daemon=None, **_kw):
        self._target, self._args = target, args

    def start(self):  # deliberately does NOT run target — freezes the gap
        pass

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass

    def run_now(self):
        self._target(*self._args)


def test_no_pre_start_race(_isolate, monkeypatch):
    # codex F-001: with busy keyed off thread.is_alive(), the window
    # between state=running and Thread.start() let a 2nd /invocations
    # through and let /ping read Healthy for an accepted run. With a
    # Thread whose start() is a no-op the thread is NEVER alive, so an
    # is_alive()-based guard WOULD wrongly admit a 2nd run. A
    # state-based guard must not.
    created = {}

    def _factory(target=None, args=(), daemon=None, **kw):
        created["t"] = _FakeThread(target=target, args=args)
        return created["t"]

    monkeypatch.setattr(server.threading, "Thread", _factory)
    monkeypatch.setattr(server, "_run_crew", lambda: _write("1-requirements.md"))

    code1, body1 = server.start_invocation()
    assert code1 == 202
    # Thread is not alive (no-op start) yet the run is accepted:
    assert server.ping() == {"status": "HealthyBusy"}, (
        "ping must be HealthyBusy from locked state, not thread liveness"
    )
    code2, body2 = server.start_invocation()
    assert code2 == 409, "pre-start window admitted a second run (race)"
    assert body2["run_id"] == body1["run_id"]
    # Resolve the frozen run so state is clean for teardown.
    created["t"].run_now()
    assert server.status()["state"] == "completed"


def test_handler_routes_over_a_real_socket(_isolate, monkeypatch):
    import http.client
    from http.server import ThreadingHTTPServer

    monkeypatch.setattr(server, "_run_crew", lambda: _write("1-requirements.md"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server._Handler)
    srv = threading.Thread(target=httpd.serve_forever, daemon=True)
    srv.start()
    host, port = httpd.server_address
    try:
        c = http.client.HTTPConnection(host, port, timeout=5)
        c.request("GET", "/ping")
        r = c.getresponse()
        assert r.status == 200
        assert json.loads(r.read())["status"] in ("Healthy", "HealthyBusy")
        c.request("GET", "/status")
        assert c.getresponse().status == 200
        # POST with a body — exercises the Content-Length drain path.
        c.request("POST", "/invocations", body=json.dumps({"x": 1}),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse()
        assert r.status == 202
        assert json.loads(r.read())["run_id"]
        c.request("GET", "/nope")
        assert c.getresponse().status == 404
        # POST to an unknown path → 404 (do_POST else arm).
        c.request("POST", "/nope", body="{}")
        assert c.getresponse().status == 404
        c.close()
        _join()
    finally:
        httpd.shutdown()
        httpd.server_close()
        srv.join(timeout=5)
    assert server.status()["state"] == "completed"


def test_status_survives_process_state_reset_via_manifest(_isolate, monkeypatch):
    monkeypatch.setattr(server, "_run_crew", lambda: _write("1-requirements.md"))

    server.start_invocation()
    _join()
    first = server.status()
    server._RUN.update(
        thread=None, id=None, state="idle", grounded=False,
        artifacts=[], error=None, updated_at=None,
    )

    restored = server.status()
    assert restored == first


def test_manifest_records_running_state_before_thread_finishes(_isolate, monkeypatch):
    release = threading.Event()

    def fake_run():
        release.wait(timeout=5)
        _write("1-requirements.md")

    monkeypatch.setattr(server, "_run_crew", fake_run)

    code, body = server.start_invocation()
    assert code == 202
    key = ("test-report-bucket", f"runs/{body['run_id']}/manifest.json")
    for _ in range(50):
        manifest = json.loads(_isolate.objects[key])
        if manifest["state"] == "running":
            break
        time.sleep(0.01)
    else:
        raise AssertionError(f"manifest never reached running state: {manifest}")
    assert manifest["state"] == "running"
    assert manifest["grounded"] is False
    assert manifest["artifacts"] == []
    assert manifest["error"] is None
    assert manifest["updated_at"]

    release.set()
    _join()


def test_missing_report_bucket_is_failed_not_hung(_isolate, monkeypatch):
    # server.py docstring: a missing REPORT_BUCKET is a real misconfig
    # and must surface as a failed run (the upload-path except arm),
    # never a hang or a silent success.
    monkeypatch.delenv("REPORT_BUCKET", raising=False)
    monkeypatch.setattr(server, "_run_crew", lambda: _write("1-requirements.md"))

    code, body = server.start_invocation()
    assert code == 500
    assert body["run_id"]

    st = server.status()
    assert st["state"] == "failed"
    assert "REPORT_BUCKET" in st["error"] or "KeyError" in st["error"]
    assert server.ping() == {"status": "Healthy"}


def test_manifest_write_failure_is_failed_not_silent_success(_isolate, monkeypatch):
    class _BoomS3(_FakeS3):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def put_object(self, **kwargs):
            self.calls += 1
            raise RuntimeError("manifest write exploded")

    boom = _BoomS3()
    monkeypatch.setattr(server, "_s3_client", lambda: boom)
    monkeypatch.setattr(server, "_run_crew", lambda: _write("1-requirements.md"))

    code, body = server.start_invocation()
    assert code == 500
    assert body["run_id"]
    assert boom.calls >= 1

    st = server.status()
    assert st["run_id"] == body["run_id"]
    assert st["state"] == "failed"
    assert "manifest write exploded" in st["error"]
    assert st["artifacts"] == []


def test_s3_upload_error_is_failed_not_silent_success(_isolate, monkeypatch):
    # An upload failure must not masquerade as a grounded success.
    class _BoomS3(_FakeS3):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def upload_file(self, *_a):
            self.calls += 1
            raise RuntimeError("s3 put exploded")

    boom = _BoomS3()
    monkeypatch.setattr(server, "_s3_client", lambda: boom)

    def fake_run():
        _write("1-requirements.md")
        _write("2-report.md")

    monkeypatch.setattr(server, "_run_crew", fake_run)

    server.start_invocation()
    _join()

    st = server.status()
    assert st["state"] == "failed"
    assert st["grounded"] is False
    assert "s3 put exploded" in st["error"]
    assert boom.calls >= 1


def test_completed_run_allows_a_fresh_invocation(_isolate, monkeypatch):
    # After a run completes, busy state must clear: /ping back to
    # Healthy and a new /invocations accepted (state transitions out of
    # "running"). The 409 test only covers reject-while-running.
    monkeypatch.setattr(server, "_run_crew", lambda: _write("1-requirements.md"))

    code1, body1 = server.start_invocation()
    assert code1 == 202
    _join()
    assert server.status()["state"] == "completed"
    assert server.ping() == {"status": "Healthy"}

    code2, body2 = server.start_invocation()
    assert code2 == 202, "a fresh run must be accepted after completion"
    assert body2["run_id"] != body1["run_id"]
    _join()
    assert server.status()["state"] == "completed"
