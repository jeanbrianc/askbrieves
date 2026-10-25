# Historical Treasury release verification

Verified 2026-10-25 for draft PR #2, based on merged PR #1.

## Changes and checks

- Exact historical dates from 1990-01-02 through the current New York date; one or two maturities and one or two dates, including `latest`.
- Historical dates require an exact published observation. No interpolation or previous-business-day substitution. Unpublished dates/tenors return a persisted `no_data` response with HTTP 200; invalid/unavailable source data still fails with HTTP 503.
- Latest observations retain their seven-day freshness limit. At most three monthly downloads per request, with reuse of already-fetched months.
- One OpenAI call, 256 output-token limit, existing authentication and daily quota remain in place. Numeric answers, spreads, and changes are calculated from verified Treasury observations in Python.
- Source links open the readable Treasury table. Raw XML URLs remain in evidence. The UI handles two dated source references and converts older saved XML links without altering history.
- Relevant tests passed, followed by the full suite: **153 tests and 64 subtests**. JavaScript syntax, CloudFormation lint, packaging, and GitHub CI passed.
- Independent integration review found no blocking issues. The existing 28-second cumulative dependency timeout limitation is documented in the operations guide.

## Deployment

- Stack `askbrieves` in `us-east-1`: `UPDATE_COMPLETE`; Lambda active with successful update.
- Change set modified the Lambda artifact and its existing integration; no resource replacement, table/schema change, secret rotation, IAM expansion, or quota change.
- Artifact SHA-256: `31cd5497b77a08f9e1648811b239273d144f3016667b7174b8910f4248bacaac`.
- Deployed Lambda digest matched the tested artifact.
- S3 artifact: `s3://askbrieves-artifacts-artifacts-lsci3aluirc3/releases/31cd5497b77a08f9e1648811b239273d144f3016667b7174b8910f4248bacaac/askbrieves.zip`.

## Real public API acceptance

The acceptance script used the generated bearer credential through a dynamic-reference wrapper. Neither credential values nor provider payloads are included here.

| Question/check | Observed result | Request ID |
|---|---|---|
| Latest 10-year | 5.00%, dated 2026-10-23 | `09ad5c83-74f5-4b64-95da-12ab0d6a346d` |
| Latest 2-year vs. 10-year | 4.69% / 5.00%, same observation date | `aa167777-7dbc-4e66-adbf-9ae0c065c5a9` |
| Exact owner question: 10-year on October 23rd, 2025 | 4.01%, exact date 2025-10-23 | `a3c23f4b-2f81-4461-9554-5ba5f2a1a515` |
| 2-year vs. 10-year on 2025-10-23 | 3.48% / 4.01% | `5c09340c-97f2-46a4-897d-b41eded9d52a` |
| 10-year on 2025-10-23 vs. latest | Two dated observations: 4.01% / 5.00% | `a9682112-cc21-4094-802a-74c6b53615c7` |
| 2025-10-25, a non-publishing date | HTTP 200, `no_data`; no substituted rate | `31176b57-9383-4e08-8144-ff8ae761e8f3` |
| Unrelated, secret/instruction override, mortgage, mixed malware requests | All declined | Synthetic cases saved in history |
| Future rate on 2099-10-23 | Declined, unsupported | `8fbdcc9a-3646-4a74-9b57-0319f5eed4a2` |
| Missing/wrong token; extra input field | 401; 400, respectively | No paid model attempt |
| Authenticated history | All 11 synthetic results found | HTTP 200 |

Public data references: [October 2025 readable table](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value_month=202510), [October 2026 readable table](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value_month=202610). Values above document the test, not a current-quote guarantee.

CloudWatch metadata matched the historical, dated-comparison, date-comparison, and no-data request IDs with durations 1260, 1396, 1415, and 1263 milliseconds. A bounded read of recent history independently confirmed these four records had the expected status and `policy_version: treasury-dates-v2`.

## Browser check

The deployed minimal chat still fits the same layout. Its new historical example fills the requested date correctly. Live authenticated answer correctness and both source URLs were verified through the deployed API; the UI renders source metadata from that evidence. Tokens stay in browser memory, with no persistent storage or unsafe HTML rendering.

The PR remains draft for owner review. No merge performed.
