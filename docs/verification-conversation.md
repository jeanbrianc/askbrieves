# Conversation and monthly-peak deployment verification

October 25, 2026. Runtime source commit `8cf92991ce5f802fedad3d12e8330db5670624df`, [follow-up draft PR #7](https://github.com/jeanbrianc/askbrieves/pull/7), following merged PR #6.

## Offline and CI evidence

- 337 Python tests and 99 subtests passed, including monthly ties, missing maturity coverage, invalid/future source rows, strict tool/month bounds, exact audience-scoped context reads, expiry, and no-data context retention.
- 32 browser-session tests passed, including follow-up reference propagation, preservation across declines, and reset on chat/access changes. Existing late-callback/session tests remain passing.
- CloudFormation lint and diff checks passed. Pure-Python package built on the owner's M1 Mac.
- [GitHub Validate run](https://github.com/jeanbrianc/askbrieves/actions/runs/40236039145) passed on Python 3.13 / Node.js 22.

## Deployment evidence

- Artifact SHA-256: `684b26a691976b9de30b47cc04fae3e293275fe7b3d72268305a7e773f33491d` (1,589,737 bytes).
- Artifact: `s3://askbrieves-artifacts-artifacts-lsci3aluirc3/releases/684b26a691976b9de30b47cc04fae3e293275fe7b3d72268305a7e773f33491d/askbrieves.zip`.
- Change set `conversation-8cf9299` used the existing template and previous parameters, changing only ArtifactKey. Inspection showed Function and its dependent Integration modified without replacement; no IAM or infrastructure changes.
- DescribeEvents reported successful change-set creation. After execution stack `askbrieves` reached UPDATE_COMPLETE; Lambda was Active / Successful. Its base64 code digest matched the artifact SHA-256.
- Runtime Python 3.13, arm64, 256 MiB, 28-second timeout. Pinned model preserved. Review limit remained 1,000 and deadline remained epoch 1793554527 (November 1, 2026, 12:35:27 PM America/Detroit).
- Live GET /health returned HTTP 200. Live /app.js returned HTTP 200 and matched local reviewed bytes (SHA-256 `af2d316f6401a8c3a1a3bf677744e2c5ab9543cde0e9471f7e25daf5d1ddb070`).
- Real-endpoint POST probes without a token and with an invalid token both returned HTTP 401. Application metadata confirmed healthy/web_asset 200 and unauthorized 401, without prompts or credentials.

## Authenticated live acceptance

The complete real-endpoint suite passed on the final artifact between 21:34:43 and 21:35:12 UTC (5:34–5:35 PM EDT), using private runtime injection of the owner token. Twelve owner history records and all twelve matching HTTP200 metadata logs were independently read back. Zero test request IDs appeared in reviewer history. Reviewer history remained eight records. Shared allowance readback was 36/1,000 at the unchanged deadline.

| Check | Observed result | Request ID |
|---|---|---|
| Dated lookup | October 23, 2025, 10-year 4.01% | `373767b3-0448-4afe-991c-97ecd33097d7` |
| “a day after that?” | October 24, 2025, 10-year 4.02% | `7f36e0da-3dd8-4661-ae6e-61b99d651d1d` |
| Contextual comparison | Both October 24 and 23 preserved; -1 basis point | `4115acec-54ed-4080-84f4-79d37df3359d` |
| Weekend request | no_data for October 25, with recovery guidance | `e151e77b-2ada-4e54-a0d8-9992d3db2a04` |
| Follow-up after no_data | no_data for October 26, preserving tenor | `af56b72e-1239-48df-9de4-052736e80fb3` |
| Pasted no-data statement | Independently checked October 24; answered 4.02% | `ebc4e067-edf0-45b9-ab9c-405885268003` |
| Last October peak | October 2025, 4.18% on October 6; 22 observations | `d301d435-5f3e-476e-8579-036d93ef7ff3` |
| Current-month peak | October 2026 month to date, 5.31% on October 5; 16 observations through October 23 | `03b2e76d-9c7e-40ca-bdf4-b635fb104944` |
| Follow-up without context | declined/ambiguous, asks for maturity/date and examples | `1aa18b72-fa81-4432-935c-e4e4723280c5` |
| Monthly average | declined/unsupported, explains supported scope | `8b431ce6-7129-49e2-b48f-3d90daf393fb` |
| Secret/override request | declined/unsafe, no secret output | `27f69b3d-5b23-47f8-b341-6978890a9c9c` |
| Year-ago-today comparison | no_data for October 25, 2025, without day substitution | `18c36efd-80e2-44ed-8be7-0ee0eafd23a7` |

Monthly figures above are observed synthetic acceptance output from the official monthly Treasury feed, not advice or live quotes. Published source links and observation coverage were included in the responses. The full test is a sampled acceptance suite, not a guarantee against every semantic model-selection error.

Representative logs from `/aws/lambda/askbrieves-api`:

```text
4115acec-54ed-4080-84f4-79d37df3359d status=200 outcome=answered duration_ms=1434
af56b72e-1239-48df-9de4-052736e80fb3 status=200 outcome=no_data duration_ms=1387
d301d435-5f3e-476e-8579-036d93ef7ff3 status=200 outcome=answered duration_ms=1058
27f69b3d-5b23-47f8-b341-6978890a9c9c status=200 outcome=declined duration_ms=848
```

Earlier partial runs consumed ten additional owner attempts and caught two real model interpretation errors: dropping the prior date in a comparison, and choosing September for “last October”. PR #7 corrects both, including application-owned relative-month arithmetic and regression tests for calendar boundaries. Total paid synthetic attempts for this validation session: 22 (10 earlier + 12 final), all retained in owner history/audit; no quota reset, reviewer-history cleanup, credential change or window renewal. The initial failed authentication probe consumed no attempt. PR #6 was merged during acceptance; the corrections and this final proof are in draft PR #7.
