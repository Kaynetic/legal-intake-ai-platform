"""Sanitized excerpt — Bedrock (Claude) client that survives a hard RPM quota.

Context: a daily batch job fires dozens of Converse calls against an account
quota of ~10 requests/minute. A naive loop instantly trips ThrottlingException
and drops records to a manual-review fallback. Three layered defenses:

  1. PACE every call to stay under the quota (min interval between calls).
  2. RETRY throttles with full-jitter exponential backoff so residual 429s
     clear as the 1-minute window drains.
  3. ReservedConcurrentExecutions = 1 on the Lambda so two invocations can
     never overlap and double the request rate (module-global pacing state
     then persists correctly across warm invocations).

The interval is env-tunable: raise the quota via Service Quotas, then lower
MIN_INTERVAL_SEC to speed runs up. Post-fix: zero throttles in production.
"""
import os
import time
import random
import threading

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("REGION", "us-east-1")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")

_THROTTLE_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceQuotaExceededException",
}
_MAX_RETRIES = int(os.environ.get("BEDROCK_MAX_RETRIES", "6"))
_BACKOFF_CAP = 30.0
# 10 RPM quota -> 1 call / 6s; pace a touch slower (~8.5/min) for margin.
_MIN_INTERVAL = float(os.environ.get("MIN_INTERVAL_SEC", "7.0"))

_RATE_LOCK = threading.Lock()
_last_call_at = 0.0
_rt = None


def _client():
    global _rt
    if _rt is None:
        _rt = boto3.client("bedrock-runtime", region_name=REGION)
    return _rt


def _pace():
    """Block until at least _MIN_INTERVAL has elapsed since the last call,
    keeping the steady request rate under the account's per-minute quota."""
    global _last_call_at
    if _MIN_INTERVAL <= 0:
        return
    with _RATE_LOCK:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def converse_with_retry(record_id="", **kwargs):
    """Call bedrock-runtime.converse, paced, retrying only on throttling."""
    last = None
    for attempt in range(_MAX_RETRIES + 1):
        _pace()
        try:
            return _client().converse(**kwargs)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code not in _THROTTLE_CODES or attempt == _MAX_RETRIES:
                raise
            last = e
            # Full-jitter exponential backoff, floored at the pacing interval
            # so the 1-minute throttle window has time to drain, capped at 30s.
            delay = max(_MIN_INTERVAL, random.uniform(0, min(_BACKOFF_CAP, 2 ** attempt)))
            # Distinct, benign log marker: the retry usually succeeds, so the
            # log-scanning alarm is taught to ignore THIS line specifically.
            print(f"[status-engine] rate-limit backoff: record {record_id or '?'} "
                  f"waiting {delay:.1f}s, retry {attempt + 1}/{_MAX_RETRIES}")
            time.sleep(delay)
    raise last  # unreachable, but keeps intent explicit
