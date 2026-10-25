import json
from unittest.mock import MagicMock

import pytest

from askbrieves import planner


def decision(name="lookup_treasury_yields", arguments=None, **changes):
    result = {"status": "completed", "output": [{"type": "function_call", "name": name,
              "arguments": json.dumps(arguments if arguments is not None else {"maturities": ["10y"]})}]}
    return dict(result, **changes)


def test_constrained_lookup_and_decline():
    assert planner.parse_plan(decision()) == {"action": "lookup", "maturities": ["10y"]}
    assert planner.parse_plan(decision(arguments={"maturities": ["2y", "10y"]}))["maturities"] == ["2y", "10y"]
    assert planner.parse_plan(decision("decline_question", {"reason": "unsafe"})) == {
        "action": "decline", "reason": "unsafe"}


@pytest.mark.parametrize("payload", [
    {}, None, [],
    decision(status="incomplete"),
    decision(name="read_secret"),
    decision(arguments={"maturities": ["10y"], "url": "https://attacker.invalid"}),
    decision(arguments={"maturities": ["mortgage"]}),
    decision(arguments={"maturities": ["10y", "10y"]}),
    decision(arguments={"maturities": []}),
    decision(arguments={"maturities": ["1y", "2y", "10y"]}),
    decision(arguments={"maturities": "10y"}),
    decision(arguments={"maturities": [None]}),
    decision("decline_question", {"reason": "anything"}),
    decision("decline_question", {"reason": "unsafe", "answer": "private content"}),
    decision(output=[{"type": "message", "content": "untrusted answer"}]),
    decision(output=[{"type": "function_call", "name": "lookup_treasury_yields", "arguments": "not json"}]),
    decision(output=decision()["output"] * 2),
    decision(output=decision()["output"] + [{"type": "message", "content": []}]),
])
def test_invalid_model_results_fail_closed(payload):
    with pytest.raises(planner.PlannerUnavailable):
        planner.parse_plan(payload)


def test_provider_request_has_hard_cap_no_storage_and_no_general_tools(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(decision()).encode()
    opener = MagicMock()
    opener.open.return_value = response
    monkeypatch.setattr(planner.urllib.request, "build_opener", lambda *args: opener)

    assert planner.plan_question("What's the 10-year Treasury yield?", "test-key")["action"] == "lookup"
    request = opener.open.call_args.args[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert payload["store"] is False
    assert payload["parallel_tool_calls"] is False
    assert payload["max_output_tokens"] == 256
    assert payload["tool_choice"] == "required"
    assert {tool["name"] for tool in payload["tools"]} == {"lookup_treasury_yields", "decline_question"}
    assert all(tool["strict"] and not tool["parameters"]["additionalProperties"] for tool in payload["tools"])
    assert opener.open.call_args.kwargs["timeout"] == 10
    assert "test-key" not in request.data.decode()


@pytest.mark.parametrize("failure", [TimeoutError("private provider detail"), OSError("private provider detail")])
def test_provider_failures_have_generic_error(monkeypatch, failure):
    opener = MagicMock()
    opener.open.side_effect = failure
    monkeypatch.setattr(planner.urllib.request, "build_opener", lambda *args: opener)
    with pytest.raises(planner.PlannerUnavailable, match="temporarily unavailable") as raised:
        planner.plan_question("10-year Treasury yield?", "test-key")
    assert "private provider detail" not in str(raised.value)


def test_oversize_provider_result_is_rejected(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b" " * 65537
    opener = MagicMock(open=MagicMock(return_value=response))
    monkeypatch.setattr(planner.urllib.request, "build_opener", lambda *args: opener)
    with pytest.raises(planner.PlannerUnavailable):
        planner.plan_question("10-year Treasury yield?", "test-key")


def test_redirects_are_not_followed():
    assert planner.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://attacker.invalid") is None
