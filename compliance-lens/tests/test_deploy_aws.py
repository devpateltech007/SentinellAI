"""The one-click AWS install (Docker plan, stage 6): deploy/aws/.

The CloudFormation template is checked for what keeps the server safe (read-only role,
no inbound port, secrets hidden, the form's free text never in shell code), and the
setup script's config and secrets steps are run for real on made-up values.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from compliancelens import config

DEPLOY = Path(__file__).parents[1] / "deploy" / "aws"
TEMPLATE = yaml.safe_load((DEPLOY / "compliancelens-server.yaml").read_text())
SCRIPT = DEPLOY / "server-setup.sh"
RESOURCES = TEMPLATE["Resources"]
FREE_TEXT = [  # typed by a person: must reach the server only through the secret
    "Company",
    "ScreenshotBucket",
    "AllowAwsUsers",
    "GitHubToken",
    "AiModel",
    "AiApiKey",
    "DashboardPassword",
]


def resources_of(kind):
    return {name: r for name, r in RESOURCES.items() if r["Type"] == kind}


# --- the template ----------------------------------------------------------------


def test_keys_and_passwords_are_hidden_and_go_into_the_secret():
    params = TEMPLATE["Parameters"]
    for name in ("GitHubToken", "AiApiKey", "DashboardPassword"):
        assert params[name]["NoEcho"] is True, name
    assert params["DashboardPassword"]["MinLength"] >= 12
    [secret] = resources_of("AWS::SecretsManager::Secret").values()
    fields = secret["Properties"]["SecretString"]["Fn::ToJsonString"]
    assert {v["Ref"] for v in fields.values()} >= set(FREE_TEXT)


def test_the_servers_role_can_only_read():
    [role] = resources_of("AWS::IAM::Role").values()
    props = role["Properties"]
    principal = props["AssumeRolePolicyDocument"]["Statement"][0]["Principal"]
    assert principal == {"Service": "ec2.amazonaws.com"}
    managed = {arn["Fn::Sub"].rsplit("/", 1)[1] for arn in props["ManagedPolicyArns"]}
    assert managed == {"SecurityAudit", "AmazonSSMManagedInstanceCore"}
    [inline] = props["Policies"]
    [statement] = inline["PolicyDocument"]["Statement"]
    assert statement["Action"] == "secretsmanager:GetSecretValue"
    assert statement["Resource"] == {"Ref": "Settings"}  # its own secret, nothing else


def test_nothing_can_connect_in():
    [group] = resources_of("AWS::EC2::SecurityGroup").values()
    assert "SecurityGroupIngress" not in group["Properties"]
    assert not resources_of("AWS::EC2::SecurityGroupIngress")


def test_the_server_uses_imdsv2_and_an_encrypted_disk():
    server = RESOURCES["Server"]["Properties"]
    assert server["MetadataOptions"]["HttpTokens"] == "required"
    # Docker's network adds a hop; the containers use the host network anyway.
    assert server["MetadataOptions"]["HttpPutResponseHopLimit"] == 2
    [disk] = server["BlockDeviceMappings"]
    assert disk["Ebs"]["Encrypted"] is True


def test_user_data_holds_no_free_text():
    script = RESOURCES["Server"]["Properties"]["UserData"]["Fn::Base64"]["Fn::Sub"]
    for name in FREE_TEXT:
        assert "${" + name + "}" not in script, name
    # What it does use is checked by the template's patterns, or made by AWS.
    for name in ("SourceRef", "SourceRepo"):
        assert "AllowedPattern" in TEMPLATE["Parameters"][name]
        assert "'" not in TEMPLATE["Parameters"][name]["AllowedPattern"]
    assert "deploy/aws/server-setup.sh" in script


def test_session_access_is_optional_and_limited_to_this_server():
    policy = RESOURCES["SessionAccess"]
    assert policy["Condition"] == "HasSessionUser"
    start = policy["Properties"]["PolicyDocument"]["Statement"][0]
    assert start["Action"] == "ssm:StartSession"
    resources = [r["Fn::Sub"] for r in start["Resource"]]
    assert any(r.endswith(":instance/${Server}") for r in resources)
    assert not any(r.endswith(":instance/*") for r in resources)


# --- the setup script ----------------------------------------------------------------

SECRET = {
    "company": 'O\'Brien & Sons "Labs" $(touch pwned) `id` #1',
    "github_org": "example-org",
    "github_repo": "example-repo",
    "github_branch": "main",
    "aws_region": "eu-west-1",
    "screenshot_bucket": "",
    "allow_aws": " svc-a, ,svc-b ",
    "github_token": "ghp_test$(touch pwned)",
    "ai_model": "openai/gpt-6-luna",
    "ai_api_key": "",
    "dashboard_password": "pa$HOME${USER}\\w'q'\"dq\"#x",
}


def run_setup(app, secret, steps="config secrets"):
    (app / "config").mkdir(exist_ok=True)
    secret_file = app.parent / "secret.json"
    secret_file.write_text(json.dumps(secret))
    env = {**os.environ, "APP_DIR": str(app), "SECRET_FILE": str(secret_file), "STEPS": steps}
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, cwd=app, capture_output=True, text=True, timeout=60
    )


def read_env(path):
    """.env as Compose reads it: KEY="value" with \\ \" and $$ escapes."""
    values = {}
    for line in path.read_text().splitlines():
        key, _, raw = line.partition("=")
        assert raw.startswith('"') and raw.endswith('"'), line
        out, i, body = [], 0, raw[1:-1]
        while i < len(body):
            pair = body[i : i + 2]
            if pair in ("\\\\", '\\"', "$$"):
                out.append(pair[1])
                i += 2
            else:
                assert body[i] not in '"$', f"unescaped {body[i]!r} in {key}"
                out.append(body[i])
                i += 1
        values[key] = "".join(out)
    return values


@pytest.fixture
def app(tmp_path):
    if not shutil.which("bash") or not shutil.which("python3"):  # pragma: no cover
        pytest.skip("needs bash and python3")
    folder = tmp_path / "app"
    folder.mkdir()
    return folder


def test_settings_and_env_are_written_from_the_secret(app):
    done = run_setup(app, SECRET)
    assert done.returncode == 0, done.stderr
    assert not list(app.parent.rglob("pwned"))  # no value was run as a command

    context = config.resolve(app / "config" / "settings.yaml", environ={})
    assert context.get("company") == SECRET["company"]
    assert context.repository == "example-org/example-repo"
    assert context.get("aws.region") == "eu-west-1"
    assert context.get("aws.screenshot_bucket") is None  # empty: left out
    assert context.get("hr.allow_aws") == ["svc-a", "svc-b"]

    env_file = app / ".env"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    env = read_env(env_file)
    assert env["GITHUB_TOKEN"] == SECRET["github_token"]
    assert env["DASHBOARD_PASSWORD"] == SECRET["dashboard_password"]  # $, quotes, \ kept
    assert env["COMPLIANCELENS_AI_MODEL"] == "openai/gpt-6-luna"
    assert "COMPLIANCELENS_AI_API_KEY" not in env  # empty: left out
    assert "AWS_PROFILE" not in env  # the server's role, never a profile
    assert len(env["DASHBOARD_SESSION_SECRET"]) >= 40
    for value in SECRET.values():
        assert value == "" or value not in done.stdout + done.stderr  # nothing printed


def test_a_value_with_a_line_break_is_refused(app):
    done = run_setup(app, {**SECRET, "dashboard_password": "two\nlines"}, steps="secrets")
    assert done.returncode != 0
    assert "DASHBOARD_PASSWORD contains a line break" in done.stderr
    assert (app / ".env").read_text() == ""  # the empty file from the start, nothing more


def test_an_unknown_step_stops_the_setup(app):
    done = run_setup(app, SECRET, steps="config nonsense")
    assert done.returncode == 2
    assert "unknown step: nonsense" in done.stdout
