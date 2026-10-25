from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from boto3.dynamodb.conditions import ConditionExpressionBuilder

from askbrieves import storage

NOW = datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc)
WINDOW_END = int((NOW + timedelta(days=7)).timestamp())


@pytest.fixture
def quota_config(monkeypatch):
    monkeypatch.setenv("REQUEST_LIMIT", "1000")
    monkeypatch.setenv("REVIEW_WINDOW_ENDS_AT", str(WINDOW_END))


@pytest.fixture
def table(monkeypatch):
    store = Mock()
    monkeypatch.setattr(storage, "table", lambda: store)
    return store


def test_quota_uses_one_atomic_conditional_update(table, quota_config):
    storage.claim_request(NOW)
    kwargs = table.update_item.call_args.kwargs
    assert kwargs["Key"] == {"pk": "quota#review#" + str(WINDOW_END), "sk": "total"}
    assert "ADD request_count :one" in kwargs["UpdateExpression"]
    assert "SET request_count" not in kwargs["UpdateExpression"]
    built = ConditionExpressionBuilder().build_expression(kwargs["ConditionExpression"])
    assert "attribute_not_exists" in built.condition_expression
    assert " OR " in built.condition_expression and " < " in built.condition_expression
    assert 1000 in built.attribute_value_placeholders.values()
    assert kwargs["ExpressionAttributeValues"][":one"] == 1
    assert kwargs["ExpressionAttributeValues"][":expires"] == WINDOW_END + 172800
    assert kwargs["ExpressionAttributeValues"][":end"] == WINDOW_END
    assert kwargs["ExpressionAttributeValues"][":limit"] == 1000


def test_quota_rejection_becomes_specific_limit_exception(table, quota_config):
    class ConditionalCheckFailed(Exception):
        pass
    table.meta.client.exceptions.ConditionalCheckFailedException = ConditionalCheckFailed
    table.update_item.side_effect = ConditionalCheckFailed()
    with pytest.raises(storage.RequestLimitExceeded):
        storage.claim_request(NOW)


def test_quota_storage_failure_is_not_reported_as_exhaustion(table, quota_config):
    class ConditionalCheckFailed(Exception):
        pass
    table.meta.client.exceptions.ConditionalCheckFailedException = ConditionalCheckFailed
    table.update_item.side_effect = RuntimeError("DynamoDB unavailable")
    with pytest.raises(RuntimeError, match="DynamoDB unavailable"):
        storage.claim_request(NOW)


def test_quota_does_not_reset_at_midnight_or_within_the_review_window(table, quota_config):
    for moment in (NOW, NOW.replace(hour=23, minute=59, second=59),
                   (NOW + timedelta(days=1)).replace(hour=0, minute=0),
                   NOW + timedelta(days=6, hours=23)):
        storage.claim_request(moment)
    calls = [call.kwargs for call in table.update_item.call_args_list]
    assert len(calls) == 4
    assert all(call["Key"] == calls[0]["Key"] for call in calls)
    assert all(call["ExpressionAttributeValues"][":expires"] == WINDOW_END + 172800
               for call in calls)


@pytest.mark.parametrize("offset", [-1, 7 * 86400, 7 * 86400 + 1])
def test_inactive_window_rejects_before_accessing_aws(table, quota_config, monkeypatch, offset):
    access = Mock(side_effect=AssertionError("Closed window must not access AWS"))
    monkeypatch.setattr(storage, "table", access)
    with pytest.raises(storage.ReviewWindowClosed):
        storage.claim_request(NOW + timedelta(seconds=offset))
    access.assert_not_called()
    table.update_item.assert_not_called()


@pytest.mark.parametrize("offset", [0, 7 * 86400 - 0.001])
def test_window_start_is_inclusive_and_end_is_exclusive(table, quota_config, offset):
    storage.claim_request(NOW + timedelta(seconds=offset))
    table.update_item.assert_called_once()


def test_equivalent_aware_timezones_use_the_same_window_key(table, quota_config):
    storage.claim_request(NOW)
    storage.claim_request(NOW.astimezone(timezone(timedelta(hours=-4))))
    assert table.update_item.call_args_list[0].kwargs["Key"] == table.update_item.call_args_list[1].kwargs["Key"]


@pytest.mark.parametrize("limit", ["1", "1000"])
def test_supported_request_limits_remain_atomic(table, quota_config, monkeypatch, limit):
    monkeypatch.setenv("REQUEST_LIMIT", limit)
    storage.claim_request(NOW)
    built = ConditionExpressionBuilder().build_expression(table.update_item.call_args.kwargs["ConditionExpression"])
    assert int(limit) in built.attribute_value_placeholders.values()
    assert table.update_item.call_args.kwargs["ExpressionAttributeValues"][":limit"] == int(limit)


def test_default_limit_is_one_thousand_without_a_daily_setting(table, quota_config, monkeypatch):
    monkeypatch.delenv("REQUEST_LIMIT")
    monkeypatch.setenv("DAILY_REQUEST_LIMIT", "1")
    storage.claim_request(NOW)
    assert table.update_item.call_args.kwargs["ExpressionAttributeValues"][":limit"] == 1000


def test_limit_change_preserves_the_window_counter_key(table, quota_config, monkeypatch):
    storage.claim_request(NOW)
    original = table.update_item.call_args.kwargs
    monkeypatch.setenv("REQUEST_LIMIT", "500")
    storage.claim_request(NOW + timedelta(days=1))
    revised = table.update_item.call_args.kwargs
    assert original["Key"] == revised["Key"]
    assert revised["ExpressionAttributeValues"][":limit"] == 500
    assert "ADD request_count :one" in revised["UpdateExpression"]


def test_explicit_new_window_uses_a_distinct_counter_without_deleting_old_state(table, quota_config, monkeypatch):
    storage.claim_request(NOW)
    original = table.update_item.call_args.kwargs["Key"]
    monkeypatch.setenv("REVIEW_WINDOW_ENDS_AT", str(WINDOW_END + 86400))
    storage.claim_request(NOW + timedelta(days=1))
    assert table.update_item.call_args.kwargs["Key"] != original
    table.delete_item.assert_not_called()


@pytest.mark.parametrize("name,value", [
    ("REQUEST_LIMIT", ""), ("REQUEST_LIMIT", "0"), ("REQUEST_LIMIT", "-1"),
    ("REQUEST_LIMIT", "1001"), ("REQUEST_LIMIT", "1.5"), ("REQUEST_LIMIT", "+1"),
    ("REQUEST_LIMIT", " 1000"), ("REQUEST_LIMIT", "1000 "),
    ("REQUEST_LIMIT", "True"), ("REQUEST_LIMIT", "1_000"),
    ("REQUEST_LIMIT", "١٠٠٠"),
    ("REVIEW_WINDOW_ENDS_AT", None), ("REVIEW_WINDOW_ENDS_AT", ""),
    ("REVIEW_WINDOW_ENDS_AT", "0"), ("REVIEW_WINDOW_ENDS_AT", "-1"),
    ("REVIEW_WINDOW_ENDS_AT", "4102444801"), ("REVIEW_WINDOW_ENDS_AT", "1.5"),
    ("REVIEW_WINDOW_ENDS_AT", "+1793550600"),
    ("REVIEW_WINDOW_ENDS_AT", "1793550600 "),
    ("REVIEW_WINDOW_ENDS_AT", "1" * 100),
])
def test_invalid_quota_configuration_fails_closed_without_aws(table, quota_config, monkeypatch, name, value):
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    access = Mock(side_effect=AssertionError("Invalid configuration must not access AWS"))
    monkeypatch.setattr(storage, "table", access)
    with pytest.raises(ValueError, match="Invalid review allowance configuration"):
        storage.claim_request(NOW)
    access.assert_not_called()
    table.update_item.assert_not_called()


def test_naive_timestamp_fails_closed_before_aws(table, quota_config):
    with pytest.raises(ValueError, match="aware timestamp"):
        storage.claim_request(NOW.replace(tzinfo=None))
    table.update_item.assert_not_called()


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
