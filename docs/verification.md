# Verification record

Verified on 2026-10-25. This evidence excludes credentials, private question history, and raw AWS payloads.

- Full offline test suite: **91 passed, 30 subtests passed**.
- Both CloudFormation templates passed cfn-lint 1.58.0 without warnings and AWS ValidateTemplate.
- Pure-Python package builds reproducibly on Apple Silicon, including browser assets. No Docker or native compilation required.
- GitHub Actions runs tests, infrastructure lint, and packaging on Python 3.13 without AWS credentials.
- cfn-guard is not installed; a cfn-guard policy run was not performed. No compliance certification is implied.

## Deployed API acceptance

The `askbrieves-artifacts` and `askbrieves` stacks completed in `us-east-1`. Public HTTPS liveness succeeded at `https://askbrieves.brianjeanbuilds.com/health`. The real model and Treasury lookup passed through the public custom domain.

| Check | Observed result |
|---|---|
| Missing token for question/history | 401 |
| Incorrect token | 401 |
| Extra request fields | 400 |
| 10-year Treasury question | Answered; 5.00%, as of 2026-10-23; request `bb2eaf05-f093-42ff-ab81-dbe7a0d89682` |
| 2-year versus 10-year question | Answered from one dated row: 4.69% / 5.00%; request `06a30601-3ede-4118-a5ed-e3771fcc8dbd` |
| Unrelated joke request | Declined: out_of_scope |
| Instruction override / secret request | Declined: unsafe |
| Mortgage rate request | Declined: out_of_scope |
| Treasury question mixed with malware request | Declined: unsafe |
| Authenticated history | 200; saved answered request found |

Source: [October 2026 Treasury feed](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value_month=202610). These figures document the test and are not a current quote guarantee.

CloudWatch metadata matched returned IDs: single-yield lookup `status=200 outcome=answered duration_ms=3297`; comparison `status=200 outcome=answered duration_ms=1931`; refusals `outcome=declined`; history `status=200 outcome=history`. The atomic daily counter recorded six model attempts for two answers and four refusals. Auth and malformed-input probes did not consume model attempts.

## Configuration readback

- Lambda active, Python 3.13, arm64, 256 MiB, 28-second timeout. No function URL exists.
- Shared account concurrency; no reservation or quota increase. Stack parameter `ReservedConcurrency=-1` matches the deployment default.
- API target throttle 1 request/second, burst 2; default execute-api endpoint disabled (direct probe rejected). Regional custom domain available with TLS 1.2 policy and IPv4/IPv6 support.
- Daily limit 100, history 30 days, maximum data age 7 days; pinned model `gpt-5.4-mini-2026-03-17`.
- DynamoDB encryption, TTL on `expires_at`, and point-in-time recovery enabled. API/Lambda log retention 14 days.
- Runtime IAM scoped to two secrets, one table, one log group; no wildcard allow resources.

## Final branded chat release

- CloudFormation update completed; Lambda active. Artifact SHA-256 `ef6b83d62324c973c23d8f0bafc2ca322ac925c06d3095995dc5610b1a2e80d0` matches Lambda's deployed code digest.
- Immutable artifact: `s3://askbrieves-artifacts-artifacts-lsci3aluirc3/releases/ef6b83d62324c973c23d8f0bafc2ca322ac925c06d3095995dc5610b1a2e80d0/askbrieves.zip`.
- Browser layouts visually checked at desktop and narrow widths. The initial view is one chat screen with the supplied mascot/logo, two suggestions, and a bottom composer; about 25 visible words. The supplied PNG is served byte-for-byte unchanged.
- Example selection, keyboard send, compact access dialog, rejected-token recovery, and restored-question behavior verified in a real browser. Successful authenticated answers and history were verified against the same deployed API using the secret-safe acceptance script.
- Final deployed acceptance suite passed: all browser assets, liveness, missing/incorrect-token rejection, malformed-input rejection, real OpenAI/Treasury lookup and comparison, four scope refusals, and persisted history.
- Final single-yield request: `8ab3efb0-cfbe-410b-828e-d9292c011c23`; comparison: `578103de-f880-4740-8c90-b3c1dc5a00b8`. Both returned the same dated source values shown above.
- GitHub Actions passed for the runtime release. Final documentation changes do not change the deployed package.
