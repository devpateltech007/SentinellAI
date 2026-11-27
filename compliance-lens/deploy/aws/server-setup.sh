#!/usr/bin/env bash
# First-boot setup of ComplianceLens on an EC2 server (Docker plan, stage 6).
#
# The CloudFormation template (compliancelens-server.yaml) clones the repository and runs
# this script as root. Everything the person typed into the stack's form (company,
# GitHub organization, tokens, AI key, dashboard password) is read from ONE Secrets
# Manager secret, never pasted into shell code, so no value can break or inject a command.
#
# Environment:
#   APP_DIR      the compliance-lens folder           (default /opt/compliancelens/compliance-lens)
#   SECRET_ID    the secret's ARN or name             (the template sets it)
#   SECRET_FILE  read the secret's JSON from this file instead (tests)
#   STEPS        which steps to run, in order         (default: all of them)
#
# Steps: packages build config secrets start schedule (the image must exist before the
# secret can be read through it). Log: /var/log/compliancelens-setup.log.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/compliancelens/compliance-lens}"
STEPS="${STEPS:-packages build config secrets start schedule}"
COMPOSE=(docker compose -f docker-compose.server.yml)
APP_UID=1000 # the image's `app` user, who writes evidence, reports, logs and the database

say() { printf '[compliancelens-setup] %s\n' "$*"; }

# The secret's JSON (one object of strings) on stdout.
read_secret() {
    if [ -n "${SECRET_FILE:-}" ]; then
        cat "$SECRET_FILE"
        return
    fi
    : "${SECRET_ID:?SECRET_ID is not set}"
    # The image has boto3 and reaches the server's IAM role on the host network.
    "${COMPOSE[@]}" run --rm -T -e SECRET_ID --entrypoint python audit -c \
        'import boto3, os; print(boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["SECRET_ID"])["SecretString"])'
}

step_packages() {
    say "installing Docker, Compose and make"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -q
    apt-get install -y -q docker.io docker-compose-v2 make python3 git
    systemctl enable --now docker
}

step_config() {
    say "writing config/settings.yaml from the stack's settings"
    read_secret | python3 -c '
import json, sys

s = json.load(sys.stdin)
q = json.dumps  # a JSON string is a valid YAML string, quotes and all

def users(text):
    return "[" + ", ".join(q(u.strip()) for u in text.split(",") if u.strip()) + "]"

lines = [
    "# Written by deploy/aws/server-setup.sh from the CloudFormation stack (no secrets here).",
    "company: " + q(s["company"]),
    "github:",
    "  org: " + q(s["github_org"]),
    "  repo: " + q(s["github_repo"]),
    "  branch: " + q(s.get("github_branch") or "main"),
    "aws:",
    "  region: " + q(s["aws_region"]),
]
if s.get("screenshot_bucket"):
    lines.append("  screenshot_bucket: " + q(s["screenshot_bucket"]))
lines += [
    "hr:",
    "  employees_file: data/employees.csv",
    "  allow_aws: " + users(s.get("allow_aws", "")),
    "  allow_github: []",
]
open("config/settings.yaml", "w").write("\n".join(lines) + "\n")
'
}

step_build() {
    say "building the Docker image"
    GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || true)" "${COMPOSE[@]}" build
}

step_secrets() {
    say "writing .env from the secret (values never printed)"
    # shellcheck disable=SC2016  # the $ signs below are Python text, meant literally
    (umask 077 && read_secret | python3 -c '
import json, secrets, sys

s = json.load(sys.stdin)
env = {
    "GITHUB_TOKEN": s.get("github_token", ""),
    "COMPLIANCELENS_AI_MODEL": s.get("ai_model", ""),
    "COMPLIANCELENS_AI_API_KEY": s.get("ai_api_key", ""),
    "DASHBOARD_PASSWORD": s.get("dashboard_password", ""),
    # Keeps dashboard sign-ins valid across restarts; made here, never leaves the server.
    "DASHBOARD_SESSION_SECRET": secrets.token_urlsafe(32),
}
for name, value in env.items():
    if "\n" in value or "\r" in value:
        sys.exit(f"{name} contains a line break")


def quoted(value):
    # Compose reads .env with variable expansion: "$HOME" in a password would be replaced.
    # Inside double quotes, $$ is a literal $, and \\ and \" are a backslash and a quote.
    escaped = value.replace("\\", "\\\\").replace("\"", "\\\"").replace("$", "$$")
    return "\"" + escaped + "\""


# No AWS_PROFILE: the server reads AWS with its IAM role (an empty one breaks boto3).
sys.stdout.write("".join(f"{k}={quoted(v)}\n" for k, v in env.items() if v))
' >.env.new && mv .env.new .env)
}

step_start() {
    say "starting the dashboard (on this server's 127.0.0.1:8000 only)"
    mkdir -p evidence reports logs sessions data
    chown -R "$APP_UID:$APP_UID" .
    "${COMPOSE[@]}" up -d dashboard
}

step_schedule() {
    say "scheduling a daily audit at 06:00 (EC2 clocks are UTC; API checks, no screenshots)"
    cat >/etc/cron.d/compliancelens <<EOF
# ComplianceLens: daily audit (written by deploy/aws/server-setup.sh)
0 6 * * * root cd $APP_DIR && docker compose -f docker-compose.server.yml run --rm audit run --no-screenshots >>/var/log/compliancelens-audit.log 2>&1
EOF
    chmod 644 /etc/cron.d/compliancelens
}

cd "$APP_DIR"
# Compose needs .env to exist; the secrets step fills it. Only root can read it.
if [ ! -f .env ]; then
    (umask 077 && : >.env)
fi
for step in $STEPS; do
    case "$step" in
    packages | config | build | secrets | start | schedule) "step_$step" ;;
    *)
        say "unknown step: $step"
        exit 2
        ;;
    esac
done
say "done: $STEPS"
