# Reviewer capabilities and public-source review

Verified October 25, 2026 against https://askbrieves.brianjeanbuilds.com. Runtime source: `f685c2706be11e803260fdc4fa62e3b7298c66a0`. Subsequent README/evidence edits do not change the deployed package.

## Release

- 221 tests and 99 subtests passed; JavaScript syntax and CloudFormation lint passed. [Runtime-source CI](https://github.com/jeanbrianc/askbrieves/actions/runs/40205240997) also passed on Python 3.13.
- Package SHA-256: `d060da883ca560d9ef53341300b05e6060882263c4b6c642ca769c57b9544f4c` (1,585,666 bytes).
- Artifact: `s3://askbrieves-artifacts-artifacts-lsci3aluirc3/releases/d060da883ca560d9ef53341300b05e6060882263c4b6c642ca769c57b9544f4c/askbrieves.zip`.
- CloudFormation change set `reviewer-capabilities-f685c270` changed Function and Integration without replacement. Stack reached `UPDATE_COMPLETE`; Lambda update succeeded and its code digest matched the package. No IAM, table, resource, quota, or concurrency changes.
- Readback: Python 3.13 / arm64, daily attempt limit 100, history 30 days, secret references only in environment, default execute-api endpoint disabled, no concurrency reservation, all four S3 public-access blocks enabled.

## Real endpoint acceptance

The normal `scripts/smoke.py` suite passed using runtime-injected credentials: public assets/health, unauthorized and invalid-token rejection, schema validation, latest and historical lookups, dated comparisons, exact-date no-data handling, refusals, and all 11 persisted synthetic results.

An additional credential-safe acceptance process tested the reviewer audience using the real OpenAI planner and public source adapter:

| Question / check | Observed result |
|---|---|
| What is a basis point? | Saved `basis_point` explanation, SEC source |
| What does a Treasury yield mean? | Saved `treasury_yield` explanation |
| What is a yield curve? | Saved `yield_curve` explanation |
| What does an inverted yield curve mean? | Saved `yield_curve_inversion` explanation |
| What is a yield spread? | Saved `yield_spread` explanation with both references |
| Is a Treasury yield the same as a bank APY? | Saved `yield_vs_apy` explanation |
| How does the federal funds rate differ from Treasury yields? | Saved conceptual explanation, Federal Reserve and Treasury sources |
| Is the yield curve inverted? | October 23, 2026: 2-year 4.69%, 10-year 5.00%, +31 bps; segment upward sloping |
| Was the 2-year/10-year curve inverted on October 23, 2025? | 3.48% and 4.01%, +53 bps; segment upward sloping |
| 10-year change between October 22 and 23, 2025 | Two exact observations: 3.97% and 4.01% |
| Unrelated founding-date question, API-key request, current Fed-rate quote | All declined |
| Reviewer history | All 13 synthetic results persisted; owner records absent |
| Reviewer requests `/history?principal=owner` | Audience unchanged; owner records absent |
| Owner history after reviewer use | Owner token still works; reviewer records absent |

The original owner credential was preserved. A separate reviewer credential was stored privately in Secrets Manager with expiry **2026-11-08 15:14:23 UTC**. No credential value is included in this repository. The two audiences share the global daily allowance; reviewer history is shared by anyone possessing that credential. Expiry and malformed-secret edge cases are covered in unit tests, not by changing the live clock or disrupting credentials.

Browser acceptance also signed in with reviewer access, submitted the curve question, displayed its answer and readable Treasury citation, and confirmed the footer's GitHub destination. The temporary browser session was closed after verification.

Sampled CloudWatch metadata correlated these synthetic requests without prompts, answers, tokens or provider bodies:

```text
f6862557-faf8-4ae7-b3b1-bf94719f951a  200 answered  791ms  (basis point)
8fdec9a9-0a23-4058-a34a-eb31d03456b3  200 answered 1368ms  (latest curve)
f7e2487a-b16d-422c-ab0f-a0ecf3ecf89c  200 answered 1344ms  (historical curve)
6ae5d69e-cf5f-4891-b22d-2ebbc9171f69  200 answered 1615ms  (dated change)
8faa32c2-f43b-4ad4-9681-d8b074ee8435  200 declined  916ms  (secret request)
```

The log query was a bounded sample, not a comprehensive log audit. These timings are observations, not latency guarantees.

## Security assessment and disclosure hygiene

Codex Security Standard scan `922adef9-d71d-4ff5-b2e7-64696b1d1baf` completed on the runtime-source commit above with **zero confirmed reportable findings**. An independent baseline reviewed all 30 tracked text files; architecture and focused investigations traced authentication, reviewer expiry/history, model tools, network/XML, browser rendering, IAM, CI and release controls. Coverage was complete for the declared source scope, with PNG decoder/compressed-content behavior excluded beyond format/credential-signature checks.

Separately, a release-hygiene review checked the earlier source/history inventory (29 files, 65 historical blobs, nine commits/messages); no usable credential or private key was found. The added runtime/source changes likewise contain no credential values. The repository is public; reviewers obtain access credentials privately.

This was an offline source assessment, not a penetration test, cloud-drift audit, dependency-advisory audit, or compliance certification. The live acceptance/readbacks above are separate evidence. Probabilistic scope classification, shared demo audiences/allowance, and a human-controlled deployment remain explicit limits. Before production multi-client use, adopt per-client identity, stronger credentials, edge/per-client abuse controls and owned paging as described in the README.
