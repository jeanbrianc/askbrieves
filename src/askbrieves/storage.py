"""Small AWS adapter. Secrets stay in runtime memory; history never enters prompts."""

import json
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


def secret(arn, field):
    """Application runtime retrieval; never run this helper to display a secret."""
    now = time.monotonic()
    cached = _secrets.get(arn)
    if cached is None or now - cached[0] >= 60:
        value = json.loads(secrets_client().get_secret_value(SecretId=arn)["SecretString"])
        _secrets[arn] = (now, value)
    value = _secrets[arn][1].get(field)
    if not isinstance(value, str) or len(value) < 20:
        raise ValueError("Secret is missing or invalid")
    return value


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


def start_history(request_id, question, now):
    item = {"pk": "history", "sk": now.isoformat() + "#" + request_id,
            "request_id": request_id, "created_at": now.isoformat(), "question": question,
            "status": "pending", "expires_at": int(now.timestamp()) + int(os.getenv("HISTORY_DAYS", "30")) * 86400}
    table().put_item(Item=item, ConditionExpression=Attr("pk").not_exists())
    return item


def finish_history(item, result):
    completed = dict(item, **result)
    table().put_item(Item=completed, ConditionExpression=Attr("pk").exists())


def recent_history(now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = (now.timestamp() - int(os.getenv("HISTORY_DAYS", "30")) * 86400)
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
    result = table().query(KeyConditionExpression=Key("pk").eq("history") & Key("sk").gte(cutoff_iso),
                           Limit=20, ScanIndexForward=False, ConsistentRead=True)
    return [{k: v for k, v in item.items() if k not in ("pk", "sk", "expires_at")}
            for item in result.get("Items", [])]
