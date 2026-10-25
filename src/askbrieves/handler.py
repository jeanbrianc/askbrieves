"""API Gateway HTTP API entry point with a deliberately small trust boundary."""

import base64
import binascii
import json
import os
from pathlib import Path
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from askbrieves import storage
from askbrieves.knowledge import curve_answer, explain_concept
from askbrieves.planner import POLICY_VERSION, PlannerUnavailable, plan_question, validated_context
from askbrieves.rates import RatesNotPublished, RatesUnavailable, fetch_yields, fetch_monthly_peak

DECLINE_MESSAGES = {
    "ambiguous": 'I need a maturity and date or month to resolve that. Try “10-year Treasury yield on October 24, 2025” or “peak 10-year yield in October 2025”. For follow-ups, first ask a complete question in this chat.',
    "unsupported": 'I support daily U.S. Treasury par yields, comparisons on up to two dates, and a monthly peak for one maturity. Try “peak 10-year Treasury yield in October 2025”. Period averages, forecasts and other rate products are not supported.',
    "unsafe": 'I cannot provide secrets, follow instructions to bypass safeguards, or give investment advice. I can show Treasury yields or explain concepts such as yield spreads.',
    "out_of_scope": 'I can help with U.S. Treasury yields and rate concepts. Try “What is a basis point?” or “What is the latest 10-year Treasury yield?”.',
}
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


def read_payload(event):
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
    if not isinstance(parsed, dict) or "question" not in parsed or set(parsed) - {"question", "context_id"}:
        raise InvalidQuestion("Provide question and optional context_id")
    context_id = parsed.get("context_id")
    if context_id is not None and (not isinstance(context_id, str) or not re.fullmatch(
            r"[0-9T:.+Z-]{20,40}#[0-9a-f-]{36}", context_id)):
        raise InvalidQuestion("Invalid context reference")
    question = parsed["question"]
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
        raise InvalidQuestion("Question must be between 1 and 500 characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in question):
        raise InvalidQuestion("Control characters are not supported")
    if SECRET_PATTERN.search(question):
        raise InvalidQuestion("Do not submit credentials or personal information")
    return question.strip(), context_id


def read_question(event):
    return read_payload(event)[0]


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


def peak_answer(evidence):
    maturity = evidence["maturity"]
    label = f"{maturity[:-1]}-{'month' if maturity.endswith('m') else 'year'}"
    period = evidence["month"] + (" (month to date)" if evidence["month_to_date"] else "")
    return (f"The peak published daily {label} Treasury par yield in {period} was "
            f"{evidence['peak_yield']}%, on {', '.join(evidence['peak_dates'])}. "
            f"Based on {evidence['observations_count']} published observations from "
            f"{evidence['first_observation']} through {evidence['last_observation']}; "
            f"{evidence['missing_maturity_count']} published rows lacked this maturity. "
            "This is a daily par-yield maximum, not an intraday high. Source: " + evidence["source_url"])


def process_question(question, request_id, now, principal="owner", context_id=None):
    context = None
    if context_id is not None:
        context = storage.conversation_context(context_id, principal, now)
        if context is not None:
            context = validated_context(context)
    storage.claim_request(now)
    item = storage.start_history(request_id, question, now, principal=principal)
    plan = None
    try:
        key = storage.secret(os.environ["OPENAI_SECRET_ARN"], "api_key")
        plan = plan_question(question, key, context=context) if context is not None else plan_question(question, key)
        if plan["action"] == "decline":
            result = {"status": "declined", "answer": DECLINE_MESSAGES[plan["reason"]], "reason": plan["reason"]}
        elif plan["action"] == "peak":
            evidence = fetch_monthly_peak(plan["maturity"], plan["month"])
            result = {"status": "answered", "answer": peak_answer(evidence), "evidence": evidence}
        elif plan["action"] == "explain":
            result = {"status": "answered", **explain_concept(plan["topic"])}
        elif plan["action"] == "curve":
            evidence = fetch_yields(["2y", "10y"], dates=plan["dates"])
            result = {"status": "answered", "answer": curve_answer(evidence), "evidence": evidence}
        else:
            evidence = fetch_yields(plan["maturities"], dates=plan["dates"])
            result = {"status": "answered", "answer": answer_from_evidence(evidence, plan["maturities"]),
                      "evidence": evidence}
        code = 200
    except RatesNotPublished as exc:
        result = {"status": "no_data", "answer": str(exc) + " Please choose another date or maturity. Weekends and holidays may have no observation; "
                  "I do not substitute a nearby day. Try an explicit business date, or ask for a monthly peak."}
        code = 200
    except (PlannerUnavailable, RatesUnavailable):
        result = {"status": "unavailable", "answer": "I could not verify the requested Treasury data safely. Please retry later."}
        code = 503
    if plan and plan["action"] != "decline" and result["status"] in ("answered", "no_data"):
        selection = dict(plan)
        evidence = result.get("evidence", {})
        if selection["action"] in ("lookup", "curve") and evidence:
            selection["dates"] = list(dict.fromkeys(o["as_of"] for o in evidence.get("observations", [evidence])))
        result["selection"] = selection
        if isinstance(item.get("sk"), str):
            result["context_id"] = item["sk"]
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
        principal = storage.authenticate_token(provided[7:])
        if principal is None:
            status, outcome = 401, "unauthorized"
            return response(status, {"error": "Valid bearer token required"}, request_id)
        if method == "GET":
            status, outcome = 200, "history"
            return response(status, {"items": storage.recent_history(principal=principal), "limit": 20}, request_id)
        question, context_id = read_payload(event)
        status, body = process_question(question, request_id, datetime.now(timezone.utc), principal=principal,
                                        context_id=context_id)
        outcome = body["status"]
        return response(status, body, request_id)
    except InvalidQuestion:
        # Only input-validation messages are returned; secret/config errors stay private.
        status, outcome = 400, "invalid_request"
        return response(status, {"error": "Invalid request. Use JSON with a question of 1-500 characters and optional context_id; do not include secrets."}, request_id)
    except storage.RequestLimitExceeded:
        status, outcome = 429, "review_limit_exceeded"
        return response(status, {"error": "Review request allowance exhausted. It does not reset daily.",
                                 "code": "review_limit_exceeded"}, request_id)
    except storage.ReviewWindowClosed:
        status, outcome = 403, "review_window_closed"
        return response(status, {"error": "The seven-day review window is not active.",
                                 "code": "review_window_closed"}, request_id)
    except Exception:
        # Final boundary intentionally suppresses private provider/AWS error payloads.
        status, outcome = 503, "unavailable"
        return response(status, {"error": "Service temporarily unavailable", "request_id": request_id}, request_id)
    finally:
        print(json.dumps({"event": "request_complete", "request_id": request_id,
                          "status": status, "outcome": outcome,
                          "duration_ms": round((time.monotonic() - started) * 1000)}))
