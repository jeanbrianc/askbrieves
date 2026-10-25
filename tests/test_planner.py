import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from askbrieves import planner

TODAY = date(2026, 10, 25)


def lookup_args(maturities=None, dates=None):
    return {"maturities": ["10y"] if maturities is None else maturities,
            "dates": ["latest"] if dates is None else dates}


def decision(name="lookup_treasury_yields", arguments=None, **changes):
    result = {"status": "completed", "output": [{"type": "function_call", "name": name,
              "arguments": json.dumps(arguments if arguments is not None else lookup_args())}]}
    return dict(result, **changes)


def test_constrained_latest_lookup_and_decline():
    assert planner.parse_plan(decision(), today=TODAY) == {
        "action": "lookup", "maturities": ["10y"], "dates": ["latest"]}
    assert planner.parse_plan(decision(arguments=lookup_args(["2y", "10y"])), today=TODAY)["maturities"] == ["2y", "10y"]
    assert planner.parse_plan(decision("decline_question", {"reason": "unsafe"}), today=TODAY) == {
        "action": "decline", "reason": "unsafe"}


@pytest.mark.parametrize("dates", [
    ["2025-10-23"], ["2025-10-23", "latest"], ["2025-10-23", "2024-10-23"],
    ["1990-01-02"], ["2026-10-25"], ["2024-02-29"],
])
def test_exact_dates_and_bounded_comparisons_are_preserved(dates):
    result = planner.parse_plan(decision(arguments=lookup_args(["2y", "10y"], dates)), today=TODAY)
    assert result == {"action": "lookup", "maturities": ["2y", "10y"], "dates": dates}
    assert planner.POLICY_VERSION == "treasury-dates-v2"


@pytest.mark.parametrize("dates", [
    [], ["latest", "latest"], ["2025-10-23", "2025-10-23"],
    ["2025-10-23", "2024-10-23", "latest"], ["2026-10-26"], ["2099-01-01"],
    ["1990-01-01"], ["1880-01-02"], ["2025-02-29"], ["2026-13-01"], ["2026-01-32"],
    ["2026-1-02"], ["20261023"], ["2026-10-23T00:00:00"], ["October 23, 2025"],
    ["2025-10"], ["2025"], ["2025-10-23\n"], ["Latest"], ["LATEST"],
    ["yesterday"], ["2025-10-23/2025-10-24"], [None], [10], [True], [{}],
    "latest", None, {"date": "2025-10-23"},
])
def test_dates_must_be_distinct_exact_supported_calendar_dates(dates):
    payload = decision(arguments={"maturities": ["10y"], "dates": dates})
    with pytest.raises(planner.PlannerUnavailable):
        planner.parse_plan(payload, today=TODAY)


def test_date_boundary_uses_the_supplied_new_york_today(monkeypatch):
    monkeypatch.setattr(planner, "_current_date", lambda: date(2026, 1, 1))
    assert planner.parse_plan(decision(arguments=lookup_args(dates=["2026-01-01"])))["dates"] == ["2026-01-01"]
    with pytest.raises(planner.PlannerUnavailable):
        planner.parse_plan(decision(arguments=lookup_args(dates=["2026-01-02"])))


@pytest.mark.parametrize("payload", [
    {}, None, [],
    decision(status="incomplete"),
    decision(name="read_secret"),
    decision(arguments={"maturities": ["10y"]}),
    decision(arguments={"dates": ["latest"]}),
    decision(arguments={"maturities": ["10y"], "dates": ["latest"], "url": "https://attacker.invalid"}),
    decision(arguments=lookup_args(["mortgage"])),
    decision(arguments=lookup_args(["10y", "10y"])),
    decision(arguments=lookup_args([])),
    decision(arguments=lookup_args(["1y", "2y", "10y"])),
    decision(arguments=lookup_args("10y")),
    decision(arguments=lookup_args([None])),
    decision("decline_question", {"reason": "anything"}),
    decision("decline_question", {"reason": "unsafe", "answer": "private content"}),
    decision(output=[{"type": "message", "content": "untrusted answer"}]),
    decision(output=[{"type": "function_call", "name": "lookup_treasury_yields", "arguments": "not json"}]),
    decision(output=decision()["output"] * 2),
    decision(output=decision()["output"] + [{"type": "message", "content": []}]),
])
def test_invalid_model_results_fail_closed(payload):
    with pytest.raises(planner.PlannerUnavailable):
        planner.parse_plan(payload, today=TODAY)


def mock_provider(monkeypatch, result):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(result).encode()
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr(planner.urllib.request, "build_opener", lambda *args: opener)
    return opener


def test_provider_request_has_hard_cap_no_storage_and_no_general_tools(monkeypatch):
    opener = mock_provider(monkeypatch, decision())
    assert planner.plan_question("What's the 10-year Treasury yield?", "test-key", today=TODAY)["action"] == "lookup"
    request = opener.open.call_args.args[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert payload["store"] is False
    assert payload["parallel_tool_calls"] is False
    assert payload["max_output_tokens"] == 256
    assert payload["tool_choice"] == "required"
    assert {tool["name"] for tool in payload["tools"]} == {"lookup_treasury_yields", "decline_question"}
    assert all(tool["strict"] and not tool["parameters"]["additionalProperties"] for tool in payload["tools"])
    lookup = payload["tools"][0]["parameters"]
    assert set(lookup["required"]) == {"maturities", "dates"}
    assert lookup["properties"]["dates"]["minItems"] == 1
    assert lookup["properties"]["dates"]["maxItems"] == 2
    assert lookup["properties"]["dates"]["items"]["type"] == "string"
    assert "Current New York date (America/New_York): 2026-10-25." in payload["instructions"]
    assert payload["input"] == [{"role": "user", "content": "What's the 10-year Treasury yield?"}]
    assert opener.open.call_args.kwargs["timeout"] == 10
    assert "test-key" not in request.data.decode()
    opener.open.assert_called_once()


def test_provider_can_resolve_explicit_historical_question_without_history(monkeypatch):
    opener = mock_provider(monkeypatch, decision(arguments=lookup_args(dates=["2025-10-23"])))
    text = "What was the 10 year rate on October 23rd, 2025?"
    assert planner.plan_question(text, "test-key", today=TODAY) == {
        "action": "lookup", "maturities": ["10y"], "dates": ["2025-10-23"]}
    payload = json.loads(opener.open.call_args.args[0].data)
    assert payload["input"] == [{"role": "user", "content": text}]
    assert "previous_response_id" not in payload


def test_provider_plan_validation_uses_the_same_date_anchor_as_its_prompt(monkeypatch):
    mock_provider(monkeypatch, decision(arguments=lookup_args(dates=["2026-10-26"])))
    with pytest.raises(planner.PlannerUnavailable):
        planner.plan_question("What is tomorrow's 10-year yield?", "test-key", today=TODAY)


@pytest.mark.parametrize("failure", [TimeoutError("private provider detail"), OSError("private provider detail")])
def test_provider_failures_have_generic_error(monkeypatch, failure):
    opener = MagicMock()
    opener.open.side_effect = failure
    monkeypatch.setattr(planner.urllib.request, "build_opener", lambda *args: opener)
    with pytest.raises(planner.PlannerUnavailable, match="temporarily unavailable") as raised:
        planner.plan_question("10-year Treasury yield?", "test-key", today=TODAY)
    assert "private provider detail" not in str(raised.value)


def test_oversize_provider_result_is_rejected(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b" " * 65537
    opener = MagicMock(open=MagicMock(return_value=response))
    monkeypatch.setattr(planner.urllib.request, "build_opener", lambda *args: opener)
    with pytest.raises(planner.PlannerUnavailable):
        planner.plan_question("10-year Treasury yield?", "test-key", today=TODAY)


def test_redirects_are_not_followed():
    assert planner.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://attacker.invalid") is None
