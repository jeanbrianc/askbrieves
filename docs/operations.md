# Operations

## Ownership and signals

The demo has an owner credential and an optional expiring reviewer credential. Histories use separate fixed partitions; a reviewer cannot request the owner's partition. People sharing the reviewer credential share that audience's history. `GET /health` is liveness only, not a dependency check. Every accepted question, including explanations, no-data results, refusals and provider failures, consumes one attempt from the global seven-day allowance. The default is 1,000 total attempts, with no daily cutoff or midnight reset.

The public `/` page and assets are served by the same Lambda. Access accepts a demo bearer token, never the OpenAI key. Tokens remain in memory, without browser storage or cookies. Changing credentials, disconnecting, a 401, or page exit clears the local conversation/draft and invalidates pending callbacks; an empty history response replaces any displayed transcript. A newly typed draft before first connecting is preserved. Local clearing does not delete server history. Questions and audience-scoped history require authentication. The CSP permits same-origin assets and connections; educational source links use official Treasury, Federal Reserve, New York Fed, and SEC hosts. The quiet footer links to GitHub. No question-supplied URLs are fetched.

CloudFormation outputs `FunctionName`, `FunctionLogGroup`, `ApiLogGroup`, and `HistoryTable`. Application logs emit request ID, status, outcome, and duration; the same request ID is returned in the response/header. Access logs contain gateway request ID, route, status, and latency. Use these IDs for correlation without printing questions or credentials. Three alarms cover API 5xx, unhandled Lambda errors, and Lambda throttles. **No alarm notification/paging destination is configured**; alarms must be inspected in CloudWatch until an owner adds one. Handled dependency failures appear in API 5xx, even when Lambda's invocation succeeded.

```bash
aws logs tail /aws/lambda/askbrieves-api --since 10m --region us-east-1
aws cloudwatch describe-alarms --region us-east-1
```

The initial service objective is operational evidence, not a measured availability promise. A reasonable future SLO is successful supported queries with verified data within 20 seconds; measure dependency latency and define what excludes a deliberate refusal or auth failure before adopting it.

## Failure handling

| Symptom | First checks / response |
|---|---|
| 401 | Verify bearer credential and header through a private channel. A rotated token may take up to 60 seconds to replace the runtime cache. Do not paste headers into logs. |
| 400 | One JSON `question` field, 1–500 characters, no controls, no query parameters, no obvious credentials; body <=4 KiB. |
| 429 | A brief gateway burst/rate throttle, or exhausted total review allowance (`review_limit_exceeded`). Gateway throttles may allow a short retry; the review allowance does not reset daily. Investigate load before deliberately opening another allowance. |
| 403 `review_window_closed` | The configured seven-day question window has not started or has ended. No history/provider work is started. An expired reviewer credential may instead fail authentication with 401. |
| 200 `no_data` | The exact requested date or maturity was not published. Check the readable monthly `source_url` and XML `data_url`; do not replace a weekend/holiday with a neighboring date. This is a domain result, not a dependency outage. |
| 503 | Inspect metadata outcomes, provider service status, secret metadata/IAM, and Treasury source availability or invalid data. Never disable screening, date validation, or freshness checks to restore an answer. |
| Pending history | A process died or persistence failed. The 28-second hard Lambda timeout bounds work; cumulative dependency delays can exhaust it. A pending record is not a completed answer. Retry is a new request and consumes quota. |
| Wrong/old rate | Inspect each returned observation date and official source. Latest observations must be <=7 calendar days old by default; explicit historical dates must match exactly and lie between 1990-01-02 and today's New York date. A historical result is not subject to the latest-data freshness window. Stop serving if integrity is doubtful. |
| Timeout / throttles | Inspect API latency, Lambda concurrency, and provider rate limits. The gateway integration timeout is 29 seconds, Lambda 28 seconds; no provider retries. Lambda shares account concurrency capacity by default, so other functions can consume that capacity. Avoid scaling before understanding costs. |

A question can select at most two maturities and two dates, with `latest` allowed alongside one exact date. One OpenAI call selects the bounded lookup; Python validates dates and maturities. Up to three monthly source downloads cover the requested dates and any latest-month fallback. Single-date evidence retains the `as_of`/`rates` shape; a date comparison uses `evidence.observations`. Each observation links to a readable monthly table (`source_url`) and its raw XML (`data_url`). No AWS resources or deployment parameters change for historical support.

## Stop, rotate, restore

The template and release script default to `ReservedConcurrency=-1`, which omits a reservation and shares existing account capacity. The script does not request a quota increase. A positive `ASKBRIEVES_RESERVED_CONCURRENCY` setting is optional and requires enough regional capacity. Per-route API targets of 1 request/second, burst 2, and the atomic 1,000-attempt total review cap remain in force. These are not one application-wide request bucket or an AWS spending ceiling.

Before an emergency stop, inspect and record the actual concurrency configuration. An empty configuration means the function has no reservation; compare it with the stack's `ReservedConcurrency` parameter. Do not guess the restore value.

```bash
aws lambda get-function-concurrency --function-name askbrieves-api --region us-east-1
```

Fast kill switch (authorized operator; stops all Lambda requests including health):

```bash
aws lambda put-function-concurrency --function-name askbrieves-api \
  --reserved-concurrent-executions 0 --region us-east-1
```

Restore only after the incident is understood. For the default unreserved setting (`ReservedConcurrency=-1`), remove the emergency reservation:

```bash
aws lambda delete-function-concurrency --function-name askbrieves-api --region us-east-1
```

If the recorded configuration had a positive reservation, restore that exact value with `put-function-concurrency --reserved-concurrent-executions VALUE` instead. These are emergency drift operations. Record the incident/change, restore the declared setting, and reconcile with IaC. Revoking the OpenAI key is an additional provider-side cutoff; it does not stop unauthenticated AWS request charges.

Rotate owner access by updating the secret's `token` field with a fresh high-entropy value, preserving reviewer fields. Rotate reviewer access independently with a generated value of at least 32 random bytes (a 43-character URL-safe token), preserving the owner token and the intended expiry. Optional `reviewer_token` (12–512 characters) requires `reviewer_expires_at` (integer UTC epoch). Revoke it by expiring or removing those fields. Missing reviewer fields do not disable owner access. Allow up to 60 seconds for caches. The temporary reviewer credential is a demo convenience, not a production identity system. Never place token values in this repository, PR comments, screenshots, or shell history.

`scripts/smoke.py` creates 11 owner/test history records. Optional `scripts/smoke_review.py` requires distinct owner and reviewer tokens and creates 13 reviewer records while checking all seven concepts, curve/date changes, refusals, and history isolation. Both consume the configured review-window allowance. Run them explicitly in a validation window against the intended HTTPS endpoint; offline tests never invoke either suite. The public scripts deliberately cannot delete history or read AWS secrets.

Before handing a tested reviewer audience to another person, an authorized operator may query the actual stack's `HistoryTable` with `pk = history#reviewer` and delete only those returned keys. Preserve owner `pk = history` and all `quota#...` records; do not reset a counter to erase test usage. Ensure no question is pending, then verify a consistent full-partition query and authenticated `GET /history` both return zero records. Avoid a new question or another smoke run after final activation/cleanup. This clears active application history; retained backups/PITR have their documented retention behavior.

## Review allowance activation

`RequestLimit` is an integer from 1 to 1,000 (default 1,000). `ReviewWindowEndsAt` is an integer UTC epoch second. Questions are accepted only in `[end - 604800, end)`. All audiences use one atomic counter at `pk = quota#review#<end epoch>`, `sk = total`, with TTL two days after the window ends. Midnight and normal code deployments do not change its key or count. History and liveness reads remain separate from the question allowance.

The release script discovers an existing stack before making AWS changes. It preserves its end and limit, including an expired end; authentication/access/network errors abort rather than being mistaken for a missing stack. New stacks and migration from the former daily quota default to a new seven-day window. `ASKBRIEVES_REVIEW_WINDOW_ENDS_AT` deliberately selects a new end and therefore a new allowance; `ASKBRIEVES_REQUEST_LIMIT` deliberately changes the limit up to 1,000. These settings are non-secret IaC parameters, not HTTP request fields. Lowering or raising the limit without changing the end preserves the existing usage counter.

For a fresh handoff: finish live acceptance in a separate validation window; inspect/execute a CloudFormation change set selecting an end exactly seven days from activation; preserve the owner and reviewer token values while setting `reviewer_expires_at` to that end (or earlier). Retain earlier counters for audit. Clean only reviewer test history. Verify the new window has no consumed attempts and read-only reviewer history is empty. Do not run another question against the handoff window afterward. Rotating a token with the same window does not replenish allowance.

Confirm an enforced spend limit in a dedicated OpenAI project separately from spend alerts. The application does not configure provider billing controls, and AWS request/transfer costs remain outside those limits. The `Application` cost allocation tag must be available and activated before Cost Explorer can attribute costs reliably; newly created or unallocated resources returning an empty cost result are not proof of zero spend.

Rotate the OpenAI project key in its separate `api_key` secret and revoke the old key after testing. Never commit credentials or post them in public issues. Runtime IAM still reads only the two existing secrets. A customer-managed KMS key needs scoped `kms:Decrypt`; the template assumes the AWS-managed Secrets Manager key.

## Releases and rollback

CI runs Python tests, offline JavaScript session tests on Node.js22, CloudFormation lint, and packaging without cloud credentials. Node is a development/test requirement only; the deployed function remains pure Python with browser JavaScript assets. The release script requires a human-authenticated AWS profile. Package contents are deterministic and named in S3 by SHA-256. Keep the prior `ArtifactKey` from stack parameters before updating.

To roll back code, redeploy `infra/service.json` using a compatible previous `ArtifactKey` and existing parameter values, or use a CloudFormation change set with `UsePreviousValue` for all other parameters. Artifacts preceding the seven-day quota release implement a daily counter and are incompatible with the new window configuration; do not roll those back under the current template. Prefer a forward fix, or stop question traffic before a coordinated code/configuration rollback. Inspect the change set, execute it, then rerun authenticated smoke checks in a validation window. Do not restore a previous secret version as part of a code rollback. To verify infrastructure configuration after a release, check the stack status, Lambda runtime/concurrency/environment (ARNs only), IAM resource scope, table encryption/PITR/TTL, log retention, custom TLS domain, disabled default endpoint, and DNS.

State retention is deliberate: the history table, generated API secret, artifact bucket and its TLS policy survive stack deletion. PITR and retained data may still incur charges. DynamoDB TTL is asynchronous and backups can retain older data beyond the API visibility window; this is not a statutory deletion guarantee. For complete teardown, first delete the service stack, then the artifact stack, and explicitly review/export/delete retained resources under a separate authorized cleanup. The externally supplied OpenAI secret and project key are not owned by this stack and require separate cleanup. ACM validation CNAMEs can remain after certificate deletion.


## Follow-up context and monthly peaks

`POST /questions` accepts `question` and optional `context_id`. The reference identifies the exact previous history row; the server always supplies the authenticated audience partition. One consistent Query projects only the saved validated selection and status, with a 30-minute age check before the read. No transcript is sent to OpenAI. Answered and no-data selections can supply context; declined/pending/unavailable records cannot. Browser clear, history load, credential change, disconnect and page exit clear its reference. Reload an existing tab after deploying to use the new browser script. People sharing a reviewer token still share one audience; this does not add per-person authentication.

A monthly peak permits one supported maturity and one YYYY-MM from January 1990 through the current New York month. Python resolves a single explicit “last October”/“this month”/“last month” reference with calendar arithmetic rather than trusting the model's month selection, and calculates a maximum across available daily yields from one bounded Treasury monthly download. It reports all ties, observation count/range and missing maturity count. Current-month results are month to date; no unpublished days or missing tenors are invented. Exact weekend/holiday lookups still return no_data with recovery guidance rather than substituting business dates. Decline categories now have fixed, specific scope/rephrasing messages.

No infrastructure, IAM, credentials, model, quota, deadline or kill-switch configuration changes are needed. A contextual question adds one consistent single-row DynamoDB read and a small bounded structured reference in the same model call; peaks use one source download. The existing 1,000-attempt shared allowance and provider/AWS cost limitations still apply. Deploy an immutable Lambda package through an ArtifactKey-only CloudFormation change set using the existing template and all other parameters unchanged. Inspect DescribeEvents and the change set, then verify stack UPDATE_COMPLETE, Lambda Successful, package digest, live app.js bytes, deadline/limit, and owner-only conversation acceptance. Rollback selects the preceding ArtifactKey, preserving the review window. An older server rejects the optional context_id field; reload/clear chat after rollback to discard references and load the matching client.

Run `scripts/smoke_conversation.py` explicitly with a privately injected owner token and the intended HTTPS endpoint. It consumes 12 attempts and creates 12 synthetic **owner** history records. Do not reset quota, renew the review window, or clear real reviewer history during this incremental release. Monitor reviewer history separately from shared quota so these test calls are not attributed to Alex.
