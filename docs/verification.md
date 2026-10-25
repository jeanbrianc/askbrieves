# Verification record

Local validation on 2026-10-25:

- Full offline test suite passed (exact final count recorded with the PR).
- Both CloudFormation templates passed cfn-lint1.58.0 without warnings.
- Package built on an Apple Silicon Mac using pure Python; no native build dependencies.
- A direct Treasury adapter call successfully fetched the official dated feed. This alone does not establish deployed end-to-end success.

Deployed verification is pending. Before treating this service as ready to hand over, record stack status, package digest, public TLS/liveness, unauthorized-request rejection, a real model-selected/source-backed answer, unrelated/mixed/injection refusals, persisted history, and a sanitized configuration/log readback. Never include the API token, OpenAI key, full AWS payloads, or private question history in this file.
