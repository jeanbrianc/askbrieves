#!/usr/bin/env bash
# Usage: AWS_PROFILE=... bash scripts/deploy.sh REGION OPENAI_SECRET_ARN HOSTED_ZONE_ID [DOMAIN]
set -euo pipefail
export AWS_PAGER=""
task_region="${1:?AWS region required}"
task_secret="${2:?same-region OpenAI secret ARN required}"
task_zone="${3:?public Route 53 hosted zone ID required}"
task_domain="${4:-askbrieves.brianjeanbuilds.com}"
task_stack="${ASKBRIEVES_STACK:-askbrieves}"
cd "$(dirname "$0")/.."
python3 -m pytest -q
cfn-lint infra/bootstrap.json infra/service.json
python3 scripts/package.py
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
  --tags Application=askbrieves
aws cloudformation describe-stacks --region "$task_region" --stack-name "$task_stack" \
  --query 'Stacks[0].Outputs' --output table
