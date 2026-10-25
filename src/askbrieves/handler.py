"""API Gateway HTTP API entry point with a deliberately small trust boundary."""

import base64
import binascii
import hmac
import json
import os
from pathlib import Path
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from askbrieves import storage
from askbrieves.planner import POLICY_VERSION, PlannerUnavailable, plan_question
from askbrieves.rates import RatesNotPublished, RatesUnavailable, fetch_yields

DECLINED = ("I can help with current or historical U.S. Treasury yields. "
            "Include a maturity and a full date, or say latest. "
            "I cannot provide forecasts, investment advice, secrets, or unrelated answers.")
SECRET_PATTERN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b")
PUBLIC_ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                 "/brand.png": ("brand.png", "image/png")}


class InvalidQuestion(ValueError):
    pass


def response(status, body, request_id, text=False):
    return {"statusCode": status, "headers": {
        "content-type": "text/plain; charset=utf-8" if text else "application/json",
        "cache-control": "no-store", "x-content-type-options": "nosniff",
        "strict-transport-security": "max-age=31536000", "x-request-id": request_id,
        "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        "referrer-policy": "no-referrer", "x-frame-options": "DENY"},
        "body": body if text else json.dumps(body, default=str)}


def read_question(event):
    if event.get("queryStringParameters"):
        raise InvalidQuestion("Query parameters are not supported")
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    if headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise InvalidQuestion("Use Content-Type: application/json")
    body = event.get("body") or ""
    if not isinstance(body, str) or len(body) > 6000:
        raise InvalidQuestion("Request body is too large")
    try:
        raw = base64.b64decode(body, validate=True) if event.get("isBase64Encoded") else body.encode()
        if len(raw) > 4096:
            raise ValueError("Request body is too large")
        parsed = json.loads(raw)
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise InvalidQuestion("Invalid JSON body") from exc
    if not isinstance(parsed, dict) or set(parsed) != {"question"}:
        raise InvalidQuestion("Provide exactly one field: question")
    question = parsed["question"]
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
        raise InvalidQuestion("Question must be between 1 and 500 characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in question):
        raise InvalidQuestion("Control characters are not supported")
    if SECRET_PATTERN.search(question):
        raise InvalidQuestion("Do not submit credentials or personal information")
    return question.strip()


def answer_from_evidence(evidence, maturities):
    observations = evidence.get("observations", [evidence])
    labels = [f"{m[:-1]}-{'month' if m.endswith('m') else 'year'}" for m in maturities]
    paragraphs = []
    for observation in observations:
        clauses = [f"the {label} yield was {observation['rates'][m]}%" for m, label in zip(maturities, labels)]
        paragraph = f"As of {observation['as_of']}, " + " and ".join(clauses) + "."
        if len(maturities) == 2:
            spread = (Decimal(observation["rates"][maturities[1]]) - Decimal(observation["rates"][maturities[0]])) * 100
            paragraph += f" The {labels[1]} minus {labels[0]} spread was {spread:+.0f} basis points."
        paragraphs.append(paragraph)
    if len(observations) == 2:
        first, second = observations
        changes = []
        for maturity, label in zip(maturities, labels):
            change = (Decimal(second["rates"][maturity]) - Decimal(first["rates"][maturity])) * 100
            changes.append(f"the {label} yield changed by {change:+.0f} basis points")
        paragraphs.append(f"From {first['as_of']} to {second['as_of']}, " + " and ".join(changes) + ".")
    sources = list(dict.fromkeys(observation["source_url"] for observation in observations))
    citation = ("Source: " if len(sources) == 1 else "Sources: ") + " | ".join(sources)
    return " ".join(paragraphs) + " These are daily U.S. Treasury par yields, not live quotes or deposit APYs. " + citation


def process_question(question, request_id, now):
    storage.claim_daily_request(now)
    item = storage.start_history(request_id, question, now)
    try:
        plan = plan_question(question, storage.secret(os.environ["OPENAI_SECRET_ARN"], "api_key"))
        if plan["action"] == "decline":
            result = {"status": "declined", "answer": DECLINED, "reason": plan["reason"]}
        else:
            evidence = fetch_yields(plan["maturities"], dates=plan["dates"])
            result = {"status": "answered", "answer": answer_from_evidence(evidence, plan["maturities"]),
                      "evidence": evidence}
        code = 200
    except RatesNotPublished as exc:
        result = {"status": "no_data", "answer": str(exc) + " Please choose another date or maturity."}
        code = 200
    except (PlannerUnavailable, RatesUnavailable):
        result = {"status": "unavailable", "answer": "I could not verify the requested Treasury data safely. Please retry later."}
        code = 503
    result["policy_version"] = POLICY_VERSION
    # A successful API response requires a durable history record. Failure propagates.
    storage.finish_history(item, result)
    return code, dict(result, request_id=request_id)


def lambda_handler(event, context):
    started = time.monotonic()
    request_id = str(uuid.uuid4())
    status = 503
    outcome = "unavailable"
    try:
        method = event.get("requestContext", {}).get("http", {}).get("method", "")
        path = event.get("rawPath", "")
        if method == "GET" and path in PUBLIC_ASSETS:
            filename, content_type = PUBLIC_ASSETS[path]
            asset = Path(__file__).parent / "web" / filename
            body = base64.b64encode(asset.read_bytes()).decode() if content_type == "image/png" else asset.read_text(encoding="utf-8")
            status, outcome = 200, "web_asset"
            result = response(status, body, request_id, text=True)
            result["headers"]["content-type"] = content_type
            if content_type == "image/png":
                result["isBase64Encoded"] = True
            return result
        if method == "GET" and path == "/health":
            status, outcome = 200, "healthy"
            return response(status, "AskBrieves is running. POST /questions and GET /history require a bearer token.\n", request_id, text=True)
        if (method, path) not in (("POST", "/questions"), ("GET", "/history")):
            status, outcome = 404, "not_found"
            return response(status, {"error": "Not found"}, request_id)
        headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
        provided = headers.get("authorization", "")
        if not provided.startswith("Bearer ") or len(provided) > 1024:
            status, outcome = 401, "unauthorized"
            return response(status, {"error": "Valid bearer token required"}, request_id)
        expected = storage.secret(os.environ["API_SECRET_ARN"], "token")
        if not hmac.compare_digest(provided[7:].encode(), expected.encode()):
            status, outcome = 401, "unauthorized"
            return response(status, {"error": "Valid bearer token required"}, request_id)
        if method == "GET":
            status, outcome = 200, "history"
            return response(status, {"items": storage.recent_history(), "limit": 20}, request_id)
        question = read_question(event)
        status, body = process_question(question, request_id, datetime.now(timezone.utc))
        outcome = body["status"]
        return response(status, body, request_id)
    except InvalidQuestion:
        # Only input-validation messages are returned; secret/config errors stay private.
        status, outcome = 400, "invalid_request"
        return response(status, {"error": "Invalid request. Use JSON with one question of 1-500 characters; do not include secrets."}, request_id)
    except storage.DailyLimitExceeded:
        status, outcome = 429, "daily_limit"
        return response(status, {"error": "Daily question limit reached. Resets at 00:00 UTC."}, request_id)
    except Exception:
        # Final boundary intentionally suppresses private provider/AWS error payloads.
        status, outcome = 503, "unavailable"
        return response(status, {"error": "Service temporarily unavailable", "request_id": request_id}, request_id)
    finally:
        print(json.dumps({"event": "request_complete", "request_id": request_id,
                          "status": status, "outcome": outcome,
                          "duration_ms": round((time.monotonic() - started) * 1000)}))
