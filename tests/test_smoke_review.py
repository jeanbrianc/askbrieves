"""Offline checks for the optional live acceptance harness, never live endpoints."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import smoke, smoke_review


OWNER = "owner-fixture-01234567890123456789"
REVIEWER = "reviewer-fixture-0123456789012345"
BASE = "https://review.example.com"
PRIVATE_HISTORY = "PRIVATE OWNER HISTORY MUST NOT BE PRINTED"


def configured(monkeypatch):
    monkeypatch.setenv("ASKBRIEVES_TOKEN", OWNER)
    monkeypatch.setenv("ASKBRIEVES_REVIEWER_TOKEN", REVIEWER)
    monkeypatch.setenv("ASKBRIEVES_URL", BASE)


@pytest.mark.parametrize("field,value", [
    ("ASKBRIEVES_TOKEN", None),
    ("ASKBRIEVES_REVIEWER_TOKEN", None),
    ("ASKBRIEVES_TOKEN", ""),
    ("ASKBRIEVES_REVIEWER_TOKEN", ""),
    ("ASKBRIEVES_REVIEWER_TOKEN", OWNER),
    ("ASKBRIEVES_TOKEN", OWNER + "\n"),
    ("ASKBRIEVES_REVIEWER_TOKEN", REVIEWER + "\r\n"),
    ("ASKBRIEVES_URL", "http://review.example.com"),
    ("ASKBRIEVES_URL", "https://user:private-fixture@review.example.com"),
    ("ASKBRIEVES_URL", "https://review.example.com/other"),
    ("ASKBRIEVES_URL", "https://review.example.com?next=elsewhere"),
    ("ASKBRIEVES_URL", "https://review.example.com#fragment"),
    ("ASKBRIEVES_URL", "https://review.example.com:8443"),
    ("ASKBRIEVES_URL", "https://review.example.com:bad"),
    ("ASKBRIEVES_URL", "https://review.exa\nmple.com"),
])
def test_bad_configuration_fails_before_network_without_echoing_values(monkeypatch, capsys, field, value):
    configured(monkeypatch)
    if value is None:
        monkeypatch.delenv(field)
    else:
        monkeypatch.setenv(field, value)
    forbidden = Mock(side_effect=AssertionError("Network must not run."))
    monkeypatch.setattr(smoke_review, "request", forbidden)
    monkeypatch.setattr(smoke_review, "ask", forbidden)
    assert smoke_review.main() == 2
    forbidden.assert_not_called()
    output = capsys.readouterr().out
    for secret in (OWNER, REVIEWER, "private-fixture"):
        assert secret not in output


def test_import_does_not_read_credentials_or_make_requests(monkeypatch):
    forbidden = Mock(side_effect=AssertionError("Import must be passive."))
    monkeypatch.setattr(smoke, "request", forbidden)
    monkeypatch.setattr(smoke, "ask", forbidden)
    monkeypatch.delenv("ASKBRIEVES_TOKEN", raising=False)
    monkeypatch.delenv("ASKBRIEVES_REVIEWER_TOKEN", raising=False)
    spec = importlib.util.spec_from_file_location("scripts.smoke_review_probe", Path(smoke_review.__file__))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    forbidden.assert_not_called()


def observation(day, rates):
    month = day[:7].replace("-", "")
    return {"as_of": day, "rates": rates,
            "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value_month=" + month,
            "data_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value_month=" + month}


class SyntheticBackend:
    def __init__(self, failure=None):
        self.failure = failure
        self.questions = []
        self.reviewer = []
        self.owner = [{"request_id": "owner-prior", "status": "answered", "principal": "owner",
                       "question": PRIVATE_HISTORY, "answer": PRIVATE_HISTORY}]
        if failure == "empty_owner":
            self.owner = []

    def __call__(self, base, path, token=None, body=None):
        assert base == BASE
        assert token in (OWNER, REVIEWER)
        if path.startswith("/history"):
            items = self.owner if token == OWNER else self.reviewer
            if self.failure == "spoof_exposes_owner" and path == "/history?principal=owner":
                items = self.owner
            if self.failure == "owner_exposes_reviewer" and token == OWNER and self.reviewer:
                items = self.owner + self.reviewer
            if self.failure == "wrong_saved_status" and token == REVIEWER and self.reviewer:
                items = [dict(item, status="pending") for item in self.reviewer]
            return 200, json.dumps({"items": items})
        assert path == "/questions" and token == REVIEWER
        question = body["question"]
        self.questions.append(question)
        request_id = "review-" + str(len(self.questions))
        result = {"request_id": request_id, "status": "answered", "answer": "Reviewed synthetic answer."}
        concepts = {question: topic for topic, question in smoke_review.CONCEPTS}
        if question in concepts:
            result["evidence"] = {"topic": concepts[question], "source_url": "https://www.investor.gov/fixture"}
        elif question == "Is the yield curve inverted?":
            result.update(evidence=observation("2026-10-23", {"2y": "4.69", "10y": "5.00"}),
                          answer="The 2-year/10-year segment was upward sloping: +31 basis points.")
        elif question.startswith("Was the 2-year/10-year"):
            result.update(evidence=observation("2025-10-23", {"2y": "3.48", "10y": "4.01"}),
                          answer="The 2-year/10-year segment was upward sloping: +53 basis points.")
        elif question.startswith("How much did"):
            result.update(evidence={"observations": [observation("2025-10-22", {"10y": "3.97"}),
                                                      observation("2025-10-23", {"10y": "4.01"})]},
                          answer="The 10-year yield changed by +4 basis points.")
        else:
            result.update(status="declined", answer="Unsupported synthetic request.", reason="unsupported")
        self.reviewer.append(dict(result, principal="reviewer", question=question))
        return 200, json.dumps(result)


def attach_backend(monkeypatch, backend):
    configured(monkeypatch)
    monkeypatch.setattr(smoke_review, "request", backend)
    # Exercise the real existing ask() helper while replacing its HTTP boundary.
    monkeypatch.setattr(smoke, "request", backend)
    monkeypatch.setattr(smoke_review.time, "sleep", lambda _: None)


def test_complete_extended_suite_runs_thirteen_cases_without_private_history_output(monkeypatch, capsys):
    backend = SyntheticBackend()
    attach_backend(monkeypatch, backend)
    assert smoke_review.main() == 0
    assert len(backend.questions) == 13
    assert backend.questions[:7] == [question for _, question in smoke_review.CONCEPTS]
    output = capsys.readouterr().out
    assert '"saved_results_found": 13' in output and "PASS:" in output
    for secret in (OWNER, REVIEWER, PRIVATE_HISTORY):
        assert secret not in output


@pytest.mark.parametrize("failure", ["spoof_exposes_owner", "owner_exposes_reviewer", "wrong_saved_status"])
def test_extended_suite_rejects_isolation_or_persistence_failure_without_dumping_history(monkeypatch, capsys, failure):
    backend = SyntheticBackend(failure)
    attach_backend(monkeypatch, backend)
    assert smoke_review.main() == 1
    output = capsys.readouterr().out
    assert "PASS:" not in output and "FAIL:" in output
    for secret in (OWNER, REVIEWER, PRIVATE_HISTORY):
        assert secret not in output


def test_empty_owner_history_cannot_give_vacuous_isolation_success(monkeypatch, capsys):
    backend = SyntheticBackend("empty_owner")
    attach_backend(monkeypatch, backend)
    assert smoke_review.main() == 1
    assert backend.questions == []
    assert "PASS:" not in capsys.readouterr().out


def test_malformed_history_fails_without_echoing_response(monkeypatch, capsys):
    configured(monkeypatch)
    monkeypatch.setattr(smoke_review.time, "sleep", lambda _: None)
    monkeypatch.setattr(smoke_review, "request", lambda *_: (200, json.dumps([PRIVATE_HISTORY])))
    assert smoke_review.main() == 1
    output = capsys.readouterr().out
    assert "FAIL:" in output and PRIVATE_HISTORY not in output
