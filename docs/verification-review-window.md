# Seven-day review allowance verification

October 25, 2026. This release replaces the UTC daily allowance with **1,000 total question attempts over one fixed seven-day window**. Owner and reviewer questions share the allowance; there is no midnight reset. Credential values are excluded from this document.

## Implementation and offline evidence

The active interval is `[ReviewWindowEndsAt - 604800, ReviewWindowEndsAt)`. A conditional DynamoDB `ADD` claims each attempt against `quota#review#<end epoch>` / `total`, with TTL two days after the end. Updating code, crossing midnight, or rotating a token preserves usage. Only deliberately selecting a new deadline creates a new grant; earlier counters are retained for audit.

Authentication and input validation precede the claim. Exhaustion returns 429 with `review_limit_exceeded`; an inactive window returns 403 with `review_window_closed`. Both stop before history/provider work. Missing or invalid window configuration fails closed with 503. History reads do not consume attempts. The deploy helper preserves the configured limit and deadline even after expiry, and aborts on AWS read/authentication failures rather than silently creating a new window.

- `python3 -m pytest -q`: 298 tests and 99 subtests passed.
- `node --test tests/web_session.test.cjs`: 31 tests passed, including updated expiry/quota messages and the preceding session-ownership protections.
- CloudFormation lint, JavaScript/shell syntax, documentation shell blocks, and diff checks passed.
- An independent static patch review reported no actionable findings; its 115 focused tests passed. This is not a new repository security assessment or proof of live dependency behavior.

## Deployment and activation

Live validation and fresh reviewer-window activation are pending. The intended sequence is to validate real dependencies in a separate window, probe exhaustion and expiry, then explicitly select a new seven-day grant, align reviewer credential expiry, and remove reviewer test history. Deployment proof and the exact activation deadline will be recorded here after execution. No claim of a fresh deployed allowance is made by this initial document.
