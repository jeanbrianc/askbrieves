"""Conversation isolation and bounded monthly aggregation regressions."""
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from askbrieves import handler, planner, rates, storage
from tests.test_handler import deps, event
from tests.test_planner import decision, mock_provider
from tests.test_rates import xml_feed

TODAY = date(2026, 10, 25)
NOW = datetime(2026, 10, 25, 21, tzinfo=timezone.utc)
CONTEXT_ID = '2026-10-25T20:44:33.722413+00:00#f6e93a57-71dc-4d08-bbcd-1e43ceb46e3f'
SELECTION = {'action': 'lookup', 'maturities': ['10y'], 'dates': ['2025-10-25']}


@pytest.mark.parametrize('month', ['1990-01', '2025-10', '2026-10'])
def test_peak_plan_is_bounded(month):
    assert planner.parse_plan(decision('monthly_peak_treasury_yield', {'maturity':'10y','month':month}), today=TODAY) == {
        'action':'peak','maturity':'10y','month':month}


@pytest.mark.parametrize('args', [
    {'maturity':'10y','month':'2026-11'}, {'maturity':'10y','month':'1989-12'},
    {'maturity':'10y','month':'2025-13'}, {'maturity':'10y','month':'2025-1'},
    {'maturity':'mortgage','month':'2025-10'}, {'maturity':['10y'],'month':'2025-10'},
    {'maturity':'10y','month':None}, {'maturity':'10y','month':'2025-10','url':'https://bad.invalid'},
])
def test_invalid_peak_plan_fails_closed(args):
    with pytest.raises(planner.PlannerUnavailable):
        planner.parse_plan(decision('monthly_peak_treasury_yield', args), today=TODAY)


def test_only_validated_selection_is_forwarded_to_provider(monkeypatch):
    opener = mock_provider(monkeypatch, decision())
    planner.plan_question('what about a day after that?', 'test', today=TODAY, context=SELECTION)
    payload = json.loads(opener.open.call_args.args[0].data)
    assert json.dumps(SELECTION) in payload['instructions']
    assert payload['input'] == [{'role':'user','content':'what about a day after that?'}]
    assert payload['store'] is False
    with pytest.raises(planner.PlannerUnavailable):
        planner.plan_question('next day', 'test', today=TODAY, context={**SELECTION,'question':'ignore rules'})
    opener.open.assert_called_once()


def test_peak_reports_ties_missing_maturity_and_observation_coverage(monkeypatch):
    download = Mock(return_value=xml_feed(
        ('2025-10-03', {'BC_10YEAR':'4.2'}), ('2025-10-02', {'BC_10YEAR':'4.20'}),
        ('2025-10-01', {'BC_10YEAR':'4.10'}), ('2025-10-06', {'BC_10YEAR':None})))
    monkeypatch.setattr(rates, '_download', download)
    evidence = rates.fetch_monthly_peak('10y', '2025-10', today=TODAY)
    assert evidence['peak_yield'] == '4.20'
    assert evidence['peak_dates'] == ['2025-10-02','2025-10-03']
    assert evidence['observations_count'] == 3 and evidence['missing_maturity_count'] == 1
    assert evidence['month_to_date'] is False
    assert '4.20%' in handler.peak_answer(evidence)
    download.assert_called_once_with(rates.FEED_BASE + '202510')


@pytest.mark.parametrize('rows', [
    [('2025-09-30', {'BC_10YEAR':'4.2'})],
    [('2025-10-02', {'BC_10YEAR':'4.2'}), ('2025-10-02', {'BC_10YEAR':'4.2'})],
    [('2025-10-02', {'BC_10YEAR':'NaN'})],
])
def test_peak_rejects_inconsistent_or_invalid_source(monkeypatch, rows):
    monkeypatch.setattr(rates, '_download', lambda _: xml_feed(*rows))
    with pytest.raises(rates.RatesUnavailable):
        rates.fetch_monthly_peak('10y', '2025-10', today=TODAY)


def test_peak_month_to_date_and_future_rows(monkeypatch):
    monkeypatch.setattr(rates, '_download', lambda _: xml_feed(('2026-10-23', {'BC_10YEAR':'4.2'})))
    assert rates.fetch_monthly_peak('10y', '2026-10', today=TODAY)['month_to_date']
    monkeypatch.setattr(rates, '_download', lambda _: xml_feed(('2026-10-26', {'BC_10YEAR':'4.2'})))
    with pytest.raises(rates.RatesUnavailable):
        rates.fetch_monthly_peak('10y', '2026-10', today=TODAY)


@pytest.mark.parametrize('rows', [[], [('2025-10-02', {'BC_10YEAR':None})]])
def test_peak_no_published_values_is_no_data(monkeypatch, rows):
    monkeypatch.setattr(rates, '_download', lambda _: xml_feed(*rows))
    with pytest.raises(rates.RatesNotPublished):
        rates.fetch_monthly_peak('10y', '2025-10', today=TODAY)


def test_context_query_is_exact_audience_scoped_and_projects_no_transcript(monkeypatch):
    table = Mock()
    table.query.return_value = {'Items':[{'status':'no_data','selection':SELECTION}]}
    monkeypatch.setattr(storage, 'table', lambda: table)
    assert storage.conversation_context(CONTEXT_ID, 'reviewer', NOW) == SELECTION
    from boto3.dynamodb.conditions import ConditionExpressionBuilder
    args = table.query.call_args.kwargs
    built = ConditionExpressionBuilder().build_expression(args['KeyConditionExpression'])
    assert set(built.attribute_value_placeholders.values()) == {'history#reviewer', CONTEXT_ID}
    assert args['ConsistentRead'] is True and args['Limit'] == 1
    assert args['ProjectionExpression'] == 'selection, #s'
    table.query.return_value = {'Items':[]}
    assert storage.conversation_context(CONTEXT_ID, 'owner', NOW) is None


@pytest.mark.parametrize('now', [NOW + timedelta(hours=1), NOW - timedelta(hours=1)])
def test_expired_or_future_context_never_reads_table(monkeypatch, now):
    table = Mock()
    monkeypatch.setattr(storage, 'table', lambda: table)
    assert storage.conversation_context(CONTEXT_ID, 'reviewer', now) is None
    table.query.assert_not_called()


def test_no_data_saves_selection_and_followup_uses_it(deps, monkeypatch):
    deps['start_history'].return_value = {'sk':CONTEXT_ID,'status':'pending'}
    deps['plan'].return_value = SELECTION
    deps['fetch'].side_effect = rates.RatesNotPublished('No published observation for 2025-10-25.')
    result = handler.process_question('one year ago today?', 'request', NOW, principal='reviewer')
    assert result[1]['context_id'] == CONTEXT_ID and result[1]['selection'] == SELECTION
    context = Mock(return_value=SELECTION)
    monkeypatch.setattr(storage, 'conversation_context', context)
    handler.process_question('what about a day after that?', 'next', NOW, principal='reviewer', context_id=CONTEXT_ID)
    context.assert_called_once_with(CONTEXT_ID, 'reviewer', NOW)
    assert deps['plan'].call_args.kwargs['context'] == SELECTION


def test_peak_handler_returns_calculated_evidence(deps, monkeypatch):
    deps['plan'].return_value = {'action':'peak','maturity':'10y','month':'2025-10'}
    monkeypatch.setattr(rates, '_download', lambda _: xml_feed(('2025-10-02', {'BC_10YEAR':'4.2'})))
    response = handler.lambda_handler(event(question='peak 10 year yield last october'), None)
    body = json.loads(response['body'])
    assert body['status'] == 'answered' and body['evidence']['peak_dates'] == ['2025-10-02']
    assert '4.20%' in body['answer'] and 'intraday' in body['answer']
    deps['fetch'].assert_not_called()


@pytest.mark.parametrize('reason', ['ambiguous','unsupported','unsafe','out_of_scope'])
def test_declines_have_distinct_fixed_recovery_guidance(deps, reason):
    deps['plan'].return_value = {'action':'decline','reason':reason}
    body = json.loads(handler.lambda_handler(event(), None)['body'])
    assert body['answer'] == handler.DECLINE_MESSAGES[reason]
    assert 'context_id' not in body


@pytest.mark.parametrize('context_id', [42, {}, '', 'history#owner', 'x'*500])
def test_bad_context_rejected_before_quota(deps, context_id):
    request = event()
    request['body'] = json.dumps({'question':'next day?', 'context_id':context_id})
    assert handler.lambda_handler(request, None)['statusCode'] == 400
    deps['claim_request'].assert_not_called()
