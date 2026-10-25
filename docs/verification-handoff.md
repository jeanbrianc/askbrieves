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

See the README for hidden-prompt invocations and the runbook for reviewer rotation and scoped history cleanup. Live checks use real dependencies and consume the shared daily allowance; they are never run by offline tests or CI. Deployment, live acceptance, random-token rotation, and final cleanup evidence are recorded below after execution.
