from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from boto3.dynamodb.conditions import ConditionExpressionBuilder

from askbrieves import storage

NOW = datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc)


@pytest.fixture
def table(monkeypatch):
    store = Mock()
    monkeypatch.setattr(storage, "table", lambda: store)
    return store


def test_quota_uses_one_atomic_conditional_update(table, monkeypatch):
    monkeypatch.setenv("DAILY_REQUEST_LIMIT", "100")
    storage.claim_daily_request(NOW)
    kwargs = table.update_item.call_args.kwargs
    assert kwargs["Key"] == {"pk": "quota#2026-10-25", "sk": "daily"}
    assert "ADD request_count :one" in kwargs["UpdateExpression"]
    built = ConditionExpressionBuilder().build_expression(kwargs["ConditionExpression"])
    assert "attribute_not_exists" in built.condition_expression
    assert " OR " in built.condition_expression and " < " in built.condition_expression
    assert 100 in built.attribute_value_placeholders.values()
    assert kwargs["ExpressionAttributeValues"][":one"] == 1
    assert kwargs["ExpressionAttributeValues"][":expires"] > NOW.timestamp()


def test_quota_rejection_becomes_specific_limit_exception(table):
    class ConditionalCheckFailed(Exception):
        pass
    table.meta.client.exceptions.ConditionalCheckFailedException = ConditionalCheckFailed
    table.update_item.side_effect = ConditionalCheckFailed()
    with pytest.raises(storage.DailyLimitExceeded):
        storage.claim_daily_request(NOW)


def test_history_preserves_question_and_result_with_bounded_retention(table, monkeypatch):
    monkeypatch.setenv("HISTORY_DAYS", "30")
    item = storage.start_history("request-1", "10-year Treasury yield?", NOW)
    assert item["status"] == "pending"
    assert item["expires_at"] == int(NOW.timestamp()) + 30 * 86400
    assert item["sk"].endswith("#request-1")
    storage.finish_history(item, {"status": "answered", "answer": "Source-backed answer"})
    stored = table.put_item.call_args.kwargs["Item"]
    assert stored["question"] == item["question"] and stored["status"] == "answered"
    assert stored["expires_at"] == item["expires_at"]


def test_history_query_uses_retention_key_range_and_never_scans(table, monkeypatch):
    monkeypatch.setenv("HISTORY_DAYS", "30")
    table.query.return_value = {"Items": [{"pk": "history", "sk": "sort", "expires_at": 20,
                                          "question": "10-year yield?", "request_id": "abc"}]}
    result = storage.recent_history(NOW)
    assert result == [{"question": "10-year yield?", "request_id": "abc"}]
    kwargs = table.query.call_args.kwargs
    assert kwargs["Limit"] == 20 and kwargs["ScanIndexForward"] is False
    assert kwargs["ConsistentRead"] is True
    built = ConditionExpressionBuilder().build_expression(kwargs["KeyConditionExpression"], is_key_condition=True)
    assert " >= " in built.condition_expression
    assert "2026-09-25T16:30:00+00:00" in built.attribute_value_placeholders.values()
    table.scan.assert_not_called()


@pytest.mark.parametrize("provided,expected", [("o" * 40, "owner"), ("reviewer-demo", "reviewer"), ("wrong-access", None)])
def test_owner_and_reviewer_credentials_have_distinct_identity(monkeypatch, provided, expected):
    document = {"token": "o" * 40, "reviewer_token": "reviewer-demo", "reviewer_expires_at": int(NOW.timestamp()) + 60}
    monkeypatch.setenv("API_SECRET_ARN", "access-secret")
    monkeypatch.setattr(storage, "_secret_document", lambda arn: document)
    assert storage.authenticate_token(provided, NOW) == expected


@pytest.mark.parametrize("expires", [None, True, "2099", int(NOW.timestamp()), int(NOW.timestamp()) - 1])
def test_expired_or_invalid_reviewer_expiry_cannot_authenticate(monkeypatch, expires):
    monkeypatch.setenv("API_SECRET_ARN", "access-secret")
    monkeypatch.setattr(storage, "_secret_document", lambda arn: {"token": "o" * 40, "reviewer_token": "reviewer-demo", "reviewer_expires_at": expires})
    assert storage.authenticate_token("reviewer-demo", NOW) is None
    assert storage.authenticate_token("o" * 40, NOW) == "owner"


def test_legacy_owner_secret_stays_usable_without_reviewer_fields(monkeypatch):
    monkeypatch.setenv("API_SECRET_ARN", "access-secret")
    monkeypatch.setattr(storage, "_secret_document", lambda arn: {"token": "o" * 40})
    assert storage.authenticate_token("o" * 40, NOW) == "owner"
    assert storage.authenticate_token("reviewer-demo", NOW) is None


def test_reviewer_history_uses_separate_partition_for_writes_and_reads(table):
    owner = storage.start_history("owner-1", "Owner question", NOW)
    reviewer = storage.start_history("reviewer-1", "Reviewer question", NOW, principal="reviewer")
    assert owner["pk"] == "history" and reviewer["pk"] == "history#reviewer"
    table.query.return_value = {"Items": []}
    storage.recent_history(NOW, principal="reviewer")
    built = ConditionExpressionBuilder().build_expression(table.query.call_args.kwargs["KeyConditionExpression"], is_key_condition=True)
    assert "history#reviewer" in built.attribute_value_placeholders.values()
    assert "history" not in built.attribute_value_placeholders.values()


def test_history_audience_is_an_enum_not_client_input(table):
    with pytest.raises(ValueError, match="Unknown history audience"):
        storage.recent_history(NOW, principal="history")
    table.query.assert_not_called()
