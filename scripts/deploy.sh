#!/usr/bin/env bash
# Usage: AWS_PROFILE=... bash scripts/deploy.sh REGION OPENAI_SECRET_ARN HOSTED_ZONE_ID [DOMAIN]
set -euo pipefail
export AWS_PAGER=""
task_region="${1:?AWS region required}"
task_secret="${2:?same-region OpenAI secret ARN required}"
task_zone="${3:?public Route 53 hosted zone ID required}"
task_domain="${4:-askbrieves.brianjeanbuilds.com}"
task_stack="${ASKBRIEVES_STACK:-askbrieves}"
task_concurrency="${ASKBRIEVES_RESERVED_CONCURRENCY:--1}"
cd "$(dirname "$0")/.."
python3 -m pytest -q
node --test tests/web_session.test.cjs
cfn-lint infra/bootstrap.json infra/service.json
python3 scripts/package.py
# Read and validate the intended allowance before the first infrastructure write.
# Only an explicit missing-stack response means this is an initial deployment.
task_review_settings="$(python3 - "$task_region" "$task_stack" <<'PY'
import json
import os
import re
import subprocess
import sys
import time


def integer(value, lower, upper):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise ValueError
    result = int(value)
    if not lower <= result <= upper:
        raise ValueError
    return result


def main():
    try:
        region, stack = sys.argv[1:]
        existing = subprocess.run(
            ["aws", "cloudformation", "describe-stacks", "--region", region,
             "--stack-name", stack, "--output", "json"],
            capture_output=True, text=True, check=False,
        )
        previous = {}
        if existing.returncode:
            missing = (r"An error occurred \(ValidationError\) when calling the DescribeStacks operation: "
                       r"Stack with id " + re.escape(stack) + r" does not exist\.?")
            if not re.fullmatch(missing, existing.stderr.strip()):
                raise ValueError
        else:
            stacks = json.loads(existing.stdout)["Stacks"]
            if not isinstance(stacks, list) or len(stacks) != 1:
                raise ValueError
            previous = {p["ParameterKey"]: p["ParameterValue"] for p in stacks[0]["Parameters"]}
        limit = integer(os.environ.get("ASKBRIEVES_REQUEST_LIMIT", previous.get("RequestLimit", "1000")), 1, 1000)
        # Preserve an expired window too: releases must never silently renew it.
        end = integer(os.environ.get("ASKBRIEVES_REVIEW_WINDOW_ENDS_AT",
                                    previous.get("ReviewWindowEndsAt", str(int(time.time()) + 604800))),
                      1, 4102444800)
        print(limit, end)
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print("Unable to read or validate review-window settings; deployment aborted before AWS changes.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
PY
)"
read -r task_request_limit task_review_end <<< "$task_review_settings"
printf 'Review allowance: %s total attempts; seven-day window ends at UTC epoch %s.\n' \
  "$task_request_limit" "$task_review_end"
aws cloudformation deploy --region "$task_region" --stack-name "${task_stack}-artifacts" \
  --template-file infra/bootstrap.json --no-fail-on-empty-changeset --tags Application=askbrieves
task_bucket="$(aws cloudformation describe-stacks --region "$task_region" --stack-name "${task_stack}-artifacts" \
  --query 'Stacks[0].Outputs[?OutputKey==`ArtifactBucket`].OutputValue | [0]' --output text)"
task_sha="$(cat build/sha256.txt)"
task_key="releases/${task_sha}/askbrieves.zip"
aws s3 cp build/askbrieves.zip "s3://${task_bucket}/${task_key}" --region "$task_region" --only-show-errors
aws cloudformation deploy --region "$task_region" --stack-name "$task_stack" \
  --template-file infra/service.json --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides "ArtifactBucket=${task_bucket}" "ArtifactKey=${task_key}" \
    "OpenAISecretArn=${task_secret}" "HostedZoneId=${task_zone}" "DomainName=${task_domain}" \
    "ReservedConcurrency=${task_concurrency}" "RequestLimit=${task_request_limit}" \
    "ReviewWindowEndsAt=${task_review_end}" \
  --tags Application=askbrieves
aws cloudformation describe-stacks --region "$task_region" --stack-name "$task_stack" \
  --query 'Stacks[0].Outputs' --output table
