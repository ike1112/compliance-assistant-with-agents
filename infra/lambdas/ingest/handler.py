"""Re-index the Knowledge Base when a regulatory PDF lands in S3.

Triggered two ways: an S3 ObjectCreated notification (a new or
replaced PDF), or a manual invoke with no/`{"resync": true}` event to
force a full re-ingest. Both just start one ingestion job; Bedrock
handles the incremental sync from there.
"""
import json
import os

import boto3

_bedrock = boto3.client("bedrock-agent")


def _event_context(event):
    records = event.get("Records") or []
    if records:
        s3 = (records[0].get("s3") or {})
        return {
            "eventType": "s3-object-created",
            "bucket": ((s3.get("bucket") or {}).get("name")),
            "key": ((s3.get("object") or {}).get("key")),
        }
    if event.get("resync"):
        return {"eventType": "manual-resync", "bucket": None, "key": None}
    return {"eventType": "unknown", "bucket": None, "key": None}


def _log(payload):
    print(json.dumps(payload, sort_keys=True), flush=True)


def handler(event, _context):
    kb_id = os.environ["KB_ID"]
    data_source_id = os.environ["DATA_SOURCE_ID"]
    details = _event_context(event or {})
    _log({
        "status": "starting",
        "knowledgeBaseId": kb_id,
        "dataSourceId": data_source_id,
        **details,
    })
    try:
        resp = _bedrock.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=data_source_id,
        )
    except Exception as exc:
        _log({
            "status": "failed",
            "knowledgeBaseId": kb_id,
            "dataSourceId": data_source_id,
            "error": f"{type(exc).__name__}: {exc}",
            **details,
        })
        raise
    job = resp["ingestionJob"]
    _log({
        "status": job["status"],
        "knowledgeBaseId": kb_id,
        "dataSourceId": data_source_id,
        "ingestionJobId": job["ingestionJobId"],
        **details,
    })
    return {"ingestionJobId": job["ingestionJobId"], "status": job["status"]}
