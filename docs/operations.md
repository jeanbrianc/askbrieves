# Operations

## Ownership and signals

The demo has an owner credential and an optional expiring reviewer credential. Histories use separate fixed partitions; a reviewer cannot request the owner's partition. People sharing the reviewer credential share that audience's history. `GET /health` is liveness only, not a dependency check. Every accepted question, including explanations and refusals, consumes one global daily attempt.

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
| 429 | Gateway burst/rate capacity or global daily limit. Daily count resets by UTC date; declined/failed attempts consume quota. Do not raise the limit to silence unexplained load. |
| 200 `no_data` | The exact requested date or maturity was not published. Check the readable monthly `source_url` and XML `data_url`; do not replace a weekend/holiday with a neighboring date. This is a domain result, not a dependency outage. |
| 503 | Inspect metadata outcomes, provider service status, secret metadata/IAM, and Treasury source availability or invalid data. Never disable screening, date validation, or freshness checks to restore an answer. |
| Pending history | A process died or persistence failed. The 28-second hard Lambda timeout bounds work; cumulative dependency delays can exhaust it. A pending record is not a completed answer. Retry is a new request and consumes quota. |
| Wrong/old rate | Inspect each returned observation date and official source. Latest observations must be <=7 calendar days old by default; explicit historical dates must match exactly and lie between 1990-01-02 and today's New York date. A historical result is not subject to the latest-data freshness window. Stop serving if integrity is doubtful. |
| Timeout / throttles | Inspect API latency, Lambda concurrency, and provider rate limits. The gateway integration timeout is 29 seconds, Lambda 28 seconds; no provider retries. Lambda shares account concurrency capacity by default, so other functions can consume that capacity. Avoid scaling before understanding costs. |

A question can select at most two maturities and two dates, with `latest` allowed alongside one exact date. One OpenAI call selects the bounded lookup; Python validates dates and maturities. Up to three monthly source downloads cover the requested dates and any latest-month fallback. Single-date evidence retains the `as_of`/`rates` shape; a date comparison uses `evidence.observations`. Each observation links to a readable monthly table (`source_url`) and its raw XML (`data_url`). No AWS resources or deployment parameters change for historical support.

## Stop, rotate, restore

The template and release script default to `ReservedConcurrency=-1`, which omits a reservation and shares existing account capacity. The script does not request a quota increase. A positive `ASKBRIEVES_RESERVED_CONCURRENCY` setting is optional and requires enough regional capacity. Per-route API targets of 1 request/second, burst 2, and the global atomic 100-attempt daily cap remain in force. These are not one application-wide request bucket or an AWS spending ceiling.

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

`scripts/smoke.py` creates 11 owner/test history records. Optional `scripts/smoke_review.py` requires distinct owner and reviewer tokens and creates 13 reviewer records while checking all seven concepts, curve/date changes, refusals, and history isolation. Both consume the shared daily allowance. Run them explicitly against the intended HTTPS endpoint; offline tests never invoke either suite. The public scripts deliberately cannot delete history or read AWS secrets.

Before handing a tested reviewer audience to another person, an authorized operator may query the actual stack's `HistoryTable` with `pk = history#reviewer` and delete only those returned keys. Preserve owner `pk = history` and all `quota#...` records; do not reset the quota to erase test usage. Ensure no question is pending, then verify a consistent full-partition query and authenticated `GET /history` both return zero records. Avoid a new question or another smoke run after cleanup. This clears active application history; retained backups/PITR have their documented retention behavior.

Confirm an enforced spend limit in a dedicated OpenAI project separately from spend alerts. The application does not configure provider billing controls, and AWS request/transfer costs remain outside those limits. The `Application` cost allocation tag must be available and activated before Cost Explorer can attribute costs reliably; newly created or unallocated resources returning an empty cost result are not proof of zero spend.

Rotate the OpenAI project key in its separate `api_key` secret and revoke the old key after testing. Never commit credentials or post them in public issues. Runtime IAM still reads only the two existing secrets. A customer-managed KMS key needs scoped `kms:Decrypt`; the template assumes the AWS-managed Secrets Manager key.

## Releases and rollback

CI runs Python tests, offline JavaScript session tests on Node.js22, CloudFormation lint, and packaging without cloud credentials. Node is a development/test requirement only; the deployed function remains pure Python with browser JavaScript assets. The release script requires a human-authenticated AWS profile. Package contents are deterministic and named in S3 by SHA-256. Keep the prior `ArtifactKey` from stack parameters before updating.

To roll back code, redeploy `infra/service.json` using the previous `ArtifactKey` and existing parameter values, or use a CloudFormation change set with `UsePreviousValue` for all other parameters. Inspect the change set, execute it, then rerun authenticated smoke checks. Do not restore a previous secret version as part of a code rollback. To verify infrastructure configuration after a release, check the stack status, Lambda runtime/concurrency/environment (ARNs only), IAM resource scope, table encryption/PITR/TTL, log retention, custom TLS domain, disabled default endpoint, and DNS.

State retention is deliberate: the history table, generated API secret, artifact bucket and its TLS policy survive stack deletion. PITR and retained data may still incur charges. DynamoDB TTL is asynchronous and backups can retain older data beyond the API visibility window; this is not a statutory deletion guarantee. For complete teardown, first delete the service stack, then the artifact stack, and explicitly review/export/delete retained resources under a separate authorized cleanup. The externally supplied OpenAI secret and project key are not owned by this stack and require separate cleanup. ACM validation CNAMEs can remain after certificate deletion.
