"""Execute the release shell with fake CLI boundaries; never contact AWS."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

import pytest


DEPLOY = Path(__file__).resolve().parents[1] / "scripts" / "deploy.sh"


@pytest.fixture
def release(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(DEPLOY, root / "scripts" / "deploy.sh")
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "aws-calls.jsonl"
    python = commands / "python3"
    python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ] && [ "$2" = "pytest" ]; then exit 0; fi\n'
        'if [ "$1" = "scripts/package.py" ]; then\n'
        '  mkdir -p build\n'
        "  printf '%s\\n' fixture-sha > build/sha256.txt\n"
        '  exit 0\n'
        "fi\n"
        f"exec {shlex.quote(sys.executable)} \"$@\"\n"
    )
    for name in ("node", "cfn-lint"):
        (commands / name).write_text("#!/bin/sh\nexit 0\n")
    aws = commands / "aws"
    aws.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['AWS_TEST_LOG'], 'a') as f: f.write(json.dumps(args) + '\\n')\n"
        "if args[:2] == ['cloudformation', 'describe-stacks']:\n"
        "    stack = args[args.index('--stack-name') + 1]\n"
        "    if stack.endswith('-artifacts'):\n"
        "        print('fixture-artifacts-bucket')\n"
        "    elif '--query' in args:\n"
        "        print('[]')\n"
        "    elif os.environ.get('AWS_TEST_ERROR'):\n"
        "        print(os.environ['AWS_TEST_ERROR'], file=sys.stderr); sys.exit(255)\n"
        "    else:\n"
        "        print(os.environ['AWS_TEST_STACK'])\n"
        "elif args[:2] in (['cloudformation', 'deploy'], ['s3', 'cp']):\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('Unexpected fake AWS operation')\n"
    )
    for executable in commands.iterdir():
        executable.chmod(0o755)

    def run(parameters=None, error=None, overrides=None, raw_stack=None):
        environ = os.environ.copy()
        for key in list(environ):
            if key.startswith("ASKBRIEVES_"):
                del environ[key]
        environ.update(
            PATH=str(commands) + os.pathsep + environ["PATH"],
            LC_ALL="C", AWS_TEST_LOG=str(log), ASKBRIEVES_STACK="fixture",
            AWS_TEST_STACK=raw_stack if raw_stack is not None else json.dumps({"Stacks": [{
                "Parameters": [{"ParameterKey": key, "ParameterValue": value}
                               for key, value in (parameters or {}).items()]
            }]}),
        )
        if error is not None:
            environ["AWS_TEST_ERROR"] = error
        else:
            environ.pop("AWS_TEST_ERROR", None)
        environ.update(overrides or {})
        result = subprocess.run(
            ["bash", str(root / "scripts" / "deploy.sh"), "us-east-1",
             "arn:aws:secretsmanager:us-east-1:000000000000:secret:fixture", "ZFIXTURE", "review.example.com"],
            cwd=root, env=environ, text=True, capture_output=True,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return result, calls

    return run


def service_parameters(calls):
    call = next(args for args in calls if args[:2] == ["cloudformation", "deploy"]
                and args[args.index("--stack-name") + 1] == "fixture")
    start = call.index("--parameter-overrides") + 1
    end = call.index("--tags")
    return dict(value.split("=", 1) for value in call[start:end])


def assert_no_aws_writes(calls):
    assert len(calls) == 1
    assert calls[0][:2] == ["cloudformation", "describe-stacks"]


def test_fresh_deployment_opens_one_seven_day_thousand_attempt_window(release):
    before = int(time.time())
    result, calls = release(error="An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id fixture does not exist")
    after = int(time.time())
    assert result.returncode == 0, result.stderr
    parameters = service_parameters(calls)
    assert parameters["RequestLimit"] == "1000"
    assert before + 604800 <= int(parameters["ReviewWindowEndsAt"]) <= after + 604800
    assert "DailyRequestLimit" not in parameters
    assert "1000 total attempts" in result.stdout


def test_code_update_preserves_expired_window_and_existing_limit(release):
    result, calls = release(parameters={"ReviewWindowEndsAt": "1700000000", "RequestLimit": "700"})
    assert result.returncode == 0, result.stderr
    parameters = service_parameters(calls)
    assert parameters["ReviewWindowEndsAt"] == "1700000000"
    assert parameters["RequestLimit"] == "700"


def test_explicit_operator_settings_open_new_window_without_using_old_daily_limit(release):
    result, calls = release(
        parameters={"ReviewWindowEndsAt": "1700000000", "RequestLimit": "700", "DailyRequestLimit": "100"},
        overrides={"ASKBRIEVES_REVIEW_WINDOW_ENDS_AT": "1900000000", "ASKBRIEVES_REQUEST_LIMIT": "1000"},
    )
    assert result.returncode == 0, result.stderr
    assert service_parameters(calls)["ReviewWindowEndsAt"] == "1900000000"
    assert service_parameters(calls)["RequestLimit"] == "1000"


def test_legacy_daily_stack_migration_gets_a_new_seven_day_allowance(release):
    before = int(time.time())
    result, calls = release(parameters={"DailyRequestLimit": "100"})
    assert result.returncode == 0, result.stderr
    parameters = service_parameters(calls)
    assert parameters["RequestLimit"] == "1000"
    assert int(parameters["ReviewWindowEndsAt"]) >= before + 604800


@pytest.mark.parametrize("name,value", [
    ("ASKBRIEVES_REQUEST_LIMIT", "0"),
    ("ASKBRIEVES_REQUEST_LIMIT", "1001"),
    ("ASKBRIEVES_REQUEST_LIMIT", "1.5"),
    ("ASKBRIEVES_REQUEST_LIMIT", ""),
    ("ASKBRIEVES_REVIEW_WINDOW_ENDS_AT", "0"),
    ("ASKBRIEVES_REVIEW_WINDOW_ENDS_AT", "4102444801"),
    ("ASKBRIEVES_REVIEW_WINDOW_ENDS_AT", "1.5"),
    ("ASKBRIEVES_REVIEW_WINDOW_ENDS_AT", ""),
])
def test_invalid_operator_settings_fail_before_aws_writes(release, name, value):
    result, calls = release(overrides={name: value})
    assert result.returncode != 0
    assert_no_aws_writes(calls)
    assert "deployment aborted before AWS changes" in result.stderr


@pytest.mark.parametrize("error", [
    "Unable to locate credentials. PRIVATE ERROR MUST NOT BE PRINTED",
    "An error occurred (AccessDenied) when calling the DescribeStacks operation: PRIVATE ERROR MUST NOT BE PRINTED",
    "An error occurred (ValidationError) when calling the DescribeStacks operation: invalid stack name PRIVATE ERROR MUST NOT BE PRINTED",
    "An error occurred (ValidationError) when calling the DescribeStacks operation: Stack with id different-stack does not exist",
])
def test_read_failure_is_not_treated_as_a_fresh_stack(release, error):
    result, calls = release(error=error)
    assert result.returncode != 0
    assert_no_aws_writes(calls)
    assert "PRIVATE ERROR" not in result.stderr


@pytest.mark.parametrize("raw_stack", ["not-json", "{}", '{"Stacks": []}'])
def test_malformed_stack_readback_fails_closed(release, raw_stack):
    result, calls = release(raw_stack=raw_stack)
    assert result.returncode != 0
    assert_no_aws_writes(calls)
