"""AgentCore Runtime HTTP service-contract shim for the compliance crew.

AgentCore terminates a runtime session after 15 minutes if the
invocation path blocks the `/ping` health thread. A compliance crew run
(three agents, Bedrock calls) routinely exceeds that, so this shim
implements the AWS-documented asynchronous long-running pattern
(https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html):

- ``POST /invocations`` starts the crew on a background daemon thread and
  returns ``202`` immediately with a run id. It never joins the thread,
  so the request path (and the ping thread) is never blocked.
- ``GET /ping`` reports ``HealthyBusy`` while a run is in flight and
  ``Healthy`` when idle/done. AgentCore keeps a ``HealthyBusy`` session
  alive up to ``LifecycleConfiguration.MaxLifetime`` (8h here).
- ``GET /status`` returns the structured outcome from a durable manifest
  in the report bucket, so a crew failure is surfaced, never reported
  as a silent success, and the last run survives a container restart.

The crew's reporting stage is a CrewAI ``ConditionalTask``: when the
researcher finds no grounded source it returns "Not found in knowledge
base" and ``output/2-report.md`` is intentionally never written. That is
a correct, desirable not-found-honesty outcome — NOT an infrastructure
failure. This shim therefore uploads whatever ``output/*.md`` artifacts
exist and reports ``grounded`` from the presence of the report, with a
2xx success either way.

Plain standard library plus boto3 (already a crew dependency): no new
runtime dependency, and the request logic is exposed as functions so the
contract is unit-tested offline with no socket and no AWS.
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_PORT = 8080
_OUTPUT_GLOB = "output/*.md"
_REPORT_ARTIFACT = "output/2-report.md"
_MANIFEST_PREFIX = "runs"
_LATEST_RUN_KEY = f"{_MANIFEST_PREFIX}/latest.json"

_LOCK = threading.Lock()
_RUN: dict = {
    "thread": None,
    "id": None,
    "state": "idle",   # idle | running | completed | failed
    "grounded": False,
    "artifacts": [],
    "error": None,
    "updated_at": None,
    "accepted_at": None,
    "running_at": None,
    "completed_at": None,
    "failed_at": None,
}


def _run_crew() -> None:
    """Run the crew to completion.

    The crew import is deferred to call time on purpose: it pulls the
    full crew dependency closure (crewai, crewai_tools), which is present
    in the deployed image but not in the build/test environment. This is
    also the seam the offline test substitutes — patching this function
    needs no crew import at all.
    """
    from compliance_assistant.main import run

    run()


def _s3_client():
    """Isolated so the offline test can substitute a fake client."""
    import boto3

    return boto3.client("s3")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _manifest_key(run_id: str) -> str:
    return f"{_MANIFEST_PREFIX}/{run_id}/manifest.json"


def _snapshot_unlocked() -> dict:
    return {
        "run_id": _RUN["id"],
        "state": _RUN["state"],
        "grounded": _RUN["grounded"],
        "artifacts": list(_RUN["artifacts"]),
        "error": _RUN["error"],
        "updated_at": _RUN["updated_at"],
        "accepted_at": _RUN["accepted_at"],
        "running_at": _RUN["running_at"],
        "completed_at": _RUN["completed_at"],
        "failed_at": _RUN["failed_at"],
    }


def _persist_status_unlocked() -> dict:
    """Persist the current run snapshot as the durable manifest."""
    bucket = os.environ["REPORT_BUCKET"]
    run_id = _RUN["id"]
    if not run_id:
        raise RuntimeError("cannot persist a manifest without a run id")
    client = _s3_client()
    manifest = _snapshot_unlocked()
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
    client.put_object(
        Bucket=bucket,
        Key=_manifest_key(run_id),
        Body=payload,
        ContentType="application/json",
    )
    client.put_object(
        Bucket=bucket,
        Key=_LATEST_RUN_KEY,
        Body=json.dumps({"run_id": run_id}, ensure_ascii=False).encode(),
        ContentType="application/json",
    )
    return manifest


def _load_json(bucket: str, key: str) -> dict | None:
    client = _s3_client()
    try:
        resp = client.get_object(Bucket=bucket, Key=key)
    except Exception:
        return None
    body = resp.get("Body")
    if body is None:
        return None
    return json.loads(body.read().decode("utf-8"))


def _load_latest_manifest() -> dict | None:
    bucket = os.environ.get("REPORT_BUCKET")
    if not bucket:
        return None
    latest = _load_json(bucket, _LATEST_RUN_KEY)
    if not latest or not latest.get("run_id"):
        return None
    manifest = _load_json(bucket, _manifest_key(latest["run_id"]))
    if not isinstance(manifest, dict):
        return None
    return manifest


def _set_state_unlocked(state: str, *, grounded: bool | None = None,
                        artifacts: list[str] | None = None,
                        error: str | None = None) -> dict:
    now = _now()
    _RUN["state"] = state
    _RUN["updated_at"] = now
    if grounded is not None:
        _RUN["grounded"] = grounded
    if artifacts is not None:
        _RUN["artifacts"] = artifacts
    _RUN["error"] = error
    if state == "accepted":
        _RUN["accepted_at"] = now
        _RUN["running_at"] = None
        _RUN["completed_at"] = None
        _RUN["failed_at"] = None
    elif state == "running":
        _RUN["running_at"] = now
    elif state == "completed":
        _RUN["completed_at"] = now
        _RUN["failed_at"] = None
    elif state == "failed":
        _RUN["failed_at"] = now
        _RUN["completed_at"] = None
    return _persist_status_unlocked()


def _upload_artifacts(run_id: str) -> list[str]:
    """Upload every produced output/*.md to the report bucket.

    Absence of the report artifact is valid (no grounded findings); we
    upload whatever exists. Missing REPORT_BUCKET is a real
    misconfiguration and is allowed to raise.
    """
    bucket = os.environ["REPORT_BUCKET"]
    client = _s3_client()
    keys: list[str] = []
    for path in sorted(glob.glob(_OUTPUT_GLOB)):
        key = f"reports/{run_id}/{os.path.basename(path)}"
        client.upload_file(path, bucket, key)
        keys.append(key)
    return keys


def _mark_failed(run_id: str, exc: Exception) -> None:
    # Caller sees a stable class+message category, not repr() (which
    # can carry ARNs / request ids / boto3 error bodies). The full
    # detail goes to the container log (CloudWatch) for the operator.
    print(f"run {run_id} failed: {exc!r}", flush=True)
    error = f"{type(exc).__name__}: {exc}"
    with _LOCK:
        _RUN["id"] = run_id
        _RUN["thread"] = threading.current_thread()
        _RUN["error"] = error
        _RUN["state"] = "failed"
        _RUN["grounded"] = False
        _RUN["completed_at"] = None
        _RUN["failed_at"] = _now()
        _RUN["updated_at"] = _RUN["failed_at"]
        try:
            _persist_status_unlocked()
        except Exception as persist_exc:
            print(
                f"run {run_id} failed and manifest persistence also failed: "
                f"{persist_exc!r}",
                flush=True,
            )


def _do_run(run_id: str) -> None:
    """Background worker: run the crew to completion, then upload."""
    try:
        with _LOCK:
            _set_state_unlocked("running", grounded=False, artifacts=[], error=None)
        _run_crew()
        artifacts = _upload_artifacts(run_id)
        with _LOCK:
            _set_state_unlocked(
                "completed",
                artifacts=artifacts,
                grounded=os.path.exists(_REPORT_ARTIFACT),
                error=None,
            )
    except Exception as exc:  # surfaced via /status and /ping, never hidden
        _mark_failed(run_id, exc)


def _running_unlocked() -> bool:
    """Authoritative busy state: the LOCKED run state, not thread
    liveness. Thread liveness has a pre-start gap (the thread is not yet
    alive between state=running and Thread.start()), which would let a
    second invocation through and report Healthy for an accepted run.
    Caller must hold _LOCK."""
    return _RUN["state"] in {"accepted", "running"}


def _busy() -> bool:
    with _LOCK:
        return _running_unlocked()


def ping() -> dict:
    """AgentCore health: HealthyBusy keeps the session alive during a run."""
    return {"status": "HealthyBusy" if _busy() else "Healthy"}


def status() -> dict:
    with _LOCK:
        if _RUN["id"] is not None or _RUN["state"] != "idle":
            return _snapshot_unlocked()
    manifest = _load_latest_manifest()
    if manifest is not None:
        return manifest
    return _snapshot_unlocked()


def start_invocation() -> tuple[int, dict]:
    """Start a run if none is in flight. Returns (http_status, body)."""
    with _LOCK:
        if _running_unlocked():
            return 409, {"error": "a run is already in flight",
                         "run_id": _RUN["id"]}
        run_id = str(uuid.uuid4())
        thread = threading.Thread(
            target=_do_run, args=(run_id,), daemon=True
        )
        _RUN.update(
            id=run_id, thread=thread, state="idle", grounded=False,
            artifacts=[], error=None, updated_at=None, accepted_at=None,
            running_at=None, completed_at=None, failed_at=None,
        )
        try:
            _set_state_unlocked(
                "accepted", grounded=False, artifacts=[], error=None
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            _RUN["thread"] = None
            _RUN["state"] = "failed"
            _RUN["error"] = error
            _RUN["grounded"] = False
            _RUN["updated_at"] = _now()
            _RUN["failed_at"] = _RUN["updated_at"]
            return 500, {"error": error, "run_id": run_id}
        # Start UNDER the lock: the accepted state is already durable
        # and the thread is launched atomically with it, so there is no
        # pre-start window where a second invocation slips past the
        # guard or /ping reports Healthy for an accepted run.
        # Thread.start() returns immediately; _do_run does not take
        # _LOCK until its terminal state write and never holds it
        # during the crew run, so the lock hold here is microseconds.
        thread.start()
    return 202, {"run_id": run_id, "state": "running"}


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - http.server contract
        if self.path == "/ping":
            self._send(200, ping())
        elif self.path == "/status":
            self._send(200, status())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - http.server contract
        if self.path == "/invocations":
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)  # payload accepted, not required
            code, body = start_invocation()
            self._send(code, body)
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *_args) -> None:  # keep stdout clean for logs
        pass


def serve() -> None:
    ThreadingHTTPServer(("0.0.0.0", _PORT), _Handler).serve_forever()


if __name__ == "__main__":
    serve()
