# Reviewer handoff verification

October 25, 2026. This release fixes browser session ownership, makes the extended live acceptance reproducible, and rotates the deployed reviewer credential privately. No credential values belong in this document or public PR evidence.

## Browser regression and compatibility

The original browser script retained the preceding audience's transcript after a token switch, disconnect, or empty history response. An aborted request could restore the preceding question afterward. This required an already-used browser tab; server-side audience partitioning was not bypassed.

The fix invalidates the session before abort/reset. Credential replacement, disconnect, a current-session 401, and page exit clear local private content. Every asynchronous question/history completion checks session ownership, including delayed fetch, response parsing, errors, and cleanup. Old authentication failures cannot disconnect a newer session, and old cleanup cannot release its active request handle. Empty history restores working welcome examples. A draft typed while disconnected remains available after first connecting.

`node --test tests/web_session.test.cjs` executes the actual chat script with synthetic DOM/fetch fixtures. All 29 tests pass on the candidate; replaying the committed pre-fix script produces 23 failures and six passing controls. The tests cover the original trigger, stale success/error/abort/401/JSON/finally paths, page exit, and ordinary question/retry/history/example workflows. This is stronger session-behavior coverage than the earlier asset/header checks, but does not alone establish browser-engine compatibility.

An independent pre-patch boundary investigation and one independent patch review traced the affected lifecycle paths. The latter found no concrete surviving bypass or regression. These are focused fix checks, not a replacement or amendment of the earlier sealed repository security assessment.

## Reproducible checks

- `python3 -m pytest -q`: 243 tests and 99 subtests passed.
- `node --test tests/web_session.test.cjs`: 29 passed.
- JavaScript syntax, shell syntax, CloudFormation lint, and `git diff --check` passed.
- CI and the human-invoked deployment script now run the offline JavaScript suite. Node.js22 is a development/test dependency only; no npm package or frontend build is added to production.
- `scripts/smoke.py` retains the original 11 live cases. Optional `scripts/smoke_review.py` adds exactly 13 cases covering seven concepts, latest/historical curve, dated change, refusals, persisted results, and both directions of audience isolation. It rejects invalid/missing/equal credentials before network use and cannot read secrets or delete records.

See the README for hidden-prompt invocations and the runbook for reviewer rotation and scoped history cleanup. Live checks use real dependencies and consume the shared daily allowance; they are never run by offline tests or CI.

## Deployment and live acceptance

- Runtime-source commit: `33c68509798177683ad67b9b121d32e26f634210`. Subsequent verification-document edits do not change the deployed package.
- [Runtime-source CI](https://github.com/jeanbrianc/askbrieves/actions/runs/40214976097) passed Python3.13 tests, Node.js22 session tests, template lint, and packaging.
- Package SHA-256: `a83e24294c7ad0328edc867d94fef86a2f986d850fd3346c1e90fd5c8a28b851` (1,586,022 bytes).
- Artifact: `s3://askbrieves-artifacts-artifacts-lsci3aluirc3/releases/a83e24294c7ad0328edc867d94fef86a2f986d850fd3346c1e90fd5c8a28b851/askbrieves.zip`.
- Change set `handoff-sessions-33c68509` modified Function and Integration without replacement. The stack reached `UPDATE_COMPLETE`, Lambda update succeeded, and its code digest matched the package. The live `/app.js` bytes also matched the reviewed source.
- Daily limit100, history30days, pinned model, timeout28seconds, secret-ARN-only configuration, and shared concurrency remained unchanged. No new infrastructure resources or IAM permissions were added.
- The committed baseline suite passed all 11 cases and found all 11 saved results. The committed extended suite passed all 13 cases and verified saved statuses, owner/reviewer separation, and the inability to select the owner audience through query parameters.

The real in-app browser also ran the unmodified chat assets against an isolated localhost API with synthetic owner/reviewer histories. Owner history was displayed first; changing credentials removed its transcript and draft. Loading empty reviewer history retained the welcome state, its example buttons remained usable, and disconnect cleared the composer and connection. The fixture made no AWS/provider calls and was stopped afterward. Browser lifecycle races additionally have the deferred-response regression coverage above; this is not a cross-browser certification.

Sampled application metadata from `/aws/lambda/askbrieves-api` correlated synthetic live requests:

```text
052326ee-9c25-4686-9c99-000bdc18f560 200 answered  872ms (basis point)
8026355e-bc0b-489c-ba2c-9f39ff10b4bf 200 answered 1649ms (latest curve)
2b459ca1-42b3-4121-9258-4cee2ff67a21 200 answered 1429ms (historical curve)
454d39df-33d3-4058-94b2-2be1c8764d79 200 answered 1138ms (dated change)
6608e478-860d-4404-baa6-67b0df847683 200 declined  967ms (secret request)
```

These are observed timings, not latency guarantees. No prompts, answers, credentials, or provider bodies were emitted by these metadata logs.

## Credential rotation and clean handoff

The reviewer token was replaced in the existing Secrets Manager document with a value generated from 32 cryptographically random bytes (43 URL-safe characters). The owner token and the existing expiry, **2026-11-08 15:14:23 UTC**, were preserved. The new value was not printed or saved to local files, source, CI, public documentation, or PR comments; the owner retrieves it privately from Secrets Manager for distribution.

After acceptance completed, a scoped transaction removed exactly 13 reviewer test records. Consistent queries confirmed zero records in `history#reviewer`; owner-history keys were unchanged by cleanup and the daily usage counter was not reset. Final read-only endpoint verification returned:

| Check | Result |
|---|---|
| New reviewer credential, `GET /history` | 200, `items: []` |
| Previous reviewer credential, `GET /history` | 401 |
| Preserved owner credential, `GET /history` | 200 |

No further question or smoke request was made after cleanup. New reviewer questions will naturally create new records. Provider hard-spend-limit configuration remains a separate owner-controlled setting; this release documents it and does not claim to configure or verify it.
