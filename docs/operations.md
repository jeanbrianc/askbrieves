# Operations

## Ownership and signals

The demo has one owner and one shared bearer credential. `GET /health` is **liveness only**: it confirms code is responding, not that OpenAI, Treasury, or history is available. `scripts/smoke.py` exercises the authenticated end-to-end path, refusals, and persisted history using a few requests from the daily quota.

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
| 503 | Inspect metadata outcomes, provider service status, secret metadata/IAM, and Treasury source availability. Never disable screening or freshness checks to restore an answer. |
| Pending history | A process died or persistence failed. The 28-second hard Lambda timeout bounds work; cumulative dependency delays can exhaust it. A pending record is not a completed answer. Retry is a new request and consumes quota. |
| Wrong/old rate | Inspect returned observation date/source, compare official Treasury feed, stop serving if integrity is doubtful. Source must be <=7 calendar days old by default. |
| Timeout / throttles | Inspect API latency, Lambda concurrency, and provider rate limits. The gateway integration timeout is 29 seconds, Lambda 28 seconds; no provider retries. The default function reservation is 2. With the optional unreserved setting, other functions can consume shared account capacity. Avoid scaling before understanding costs. |

## Stop, rotate, restore

The template and release script default to `ReservedConcurrency=2`. Verify that the regional account quota can accommodate this while leaving AWS's required unreserved pool available; an account with a total quota of 10 needs at least 12 to reserve two. The preferred deployment retains the function reservation. `ReservedConcurrency=-1` is an explicit fallback that omits the property: set `ASKBRIEVES_RESERVED_CONCURRENCY=-1` when invoking `scripts/deploy.sh` only if sharing account capacity is the intended policy. This does not raise the account quota, reserve capacity, or give the service an isolated concurrency ceiling. API target 1 request/second, burst 2, and the global atomic 100-attempt daily cap remain in force.

Before an emergency stop, inspect and record the actual concurrency configuration. An empty configuration means the function has no reservation; compare it with the stack's `ReservedConcurrency` parameter. Do not guess the restore value.

```bash
aws lambda get-function-concurrency --function-name askbrieves-api --region us-east-1
```

Fast kill switch (authorized operator; stops all Lambda requests including health):

```bash
aws lambda put-function-concurrency --function-name askbrieves-api \
  --reserved-concurrent-executions 0 --region us-east-1
```

Restore only after the incident is understood. If the recorded configuration matched the preferred reservation of two, restore it:

```bash
aws lambda put-function-concurrency --function-name askbrieves-api \
  --reserved-concurrent-executions 2 --region us-east-1
```

If the recorded configuration had a different positive reservation, restore that exact value. If the deployment used the optional unreserved setting (`ReservedConcurrency=-1`), remove the emergency reservation instead:

```bash
aws lambda delete-function-concurrency --function-name askbrieves-api --region us-east-1
```

These are emergency drift operations. Record the incident/change, restore the declared setting, and reconcile with IaC. Revoking the OpenAI key is an additional provider-side cutoff; it does not stop unauthenticated AWS request charges.

Rotate the shared API token by creating a new secret version with a fresh random `token` field in Secrets Manager, distribute privately, and allow up to60 seconds for caches. Rotate the OpenAI project key by updating `api_key` in its secret and revoke the old key after testing. Do not send values through GitHub or chat. The Lambda role can read only the two referenced secrets. Secrets using a customer-managed KMS key require an explicitly scoped `kms:Decrypt` grant; the provided template assumes the AWS-managed Secrets Manager key.

## Releases and rollback

CI runs offline tests, CloudFormation lint, and packaging on Python3.13 without cloud credentials. The release script requires a human-authenticated AWS profile. Package contents are pure Python, deterministic, and named in S3 by SHA-256. Keep the prior `ArtifactKey` from stack parameters before updating.

To roll back code, redeploy `infra/service.json` using the previous `ArtifactKey` and existing parameter values, or use a CloudFormation change set with `UsePreviousValue` for all other parameters. Inspect the change set, execute it, then rerun authenticated smoke checks. Do not restore a previous secret version as part of a code rollback. To verify infrastructure configuration after a release, check the stack status, Lambda runtime/concurrency/environment (ARNs only), IAM resource scope, table encryption/PITR/TTL, log retention, custom TLS domain, disabled default endpoint, and DNS.

State retention is deliberate: the history table, generated API secret, artifact bucket and its TLS policy survive stack deletion. PITR and retained data may still incur charges. DynamoDB TTL is asynchronous and backups can retain older data beyond the API visibility window; this is not a statutory deletion guarantee. For complete teardown, first delete the service stack, then the artifact stack, and explicitly review/export/delete retained resources under a separate authorized cleanup. The externally supplied OpenAI secret and project key are not owned by this stack and require separate cleanup. ACM validation CNAMEs can remain after certificate deletion.
