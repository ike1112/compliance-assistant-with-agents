"""Re-index the Knowledge Base when a regulatory PDF lands in S3.

Triggered two ways: an S3 ObjectCreated notification (a new or
replaced PDF), or a manual invoke with no/`{"resync": true}` event to
force a full re-ingest. Both just start one ingestion job; Bedrock
handles the incremental sync from there.
"""
import os

import boto3

_bedrock = boto3.client("bedrock-agent")


def handler(event, _context):
    resp = _bedrock.start_ingestion_job(
        knowledgeBaseId=os.environ["KB_ID"],
        dataSourceId=os.environ["DATA_SOURCE_ID"],
    )
    job = resp["ingestionJob"]
    return {"ingestionJobId": job["ingestionJobId"], "status": job["status"]}
