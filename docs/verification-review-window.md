# Seven-day review allowance verification

October 25, 2026. This release replaces the UTC daily allowance with **1,000 total question attempts over one fixed seven-day window**. Owner and reviewer questions share the allowance; there is no midnight reset. Credential values are excluded from this document.

## Implementation and offline evidence

The active interval is `[ReviewWindowEndsAt - 604800, ReviewWindowEndsAt)`. A conditional DynamoDB `ADD` claims each attempt against `quota#review#<end epoch>` / `total`, with TTL two days after the end. Updating code, crossing midnight, or rotating a token preserves usage. Only deliberately selecting a new deadline creates a new grant; earlier counters are retained for audit.

Authentication and input validation precede the claim. Exhaustion returns 429 with `review_limit_exceeded`; an inactive window returns 403 with `review_window_closed`. Both stop before history/provider work. Missing or invalid window configuration fails closed with 503. History reads do not consume attempts. The deploy helper preserves the configured limit and deadline even after expiry, and aborts on AWS read/authentication failures rather than silently creating a new window.

- `python3 -m pytest -q`: 298 tests and 99 subtests passed.
- `node --test tests/web_session.test.cjs`: 31 tests passed, including updated expiry/quota messages and the preceding session-ownership protections.
- CloudFormation lint, JavaScript/shell syntax, documentation shell blocks, and diff checks passed.
- An independent static patch review reported no actionable findings; its 115 focused tests passed. This is not a new repository security assessment or proof of live dependency behavior.

## Deployment and live validation

- Runtime-source commit: `2ceb9ca879719e00a591ccdc4265fad4c06b2c97`. Later proof edits do not change the runtime package.
- [Runtime-source CI](https://github.com/jeanbrianc/askbrieves/actions/runs/40216698042) passed on Python 3.13 and Node.js 22.
- Package SHA-256: `bbcb3aac27642a0e8c48a6e57a8d8d3dc8ee365b202ac568a65131208987834c` (1,586,453 bytes).
- Artifact: `s3://askbrieves-artifacts-artifacts-lsci3aluirc3/releases/bbcb3aac27642a0e8c48a6e57a8d8d3dc8ee365b202ac568a65131208987834c/askbrieves.zip`.
- Change sets `review-window-2ceb9ca8`, `review-window-expiry-probe`, and `review-window-fresh-handoff` each modified only Function/Integration without replacement. Each passed CloudFormation pre-deployment validation via `DescribeEvents`. The stack reached `UPDATE_COMPLETE` and Lambda reported `Successful` after each phase.
- The final Lambda code digest matched the package. The live `/app.js` bytes matched the reviewed source. Limit 1,000, pinned model, timeout 28 seconds, secret-ARN-only configuration and shared account concurrency were confirmed; the daily environment setting was removed. No new AWS resources, IAM permissions, dependencies or concurrency changes were introduced.

The committed real-endpoint suites passed **11 baseline plus 13 extended cases**, covering dated/latest yields, calculations, exact-date gaps, seven concepts, curve assessments, refusals, persisted results and audience isolation. Consistent DynamoDB readback recorded exactly 24 attempts in the separate validation window. Historical evidence included the October 23, 2025 10-year observation of 4.01%, its 2-year counterpart of 3.48%, and the +53 basis-point spread.

To test exhaustion without purchasing 1,000 calls, an operator conditionally seeded **only the validation counter** from its verified 24 to 1,000 and marked it `validation_seed=true`, preserving `actual_attempts_before_seed=24`. The next authenticated question returned 429 / `review_limit_exceeded`; the counter remained 1,000 and both audiences' history keys were unchanged. This is a seeded boundary test, not a claim of 1,000 real requests or a live concurrency stress test.

A temporary expired deadline then made an authenticated owner question return 403 / `review_window_closed`, again with no history changes. The expired-window probe used the owner token so reviewer-token expiry could not mask the question-window check. Unit tests separately prove both rejections stop before provider work and cover the exact start/end boundaries, midnight, configuration errors and conditional-write behavior.

Sampled application metadata from `/aws/lambda/askbrieves-api`:

```text
f5b4c655-9587-43d8-a599-afd82b228c77 200 answered              1641ms (historical yield)
464ebc2f-9b2f-42bd-8d8f-788a339f743c 200 answered              1124ms (historical curve)
2e0c298a-3518-4390-98ae-70700f7f4f5a 200 answered              1330ms (dated change)
c562e4b1-a8b7-45b7-bf96-2ef07ff3c38f 200 declined               854ms (secret request)
8cbca4c8-15e6-492b-a44a-1c34dfca0cb5 429 review_limit_exceeded   17ms
d7f2d20a-6611-450a-9925-a6065abf3427 403 review_window_closed   957ms
```

These are observed timings, not service guarantees. Logs contain request metadata rather than question text, answers or credentials.

## Fresh review grant and clean history

After acceptance and boundary probes, a new grant was explicitly selected:

| Setting | Confirmed value |
|---|---|
| Start, inclusive | October 25, 2026 17:35:27 UTC (1:35:27 PM EDT) |
| End, exclusive | November 1, 2026 17:35:27 UTC (12:35:27 PM EST) |
| Window length | 604,800 seconds; exactly seven 24-hour days across the daylight-saving change |
| Shared total allowance | 1,000 attempts |
| Used at activation readback | 0; consistent read found no counter item for the new deadline |
| Reviewer credential expiry | Same end epoch, 1793554527 |

Owner and reviewer credential values were preserved while only the reviewer expiry changed. Credentials were injected privately at runtime and were never printed, committed or included in evidence. A scoped transaction deleted exactly the 13 known reviewer test records; consistent queries showed zero reviewer records and all 71 owner-history keys unchanged. Legacy daily usage and the marked validation counter remain retained; neither was reset to disguise test consumption.

Final read-only endpoint verification returned reviewer `GET /history` HTTP200 with `items: []`, preserved owner `GET /history` HTTP200, and public health HTTP200. The reviewer expiry matched the window deadline. No question or smoke request was sent against the fresh handoff window. The 1,000-attempt limit bounds model attempts, not public AWS request charges; provider spending controls remain separate owner settings.
