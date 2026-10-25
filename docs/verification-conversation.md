# Conversation and monthly-peak deployment verification

October 25, 2026. Runtime source commit `132cb6a8596133e5fa6cee1fde14eea380cb687d`, [draft PR #6](https://github.com/jeanbrianc/askbrieves/pull/6).

## Offline and CI evidence

- 331 Python tests and 99 subtests passed, including monthly ties, missing maturity coverage, invalid/future source rows, strict tool/month bounds, exact audience-scoped context reads, expiry, and no-data context retention.
- 32 browser-session tests passed, including follow-up reference propagation, preservation across declines, and reset on chat/access changes. Existing late-callback/session tests remain passing.
- CloudFormation lint and diff checks passed. Pure-Python package built on the owner's M1 Mac.
- [GitHub Validate run](https://github.com/jeanbrianc/askbrieves/actions/runs/40234763914) passed on Python 3.13 / Node.js 22.

## Deployment evidence

- Artifact SHA-256: `f4f964dc1fd9168753b76b8b3c26e5cd16e54311501c31a0aedea214d06704bc` (1,589,170 bytes).
- Artifact: `s3://askbrieves-artifacts-artifacts-lsci3aluirc3/releases/f4f964dc1fd9168753b76b8b3c26e5cd16e54311501c31a0aedea214d06704bc/askbrieves.zip`.
- Change set `conversation-132cb6a8` used the existing template and previous parameters, changing only ArtifactKey. Inspection showed Function and its dependent Integration modified without replacement; no IAM or infrastructure changes.
- DescribeEvents reported successful change-set creation. After execution stack `askbrieves` reached UPDATE_COMPLETE; Lambda was Active / Successful. Its base64 code digest matched the artifact SHA-256.
- Runtime Python 3.13, arm64, 256 MiB, 28-second timeout. Pinned model preserved. Review limit remained 1,000 and deadline remained epoch 1793554527 (November 1, 2026, 12:35:27 PM America/Detroit).
- Live GET /health returned HTTP 200. Live /app.js returned HTTP 200 and matched local reviewed bytes (SHA-256 `af2d316f6401a8c3a1a3bf677744e2c5ab9543cde0e9471f7e25daf5d1ddb070`).
- Real-endpoint POST probes without a token and with an invalid token both returned HTTP 401. Application metadata confirmed healthy/web_asset 200 and unauthorized 401, without prompts or credentials.

## Remaining live acceptance

The authenticated 12-attempt conversation suite has **not run yet**. The local AWS session expired; approval to start sign-in was requested. Deployment and public/auth-failure probes do not prove live model selection or contextual/peak answers. Use the owner token through runtime secret injection to run `scripts/smoke_conversation.py`, then append its controlled evidence. Do not claim authenticated acceptance until it passes. Reviewer history and the shared review grant have not been cleared or reset.
