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
