"""Changes the test accounts to make each case, and puts them back afterwards.

This is the only code in the project that writes to AWS or GitHub. It never uses the
audit's read-only logins:
- AWS: the CLI profile in COMPLIANCELENS_SETUP_AWS_PROFILE (default compliancelens-setup),
  e.g.  aws login --profile compliancelens-setup  as an administrator.
- GitHub: COMPLIANCELENS_SETUP_GITHUB_TOKEN, or else the GitHub CLI's own login
  (`gh auth token`). The organization's settings need its admin:org scope:
  gh auth refresh -h github.com -s admin:org

Safety:
- Before the first change, everything a batch will change is saved to
  data/original-state.json. `restore` puts it back and removes what the experiment
  made, even after a crash. A new batch refuses to start while that file exists, so
  a half-changed account is never saved as the "original".
- What the experiment creates is marked: IAM users and MFA devices under the path
  /compliancelens-experiment/, buckets named clx-... with a compliancelens-experiment
  tag. Cleanup only ever deletes marked things.
- No access keys, no password expiry, force pushes stay blocked, nothing is made
  public (a bucket without Block Public Access is still private: no policy or ACL
  grants access to it).
- Test users' console passwords are random and never shown or saved. They must be
  changed at the first sign-in, and the users are deleted at the end of the batch.
"""

import base64
import contextlib
import copy
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import subprocess
import time
from pathlib import Path

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound

from compliancelens import evidence
from compliancelens.connectors import aws, browser, github
from experiment.lab import data_dir

AWS_PROFILE_ENV = "COMPLIANCELENS_SETUP_AWS_PROFILE"
DEFAULT_AWS_PROFILE = "compliancelens-setup"
GITHUB_TOKEN_ENV = "COMPLIANCELENS_SETUP_GITHUB_TOKEN"
STATE_FILE = "original-state.json"
AUDIT_USER = "compliancelens-audit"  # the read-only audit login: never used for changes

EXPERIMENT_PATH = "/compliancelens-experiment/"
TAG = {"Key": "compliancelens-experiment", "Value": "true"}
BUCKET_PREFIX = "clx-"

# AWS-01: what a case may set. Password expiry is never changed (it could lock people out).
POLICY_FLAGS = (
    "RequireSymbols",
    "RequireNumbers",
    "RequireUppercaseCharacters",
    "RequireLowercaseCharacters",
    "AllowUsersToChangePassword",
)
POLICY_KEYS = ("MinimumPasswordLength", "PasswordReusePrevention", *POLICY_FLAGS)
RESTORE_POLICY_KEYS = (*POLICY_KEYS, "MaxPasswordAge", "HardExpiry")
# GH-01: the parts of main's protection rule a case may set (force pushes stay blocked).
PROTECTION_FLAGS = (
    "pull_request",
    "dismiss_stale_reviews",
    "code_owners",
    "last_push_approval",
    "enforce_admins",
    "linear_history",
    "conversation_resolution",
)
MAX_APPROVALS = 6  # GitHub's limit
# GH-06: the Member privileges settings a case may set.
ORG_KEYS = (
    "default_repository_permission",
    "members_can_create_private_repositories",
    "members_can_fork_private_repositories",
)
PERMISSIONS = ("read", "write", "admin", "none")

USER_NAME = re.compile(r"^[A-Za-z0-9+=,.@_-]{1,64}$")  # what IAM allows
BUCKET_STEM = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}[a-z0-9]$")  # clx-<stem>-<6 hex> <= 63

_clock = time.time  # tests replace this


class SetupError(RuntimeError):
    """The setup can't change or put back something; the message says what to do."""


# ------------------------------------------------------------- case checks ----


def _keys(setup: dict, allowed: set, required: set) -> list[str]:
    problems = []
    if unknown := set(setup) - allowed:
        problems.append(f"unknown key(s) {sorted(unknown)}")
    if missing := required - set(setup):
        problems.append(f"needs {', '.join(sorted(missing))}")
    return problems


def _is_int(value, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _policy_problems(setup: dict) -> list[str]:
    problems = _keys(setup, {"password_policy"}, {"password_policy"})
    policy = setup.get("password_policy", {})
    if policy is None:  # no password policy at all
        return problems
    if not isinstance(policy, dict):
        return [*problems, "password_policy must be a mapping, or null for no policy"]
    if unknown := set(policy) - set(POLICY_KEYS):
        problems.append(f"password_policy: key(s) {sorted(unknown)} can't be set here")
    if not _is_int(policy.get("MinimumPasswordLength"), 6, 128):
        problems.append("password_policy.MinimumPasswordLength must be a number from 6 to 128")
    if "PasswordReusePrevention" in policy and not _is_int(
        policy["PasswordReusePrevention"], 1, 24
    ):
        problems.append("password_policy.PasswordReusePrevention must be from 1 to 24")
    if any(not isinstance(policy[key], bool) for key in POLICY_FLAGS if key in policy):
        problems.append(f"password_policy: {', '.join(POLICY_FLAGS)} must be true or false")
    return problems


def _users_problems(setup: dict) -> list[str]:
    problems = _keys(setup, {"users", "mfa_for"}, {"users"})
    users = setup.get("users")
    if not isinstance(users, list):
        return [*problems, "users must be a list (it may be empty)"]
    names = []
    for user in users:
        if (
            not isinstance(user, dict)
            or set(user) - {"name", "console", "mfa"}
            or not isinstance(user.get("name"), str)
            or not USER_NAME.match(user["name"])
            or any(not isinstance(user.get(key, False), bool) for key in ("console", "mfa"))
        ):
            problems.append(f"users: {user!r} needs a valid name, and console/mfa true or false")
            continue
        if user["name"] == AUDIT_USER:
            problems.append(f"users: {AUDIT_USER} can't be a test user")
        names.append(user["name"])
    if len(set(names)) != len(names):
        problems.append("users: each test user needs a different name")
    mfa_for = setup.get("mfa_for", [])
    if not isinstance(mfa_for, list) or not all(
        isinstance(name, str) and USER_NAME.match(name) for name in mfa_for
    ):
        problems.append("mfa_for must be a list of existing user names")
    elif set(mfa_for) & set(names):
        problems.append("mfa_for is for users that exist already; give test users mfa: true")
    elif AUDIT_USER in mfa_for:
        problems.append(f"mfa_for: {AUDIT_USER} is never changed")
    return problems


def block_flags(block) -> dict:
    """A bucket's Block Public Access flags: true (all on), false (all off) or each one."""
    if isinstance(block, bool):
        return dict.fromkeys(aws.S3_BLOCK_FLAGS, block)
    return {flag: block[flag] for flag in aws.S3_BLOCK_FLAGS}


def _bucket_problems(setup: dict) -> list[str]:
    problems = _keys(setup, {"bucket"}, {"bucket"})
    bucket = setup.get("bucket")
    if not isinstance(bucket, dict):
        return [*problems, "bucket must be a mapping"]
    if unknown := set(bucket) - {"name", "block", "tls_policy"}:
        problems.append(f"bucket: unknown key(s) {sorted(unknown)}")
    if not isinstance(bucket.get("name"), str) or not BUCKET_STEM.match(bucket["name"]):
        problems.append("bucket.name must be 2 to 42 lowercase letters, digits and dashes")
    block = bucket.get("block")
    if not isinstance(block, bool) and not (
        isinstance(block, dict)
        and set(block) == set(aws.S3_BLOCK_FLAGS)
        and all(isinstance(value, bool) for value in block.values())
    ):
        problems.append(
            f"bucket.block must be true (all on), false (all off), or set each of"
            f" {', '.join(aws.S3_BLOCK_FLAGS)}"
        )
    if not isinstance(bucket.get("tls_policy", False), bool):
        problems.append("bucket.tls_policy must be true or false")
    return problems


def _protection_problems(setup: dict) -> list[str]:
    problems = _keys(setup, {"protection"}, {"protection"})
    spec = setup.get("protection")
    if not isinstance(spec, dict):
        return [*problems, "protection must be a mapping"]
    if unknown := set(spec) - {"approvals", *PROTECTION_FLAGS}:
        problems.append(f"protection: unknown key(s) {sorted(unknown)}")
    if not _is_int(spec.get("approvals", 1), 0, MAX_APPROVALS):
        problems.append(f"protection.approvals must be a number from 0 to {MAX_APPROVALS}")
    if any(not isinstance(spec[key], bool) for key in PROTECTION_FLAGS if key in spec):
        problems.append(f"protection: {', '.join(PROTECTION_FLAGS)} must be true or false")
    if spec.get("pull_request", True) is False and "approvals" in spec:
        problems.append("protection.approvals only goes with pull_request: true")
    return problems


def _org_problems(setup: dict) -> list[str]:
    problems = _keys(setup, {"org"}, {"org"})
    spec = setup.get("org")
    if not isinstance(spec, dict):
        return [*problems, "org must be a mapping"]
    if unknown := set(spec) - set(ORG_KEYS):
        problems.append(f"org: key(s) {sorted(unknown)} can't be set here")
    if spec.get("default_repository_permission") not in PERMISSIONS:
        problems.append(
            f"org.default_repository_permission must be one of {', '.join(PERMISSIONS)}"
        )
    if any(not isinstance(spec[key], bool) for key in ORG_KEYS[1:] if key in spec):
        problems.append(f"org: {', '.join(ORG_KEYS[1:])} must be true or false")
    return problems


SETUP_CHECKS = {
    "AWS-01": _policy_problems,
    "AWS-02": _users_problems,
    "AWS-05": _bucket_problems,
    "GH-01": _protection_problems,
    "GH-06": _org_problems,
}


def setup_problems(rule_id: str, setup: dict) -> list[str]:
    """Everything wrong with a case's `setup` for its rule (empty list if it is fine)."""
    return SETUP_CHECKS[rule_id](setup)


def _on(value: bool) -> str:
    return "on" if value else "off"


def describe(rule_id: str, setup: dict) -> str:
    """A case's setup in words, for `plan` and the batch confirmation."""
    if rule_id == "AWS-01":
        policy = setup["password_policy"]
        if policy is None:
            return "password policy: none (deleted)"
        flags = [key for key in POLICY_FLAGS if policy.get(key)]
        extra = (
            f", reuse {policy['PasswordReusePrevention']}"
            if "PasswordReusePrevention" in policy
            else ""
        )
        return f"password policy: minimum {policy['MinimumPasswordLength']}{extra}; " + (
            ", ".join(flags) or "no other requirements"
        )
    if rule_id == "AWS-02":
        users = [
            f"{u['name']} ({'console' if u.get('console') else 'no console'}"
            f"{', MFA' if u.get('mfa') else ''})"
            for u in setup["users"]
        ]
        text = f"test users: {', '.join(users) or 'none'}"
        if setup.get("mfa_for"):
            text += f"; temporary MFA for {', '.join(setup['mfa_for'])}"
        return text
    if rule_id == "AWS-05":
        bucket = setup["bucket"]
        flags = block_flags(bucket["block"])
        if all(flags.values()):
            state = "all on"
        elif not any(flags.values()):
            state = "all off"
        else:
            state = ", ".join(f"{flag} {_on(value)}" for flag, value in flags.items())
        policy = " + HTTPS-only policy" if bucket.get("tls_policy") else ""
        return f"new bucket {BUCKET_PREFIX}{bucket['name']}-…: Block Public Access {state}{policy}"
    if rule_id == "GH-01":
        spec = setup["protection"]
        if spec.get("pull_request", True):
            text = f"main: pull request with {spec.get('approvals', 1)} approval(s)"
        else:
            text = "main: no pull request required"
        others = [key for key in PROTECTION_FLAGS[1:] if spec.get(key)]
        return text + (f"; {', '.join(others)}" if others else "")
    spec = setup["org"]
    others = [f"{key} {_on(spec[key])}" for key in ORG_KEYS[1:] if key in spec]
    return f"organization base permission {spec['default_repository_permission']}" + (
        f"; {', '.join(others)}" if others else ""
    )


# --------------------------------------------------------------------- AWS ----


def totp(seed: bytes | str, at: float) -> str:
    """The 6-digit code an authenticator app shows at time `at` (RFC 6238, 30 s steps)."""
    key = base64.b32decode(seed if isinstance(seed, bytes) else seed.encode("ascii"))
    counter = int(at // 30).to_bytes(8, "big")
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def _password() -> str:
    """A random console password that meets any password policy. Never shown or saved."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(40)) + "Aa1!"


def _tls_policy(bucket: str) -> dict:
    """A bucket policy that only denies (plain-HTTP requests): it makes nothing public."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyPlainHttp",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }
        ],
    }


class AwsSetup:
    """The AWS side: the password policy (AWS-01), test users (AWS-02), test buckets (AWS-05)."""

    def __init__(self, session, region: str, suffix: str | None = None):
        self.iam = session.client("iam", config=aws.RETRY_CONFIG)
        self.s3 = session.client("s3", region_name=region, config=aws.RETRY_CONFIG)
        self.sts = session.client("sts", region_name=region, config=aws.RETRY_CONFIG)
        self.region = region
        self.suffix = suffix or secrets.token_hex(3)  # bucket names are global: keep them unique

    @classmethod
    def from_env(cls, region: str, suffix: str | None = None) -> "AwsSetup":
        profile = os.environ.get(AWS_PROFILE_ENV, "").strip() or DEFAULT_AWS_PROFILE
        try:
            session = boto3.Session(profile_name=profile, region_name=region)
        except ProfileNotFound:
            raise SetupError(
                f"no AWS profile {profile!r}: sign in with  aws login --profile {profile}"
                f"  as an administrator (not {AUDIT_USER})"
            )
        return cls(session, region, suffix)

    def identity(self) -> str:
        """Who the changes are made as (account ID hidden). Refuses the read-only audit user."""
        try:
            arn = self.sts.get_caller_identity()["Arn"]
        except (BotoCoreError, ClientError) as e:
            raise SetupError(f"the AWS setup login does not work ({e})")
        if arn.endswith(f":user/{AUDIT_USER}"):
            raise SetupError(
                f"the AWS setup login is {AUDIT_USER}, which can only read: sign in"
                f" with  aws login --profile {DEFAULT_AWS_PROFILE}  as an administrator"
            )
        return browser.ACCOUNT_ID.sub("ACCOUNT", arn)

    # AWS-01 ---------------------------------------------------------------

    def password_policy(self) -> dict | None:
        """The account's password policy as update_account_password_policy takes it."""
        try:
            policy = self.iam.get_account_password_policy()["PasswordPolicy"]
        except self.iam.exceptions.NoSuchEntityException:
            return None
        kept = {key: policy[key] for key in RESTORE_POLICY_KEYS if key in policy}
        if not kept.get("MaxPasswordAge"):  # 0 or missing: passwords never expire
            kept.pop("MaxPasswordAge", None)
            kept.pop("HardExpiry", None)
        return kept

    def set_password_policy(self, policy: dict | None) -> None:
        if policy is not None:
            self.iam.update_account_password_policy(**policy)
            return
        with contextlib.suppress(self.iam.exceptions.NoSuchEntityException):
            self.iam.delete_account_password_policy()

    # AWS-02 ---------------------------------------------------------------

    def add_users(self, users: list[dict], mfa_for: list[str]) -> None:
        for spec in users:
            name = spec["name"]
            self.iam.create_user(UserName=name, Path=EXPERIMENT_PATH, Tags=[TAG])
            if spec.get("console"):
                self.iam.create_login_profile(
                    UserName=name, Password=_password(), PasswordResetRequired=True
                )
            if spec.get("mfa"):
                self._add_mfa(name)
        for name in mfa_for:
            self._add_mfa(name)

    def _add_mfa(self, user: str) -> None:
        """A virtual MFA device (marked with the experiment's path) for the user."""
        device = self.iam.create_virtual_mfa_device(
            VirtualMFADeviceName=f"clx-{user}", Path=EXPERIMENT_PATH, Tags=[TAG]
        )["VirtualMFADevice"]
        seed, serial = device["Base32StringSeed"], device["SerialNumber"]
        now = _clock()
        for start in (now, now - 30):  # two codes in a row; this clock may be a step ahead
            try:
                self.iam.enable_mfa_device(
                    UserName=user,
                    SerialNumber=serial,
                    AuthenticationCode1=totp(seed, start),
                    AuthenticationCode2=totp(seed, start + 30),
                )
                return
            except ClientError as e:
                if aws._error_code(e) != "InvalidAuthenticationCode":
                    raise
        raise SetupError(
            f"AWS did not accept the MFA codes for {user}: is this computer's clock right?"
        )

    def _test_devices(self) -> list[dict]:
        pages = self.iam.get_paginator("list_virtual_mfa_devices").paginate(AssignmentStatus="Any")
        marker = f":mfa{EXPERIMENT_PATH}"
        return [
            d for page in pages for d in page["VirtualMFADevices"] if marker in d["SerialNumber"]
        ]

    def _test_users(self) -> list[str]:
        pages = self.iam.get_paginator("list_users").paginate(PathPrefix=EXPERIMENT_PATH)
        return [user["UserName"] for page in pages for user in page["Users"]]

    def remove_test_users(self) -> list[str]:
        """Delete every MFA device and user the experiment made. Returns what was removed."""
        removed = []
        for device in self._test_devices():
            serial = device["SerialNumber"]
            user = (device.get("User") or {}).get("UserName")
            if user:
                self.iam.deactivate_mfa_device(UserName=user, SerialNumber=serial)
            self.iam.delete_virtual_mfa_device(SerialNumber=serial)
            removed.append(f"MFA device {serial.rsplit('/', 1)[-1]}")
        for name in self._test_users():
            with contextlib.suppress(self.iam.exceptions.NoSuchEntityException):
                self.iam.delete_login_profile(UserName=name)
            self.iam.delete_user(UserName=name)
            removed.append(f"user {name}")
        return removed

    # AWS-05 ---------------------------------------------------------------

    def bucket_name(self, stem: str) -> str:
        return f"{BUCKET_PREFIX}{stem}-{self.suffix}"

    def add_bucket(self, spec: dict) -> str:
        """A new, empty, marked bucket with the case's Block Public Access flags."""
        name = self.bucket_name(spec["name"])
        create = {"Bucket": name}
        if self.region != "us-east-1":
            create["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
        try:
            self.s3.create_bucket(**create)
        except ClientError as e:
            if aws._error_code(e) != "BucketAlreadyOwnedByYou":
                raise
        self.s3.put_bucket_tagging(Bucket=name, Tagging={"TagSet": [TAG]})
        self.s3.put_public_access_block(
            Bucket=name, PublicAccessBlockConfiguration=block_flags(spec["block"])
        )
        if spec.get("tls_policy"):
            self.s3.put_bucket_policy(Bucket=name, Policy=json.dumps(_tls_policy(name)))
        return name

    def _marked(self, bucket: str) -> bool:
        try:
            return TAG in self.s3.get_bucket_tagging(Bucket=bucket)["TagSet"]
        except ClientError:  # no tags at all
            return False

    def _test_buckets(self) -> list[str]:
        return [
            name
            for name in aws._bucket_names(self.s3)
            if name.startswith(BUCKET_PREFIX) and self._marked(name)
        ]

    def remove_test_buckets(self) -> list[str]:
        """Delete every (empty) bucket the experiment made. Returns what was removed."""
        removed = []
        for name in self._test_buckets():
            self.s3.delete_bucket(Bucket=name)
            removed.append(f"bucket {name}")
        return removed

    def leftovers(self) -> list[str]:
        """Test users, MFA devices and buckets that still exist (should be none)."""
        devices = [
            f"MFA device {d['SerialNumber'].rsplit('/', 1)[-1]}" for d in self._test_devices()
        ]
        users = [f"user {name}" for name in self._test_users()]
        return devices + users + [f"bucket {name}" for name in self._test_buckets()]


# ------------------------------------------------------------------ GitHub ----


def github_token() -> str:
    """The token for changes: COMPLIANCELENS_SETUP_GITHUB_TOKEN, else the GitHub CLI's own
    login. Never the audit's read-only GITHUB_TOKEN (which `gh` would otherwise prefer)."""
    token = os.environ.get(GITHUB_TOKEN_ENV, "").strip()
    if not token:
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
        try:
            done = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
                env=env,
            )
        except (OSError, subprocess.SubprocessError):
            raise SetupError(
                f"no GitHub login for the setup: run  gh auth login  (or set {GITHUB_TOKEN_ENV})"
            )
        token = done.stdout.strip()
        if not token:
            raise SetupError("the GitHub CLI gave no token: run  gh auth login")
    if token == os.environ.get("GITHUB_TOKEN", "").strip():
        raise SetupError(
            "the setup login is the audit's read-only GITHUB_TOKEN: use the GitHub CLI's login"
            f" (gh auth login) or set {GITHUB_TOKEN_ENV} to another token"
        )
    return token


def protection_body(current: dict) -> dict:
    """Turn GitHub's description of a protection rule into the body that sets it again."""
    reviews = current.get("required_pull_request_reviews")
    for extra in ("dismissal_restrictions", "bypass_pull_request_allowances"):
        lists = (reviews or {}).get(extra) or {}
        if any(lists.get(kind) for kind in ("users", "teams", "apps")):
            raise SetupError(f"main's protection rule has {extra}, which this tool can't put back")
    if current.get("restrictions"):
        raise SetupError(
            "main's protection rule limits who can push, which this tool can't put back"
        )

    def enabled(key: str) -> bool:
        return bool((current.get(key) or {}).get("enabled"))

    checks = current.get("required_status_checks")
    return {
        "required_status_checks": None
        if checks is None
        else {"strict": bool(checks.get("strict")), "contexts": list(checks.get("contexts") or [])},
        "enforce_admins": enabled("enforce_admins"),
        "required_pull_request_reviews": None
        if reviews is None
        else {
            "dismiss_stale_reviews": bool(reviews.get("dismiss_stale_reviews")),
            "require_code_owner_reviews": bool(reviews.get("require_code_owner_reviews")),
            "required_approving_review_count": reviews.get("required_approving_review_count", 0),
            "require_last_push_approval": bool(reviews.get("require_last_push_approval")),
        },
        "restrictions": None,
        "required_linear_history": enabled("required_linear_history"),
        "allow_force_pushes": enabled("allow_force_pushes"),
        "allow_deletions": enabled("allow_deletions"),
        "block_creations": enabled("block_creations"),
        "required_conversation_resolution": enabled("required_conversation_resolution"),
        "lock_branch": enabled("lock_branch"),
        "allow_fork_syncing": enabled("allow_fork_syncing"),
    }


def case_protection(original: dict, spec: dict) -> dict:
    """main's protection rule for a GH-01 case: the original, changed as the case says."""
    body = copy.deepcopy(original)
    body["allow_force_pushes"] = False  # GH-02 stays as it is
    if spec.get("pull_request", True):
        body["required_pull_request_reviews"] = {
            "dismiss_stale_reviews": spec.get("dismiss_stale_reviews", False),
            "require_code_owner_reviews": spec.get("code_owners", False),
            "required_approving_review_count": spec.get("approvals", 1),
            "require_last_push_approval": spec.get("last_push_approval", False),
        }
    else:
        body["required_pull_request_reviews"] = None
    for key, field in (
        ("enforce_admins", "enforce_admins"),
        ("linear_history", "required_linear_history"),
        ("conversation_resolution", "required_conversation_resolution"),
    ):
        body[field] = spec.get(key, original[field])
    return body


class GithubSetup:
    """The GitHub side: main's protection rule (GH-01) and Member privileges (GH-06)."""

    def __init__(self, token: str, org: str, repo: str, branch: str = "main"):
        self._token = token
        self.org, self.repo, self.branch = org, repo, branch

    def __repr__(self) -> str:  # never the token
        return f"GithubSetup(org={self.org!r}, repo={self.repo!r})"

    def _call(self, method: str, path: str, body: dict | None = None) -> requests.Response:
        response = requests.request(
            method,
            f"{github.API}{path}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json=body,
            timeout=github.TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            message = github._message(response)
            raise SetupError(
                f"GitHub {method} {path}: HTTP {response.status_code} {message}".strip()
            )
        return response

    def identity(self, rule_ids) -> str:
        """Who the changes are made as. Checks a GitHub CLI login has the scopes it needs."""
        response = self._call("GET", "/user")
        login = response.json().get("login", "?")
        scopes = response.headers.get("X-OAuth-Scopes")
        if scopes is not None:  # classic and CLI tokens list their scopes
            have = {scope.strip() for scope in scopes.split(",")}
            if "GH-06" in rule_ids and "admin:org" not in have:
                raise SetupError(
                    "the GitHub login can't change organization settings: run"
                    "  gh auth refresh -h github.com -s admin:org"
                )
            if "GH-01" in rule_ids and "repo" not in have:
                raise SetupError(
                    "the GitHub login can't change repositories: run  gh auth refresh -s repo"
                )
        return login

    def protection(self) -> dict:
        path = f"/repos/{self.repo}/branches/{self.branch}/protection"
        return protection_body(self._call("GET", path).json())

    def set_protection(self, body: dict) -> None:
        self._call("PUT", f"/repos/{self.repo}/branches/{self.branch}/protection", body)

    def org_settings(self) -> dict:
        data = self._call("GET", f"/orgs/{self.org}").json()
        values = {key: data.get(key) for key in ORG_KEYS}
        if values["default_repository_permission"] is None:
            raise SetupError(
                "GitHub hides the base permission from this login: run"
                "  gh auth refresh -h github.com -s admin:org"
            )
        return values

    def set_org(self, values: dict) -> None:
        self._call("PATCH", f"/orgs/{self.org}", {key: values[key] for key in ORG_KEYS})


# ------------------------------------------------------------------- batch ----


def state_path() -> Path:
    return data_dir() / STATE_FILE


class Setup:
    """One batch of cases: save what will change, make each case, put everything back."""

    def __init__(self, aws_setup: AwsSetup | None = None, github_setup: GithubSetup | None = None):
        self.aws = aws_setup
        self.github = github_setup

    def begin(self, rule_ids) -> dict:
        """Save the settings the batch will change. Refuses while an old batch is unfinished."""
        path = state_path()
        if path.exists():
            raise SetupError(
                f"{path} exists: an earlier batch did not finish. Run"
                "  python -m experiment.lab restore  first"
            )
        rule_ids = sorted(set(rule_ids))
        state = {
            "saved_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "rules": rule_ids,
            "bucket_suffix": self.aws.suffix if self.aws else None,
        }
        if "AWS-01" in rule_ids:
            state["password_policy"] = self.aws.password_policy()
        if "GH-01" in rule_ids:
            state["protection"] = self.github.protection()
        if "GH-06" in rule_ids:
            state["org"] = self.github.org_settings()
        path.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_atomic(path, evidence.to_json_bytes(state))
        return state

    def apply(self, case, original: dict) -> dict:
        """Make the case's state. Returns what its picture needs (AWS-05: the bucket name)."""
        setup = case.setup
        if case.rule == "AWS-01":
            self.aws.set_password_policy(setup["password_policy"])
        elif case.rule == "AWS-02":
            self.aws.remove_test_users()
            self.aws.add_users(setup["users"], setup.get("mfa_for", []))
        elif case.rule == "AWS-05":
            return {"bucket": self.aws.add_bucket(setup["bucket"])}
        elif case.rule == "GH-01":
            self.github.set_protection(case_protection(original["protection"], setup["protection"]))
        else:
            self.github.set_org({**original["org"], **setup["org"]})
        return {}

    def restore(self) -> list[str]:
        """Put back what the batch changed and remove what it made.

        Returns what was done. If anything fails, the rest is still tried, the state
        file is kept (so restore can run again) and SetupError lists the problems.
        """
        path = state_path()
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rules": []}
        rules = set(state.get("rules", []))
        steps = []
        if "GH-06" in rules:
            steps.append(("organization settings", lambda: self.github.set_org(state["org"])))
        if "GH-01" in rules:
            steps.append(
                ("main's protection rule", lambda: self.github.set_protection(state["protection"]))
            )
        if "AWS-01" in rules:
            steps.append(
                ("password policy", lambda: self.aws.set_password_policy(state["password_policy"]))
            )
        if self.aws is not None:
            steps.append(("test users", self.aws.remove_test_users))
            steps.append(("test buckets", self.aws.remove_test_buckets))
        done, problems = [], []
        for label, step in steps:
            try:
                removed = step()
            except Exception as e:  # keep going: put back as much as possible
                problems.append(f"{label}: {e}")
                continue
            if removed is None:
                done.append(f"{label}: put back")
            else:
                done.append(
                    f"{label}: {'removed ' + ', '.join(removed) if removed else 'none left'}"
                )
        if problems:
            raise SetupError(
                "could not put everything back: "
                + "; ".join(problems)
                + ". Fix that, then run  python -m experiment.lab restore  again"
            )
        path.unlink(missing_ok=True)
        return done
