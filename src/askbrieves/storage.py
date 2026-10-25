"""Small AWS adapter. Secrets stay in runtime memory; history never enters prompts."""

import json
import hmac
import os
import time
from datetime import datetime, timezone
from functools import lru_cache

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config

CONFIG = Config(connect_timeout=1, read_timeout=2, retries={"total_max_attempts": 1, "mode": "standard"})


class DailyLimitExceeded(Exception):
    pass


@lru_cache(maxsize=1)
def table():
    return boto3.resource("dynamodb", config=CONFIG).Table(os.environ["TABLE_NAME"])


@lru_cache(maxsize=1)
def secrets_client():
    return boto3.client("secretsmanager", config=CONFIG)


_secrets = {}


def _secret_document(arn):
    """Resolve secret data only inside application/runtime memory."""
    now = time.monotonic()
    cached = _secrets.get(arn)
    if cached is None or now - cached[0] >= 60:
        value = json.loads(secrets_client().get_secret_value(SecretId=arn)["SecretString"])
        if not isinstance(value, dict):
            raise ValueError("Secret must contain an object")
        _secrets[arn] = (now, value)
    return _secrets[arn][1]


def secret(arn, field):
    """Application runtime retrieval; never run this helper to display a secret."""
    value = _secret_document(arn).get(field)
    if not isinstance(value, str) or len(value) < 20:
        raise ValueError("Secret is missing or invalid")
    return value


def authenticate_token(provided, now=None):
    """Map a credential to a fixed audience; a reviewer never becomes an owner."""
    document = _secret_document(os.environ["API_SECRET_ARN"])
    owner = document.get("token")
    if not isinstance(owner, str) or not 20 <= len(owner) <= 512:
        raise ValueError("Owner credential configuration is invalid")
    owner_matches = hmac.compare_digest(provided.encode(), owner.encode())
    reviewer = document.get("reviewer_token")
    expires = document.get("reviewer_expires_at")
    reviewer_configured = isinstance(reviewer, str) and 12 <= len(reviewer) <= 512
    reviewer_matches = hmac.compare_digest(provided.encode(), (reviewer if reviewer_configured else "").encode())
    timestamp = (now or datetime.now(timezone.utc)).timestamp()
    reviewer_active = isinstance(expires, int) and not isinstance(expires, bool) and timestamp < expires
    if owner_matches:
        return "owner"
    if reviewer_configured and reviewer_matches and reviewer_active:
        return "reviewer"
    return None


def _history_partition(principal):
    if principal not in ("owner", "reviewer"):
        raise ValueError("Unknown history audience")
    return "history" if principal == "owner" else "history#reviewer"


def claim_daily_request(now):
    store = table()
    try:
        store.update_item(
            Key={"pk": "quota#" + now.date().isoformat(), "sk": "daily"},
            UpdateExpression="SET expires_at = :expires ADD request_count :one",
            ExpressionAttributeValues={":one": 1, ":expires": int(now.timestamp()) + 172800},
            ConditionExpression=Attr("request_count").not_exists() | Attr("request_count").lt(int(os.getenv("DAILY_REQUEST_LIMIT", "100"))))
    except store.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise DailyLimitExceeded() from exc


def start_history(request_id, question, now, principal="owner"):
    item = {"pk": _history_partition(principal), "sk": now.isoformat() + "#" + request_id,
            "request_id": request_id, "created_at": now.isoformat(), "question": question,
            "principal": principal, "status": "pending", "expires_at": int(now.timestamp()) + int(os.getenv("HISTORY_DAYS", "30")) * 86400}
    table().put_item(Item=item, ConditionExpression=Attr("pk").not_exists())
    return item


def finish_history(item, result):
    completed = dict(item, **result)
    table().put_item(Item=completed, ConditionExpression=Attr("pk").exists())


def recent_history(now=None, principal="owner"):
    now = now or datetime.now(timezone.utc)
    cutoff = (now.timestamp() - int(os.getenv("HISTORY_DAYS", "30")) * 86400)
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
    result = table().query(KeyConditionExpression=Key("pk").eq(_history_partition(principal)) & Key("sk").gte(cutoff_iso),
                           Limit=20, ScanIndexForward=False, ConsistentRead=True)
    return [{k: v for k, v in item.items() if k not in ("pk", "sk", "expires_at")}
            for item in result.get("Items", [])]
