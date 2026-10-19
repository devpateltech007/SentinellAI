"""The experiment's setup: changes to fake AWS (moto) and recorded GitHub replies, and
putting everything back. No network, no real account."""

import json
import subprocess

import boto3
import pytest
import responses
from botocore.exceptions import ClientError
from moto import mock_aws

from compliancelens.connectors import aws
from experiment.lab import world
from experiment.lab.cases import Case

REGION = "us-east-1"
ORG_URL = "https://api.github.com/orgs/test-org"
PROTECTION_URL = "https://api.github.com/repos/test-org/test-repo/branches/main/protection"
PROTECTION = {
    "url": PROTECTION_URL,
    "required_pull_request_reviews": {
        "url": "...",
        "dismiss_stale_reviews": False,
        "require_code_owner_reviews": False,
        "require_last_push_approval": False,
        "required_approving_review_count": 1,
    },
    "required_signatures": {"enabled": False},
    "enforce_admins": {"url": "...", "enabled": False},
    "required_linear_history": {"enabled": False},
    "allow_force_pushes": {"enabled": False},
    "allow_deletions": {"enabled": False},
    "block_creations": {"enabled": False},
    "required_conversation_resolution": {"enabled": False},
    "lock_branch": {"enabled": False},
    "allow_fork_syncing": {"enabled": False},
}
ORG = {
    "login": "test-org",
    "default_repository_permission": "read",
    "members_can_create_private_repositories": True,
    "members_can_fork_private_repositories": False,
    "members_can_delete_repositories": False,
}


def case(rule, setup, case_id="c1", state="PASS"):
    return Case(id=case_id, rule=rule, state=state, kind="plain", setup=setup)


@pytest.fixture
def account():
    """A fake AWS account like the real one: the audit user (console + MFA) and intern-bob."""
    with mock_aws():
        iam = boto3.client("iam")
        iam.update_account_password_policy(MinimumPasswordLength=14, RequireSymbols=True)
        for name in ("compliancelens-audit", "intern-bob"):
            iam.create_user(UserName=name)
            iam.create_login_profile(UserName=name, Password="Aa1!aaaaaaaaaaaaaa")
        device = iam.create_virtual_mfa_device(VirtualMFADeviceName="audit")["VirtualMFADevice"]
        iam.enable_mfa_device(
            UserName="compliancelens-audit",
            SerialNumber=device["SerialNumber"],
            AuthenticationCode1="123456",
            AuthenticationCode2="654321",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket="real-bucket")
        s3.create_bucket(Bucket="clx-not-ours")  # looks like ours, but has no tag
        yield world.AwsSetup(boto3.Session(region_name=REGION), REGION, suffix="abc123")


@pytest.fixture
def gh():
    return world.GithubSetup("setup-token-not-real", "test-org", "test-org/test-repo")


# --- case checks ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "setup", "problem"),
    [
        ("AWS-01", {}, "needs password_policy"),
        ("AWS-01", {"password_policy": "x"}, "must be a mapping"),
        ("AWS-01", {"password_policy": {"MinimumPasswordLength": 5}}, "6 to 128"),
        (
            "AWS-01",
            {"password_policy": {"MinimumPasswordLength": 12, "MaxPasswordAge": 1}},
            "can't be set",
        ),
        (
            "AWS-01",
            {"password_policy": {"MinimumPasswordLength": 12, "PasswordReusePrevention": 30}},
            "1 to 24",
        ),
        (
            "AWS-01",
            {"password_policy": {"MinimumPasswordLength": 12, "RequireSymbols": "yes"}},
            "true or false",
        ),
        ("AWS-01", {"password_policy": None, "other": 1}, "unknown key"),
        ("AWS-02", {"users": "x"}, "must be a list"),
        ("AWS-02", {"users": [{"name": "a b"}]}, "valid name"),
        ("AWS-02", {"users": [{"name": "a", "console": "yes"}]}, "valid name"),
        ("AWS-02", {"users": [{"name": "compliancelens-audit"}]}, "can't be a test user"),
        ("AWS-02", {"users": [{"name": "a"}, {"name": "a"}]}, "different name"),
        ("AWS-02", {"users": [], "mfa_for": "bob"}, "existing user names"),
        ("AWS-02", {"users": [{"name": "a"}], "mfa_for": ["a"]}, "exist already"),
        ("AWS-02", {"users": [], "mfa_for": ["compliancelens-audit"]}, "never changed"),
        ("AWS-05", {"bucket": "x"}, "must be a mapping"),
        ("AWS-05", {"bucket": {"name": "A", "block": True}}, "lowercase"),
        ("AWS-05", {"bucket": {"name": "ab", "block": {"BlockPublicAcls": True}}}, "set each"),
        ("AWS-05", {"bucket": {"name": "ab", "block": True, "tls_policy": 1}}, "true or false"),
        ("AWS-05", {"bucket": {"name": "ab", "block": True, "acl": "public"}}, "unknown key"),
        ("GH-01", {"protection": []}, "must be a mapping"),
        ("GH-01", {"protection": {"approvals": 7}}, "0 to 6"),
        ("GH-01", {"protection": {"enforce_admins": 1}}, "true or false"),
        ("GH-01", {"protection": {"pull_request": False, "approvals": 1}}, "only goes with"),
        ("GH-01", {"protection": {"allow_force_pushes": True}}, "unknown key"),
        ("GH-06", {"org": "x"}, "must be a mapping"),
        ("GH-06", {"org": {"default_repository_permission": "maintain"}}, "must be one of"),
        (
            "GH-06",
            {
                "org": {
                    "default_repository_permission": "read",
                    "members_can_delete_repositories": True,
                }
            },
            "can't be set",
        ),
        (
            "GH-06",
            {
                "org": {
                    "default_repository_permission": "read",
                    "members_can_fork_private_repositories": "no",
                }
            },
            "true or false",
        ),
    ],
)
def test_setups_that_are_refused(rule, setup, problem):
    assert any(problem in p for p in world.setup_problems(rule, setup)), world.setup_problems(
        rule, setup
    )


@pytest.mark.parametrize(
    ("rule", "setup", "text"),
    [
        ("AWS-01", {"password_policy": None}, "password policy: none (deleted)"),
        (
            "AWS-01",
            {
                "password_policy": {
                    "MinimumPasswordLength": 16,
                    "RequireSymbols": True,
                    "PasswordReusePrevention": 5,
                }
            },
            "password policy: minimum 16, reuse 5; RequireSymbols",
        ),
        (
            "AWS-01",
            {"password_policy": {"MinimumPasswordLength": 9}},
            "minimum 9; no other requirements",
        ),
        (
            "AWS-02",
            {
                "users": [{"name": "a", "console": True, "mfa": True}, {"name": "b"}],
                "mfa_for": ["bob"],
            },
            "test users: a (console, MFA), b (no console); temporary MFA for bob",
        ),
        ("AWS-02", {"users": []}, "test users: none"),
        (
            "AWS-05",
            {"bucket": {"name": "ab", "block": True, "tls_policy": True}},
            "Block Public Access all on + HTTPS-only policy",
        ),
        ("AWS-05", {"bucket": {"name": "ab", "block": False}}, "all off"),
        (
            "AWS-05",
            {
                "bucket": {
                    "name": "ab",
                    "block": {**dict.fromkeys(aws.S3_BLOCK_FLAGS, True), "BlockPublicAcls": False},
                }
            },
            "BlockPublicAcls off, IgnorePublicAcls on",
        ),
        (
            "GH-01",
            {"protection": {"approvals": 2, "linear_history": True}},
            "main: pull request with 2 approval(s); linear_history",
        ),
        ("GH-01", {"protection": {"pull_request": False}}, "main: no pull request required"),
        (
            "GH-06",
            {
                "org": {
                    "default_repository_permission": "none",
                    "members_can_fork_private_repositories": True,
                }
            },
            "organization base permission none; members_can_fork_private_repositories on",
        ),
    ],
)
def test_describe(rule, setup, text):
    assert world.setup_problems(rule, setup) == []
    assert text in world.describe(rule, setup)


# --- AWS ------------------------------------------------------------------------------


def test_totp_matches_the_rfc_test_vector():
    seed = __import__("base64").b32encode(b"12345678901234567890")
    assert world.totp(seed, 59) == "287082"  # RFC 6238: 94287082 (8 digits)
    assert world.totp(seed.decode(), 1111111109) == "081804"


def test_test_passwords_are_long_and_varied():
    one, two = world._password(), world._password()
    assert one != two and len(one) == 44
    assert any(c.isupper() for c in one) and any(c.isdigit() for c in one) and "!" in one


def test_identity_hides_the_account_and_refuses_the_audit_user(account, monkeypatch):
    assert world.AwsSetup.identity(account).startswith("arn:aws:")
    assert "123456789012" not in account.identity()

    class Sts:
        def get_caller_identity(self):
            return {"Arn": "arn:aws:iam::123456789012:user/compliancelens-audit"}

    account.sts = Sts()
    with pytest.raises(world.SetupError, match="can only read"):
        account.identity()


def test_identity_without_a_working_login(account):
    class Sts:
        def get_caller_identity(self):
            raise ClientError({"Error": {"Code": "ExpiredToken"}}, "GetCallerIdentity")

    account.sts = Sts()
    with pytest.raises(world.SetupError, match="does not work"):
        account.identity()


def test_a_missing_setup_profile(monkeypatch):
    monkeypatch.setenv(world.AWS_PROFILE_ENV, "no-such-profile-xyz")
    with pytest.raises(world.SetupError, match="aws login --profile no-such-profile-xyz"):
        world.AwsSetup.from_env(REGION)


def test_setup_profile_from_env(monkeypatch):
    seen, real = {}, boto3.Session

    def session(**kwargs):
        seen.update(kwargs)
        return real(region_name=REGION)

    monkeypatch.setattr(world.boto3, "Session", session)
    with mock_aws():
        setup = world.AwsSetup.from_env("eu-west-1", suffix="x1")
    assert seen == {"profile_name": world.DEFAULT_AWS_PROFILE, "region_name": "eu-west-1"}
    assert setup.suffix == "x1" and setup.region == "eu-west-1"


def test_password_policy_round_trip(account):
    original = account.password_policy()
    assert original["MinimumPasswordLength"] == 14 and "MaxPasswordAge" not in original
    account.set_password_policy({"MinimumPasswordLength": 9})
    assert account.password_policy()["MinimumPasswordLength"] == 9
    account.set_password_policy(None)
    assert account.password_policy() is None
    account.set_password_policy(None)  # deleting twice is fine
    account.set_password_policy(original)
    assert account.password_policy() == original


def test_password_expiry_is_kept_when_putting_back(account):
    account.iam.update_account_password_policy(
        MinimumPasswordLength=14, MaxPasswordAge=90, HardExpiry=False
    )
    assert account.password_policy()["MaxPasswordAge"] == 90


def test_users_and_mfa_are_added_and_removed(account):
    account.add_users(
        [{"name": "clx-a", "console": True, "mfa": True}, {"name": "clx-b"}], ["intern-bob"]
    )
    assert aws.users_without_mfa({}) == {"count": 0, "users": []}
    iam = account.iam
    assert iam.get_user(UserName="clx-a")["User"]["Path"] == world.EXPERIMENT_PATH
    assert iam.list_user_tags(UserName="clx-b")["Tags"] == [world.TAG]
    assert sorted(account.leftovers()) == [
        "MFA device clx-clx-a",
        "MFA device clx-intern-bob",
        "user clx-a",
        "user clx-b",
    ]
    removed = account.remove_test_users()
    assert set(removed) == {
        "MFA device clx-clx-a",
        "MFA device clx-intern-bob",
        "user clx-a",
        "user clx-b",
    }
    assert aws.users_without_mfa({}) == {"count": 1, "users": ["intern-bob"]}
    names = {u["UserName"] for u in iam.list_users()["Users"]}
    assert names == {"compliancelens-audit", "intern-bob"}  # only marked users go
    assert len(iam.list_mfa_devices(UserName="compliancelens-audit")["MFADevices"]) == 1
    assert account.leftovers() == []


def test_mfa_codes_are_tried_one_step_earlier(account, monkeypatch):
    tries = []
    real = account.iam.enable_mfa_device

    def enable(**kwargs):
        tries.append(kwargs["AuthenticationCode1"])
        if len(tries) == 1:
            raise ClientError({"Error": {"Code": "InvalidAuthenticationCode"}}, "EnableMFADevice")
        return real(**kwargs)

    monkeypatch.setattr(account.iam, "enable_mfa_device", enable)
    monkeypatch.setattr(world, "_clock", lambda: 1_000_000.0)
    account.add_users([], ["intern-bob"])
    assert len(tries) == 2 and tries[0] != tries[1]


def test_mfa_codes_never_accepted(account, monkeypatch):
    def enable(**kwargs):
        raise ClientError({"Error": {"Code": "InvalidAuthenticationCode"}}, "EnableMFADevice")

    monkeypatch.setattr(account.iam, "enable_mfa_device", enable)
    with pytest.raises(world.SetupError, match="clock"):
        account.add_users([], ["intern-bob"])


def test_other_mfa_errors_are_raised(account, monkeypatch):
    def enable(**kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "EnableMFADevice")

    monkeypatch.setattr(account.iam, "enable_mfa_device", enable)
    with pytest.raises(ClientError):
        account.add_users([], ["intern-bob"])


def test_buckets_are_made_and_only_marked_ones_removed(account):
    name = account.add_bucket({"name": "reports", "block": True, "tls_policy": True})
    off = account.add_bucket({"name": "open", "block": False})
    assert (name, off) == ("clx-reports-abc123", "clx-open-abc123")
    flags = aws.s3_public_access({})["bucket_flags"]
    assert all(flags[name].values()) and not any(flags[off].values())
    policy = json.loads(account.s3.get_bucket_policy(Bucket=name)["Policy"])
    assert policy["Statement"][0]["Effect"] == "Deny"  # it only denies: nothing is public
    assert account.add_bucket({"name": "reports", "block": True}) == name  # made already: fine
    assert sorted(account.remove_test_buckets()) == [f"bucket {off}", f"bucket {name}"]
    left = {b["Name"] for b in account.s3.list_buckets()["Buckets"]}
    assert left == {"real-bucket", "clx-not-ours"}


def test_bucket_errors_other_than_already_made(account, monkeypatch):
    def create(**kwargs):
        raise ClientError({"Error": {"Code": "BucketAlreadyExists"}}, "CreateBucket")

    monkeypatch.setattr(account.s3, "create_bucket", create)
    with pytest.raises(ClientError):
        account.add_bucket({"name": "taken", "block": True})


def test_buckets_outside_us_east_1_name_their_region():
    with mock_aws():
        setup = world.AwsSetup(boto3.Session(region_name="eu-west-1"), "eu-west-1", suffix="e1")
        name = setup.add_bucket({"name": "eu", "block": True})
        assert setup.s3.get_bucket_location(Bucket=name)["LocationConstraint"] == "eu-west-1"


# --- GitHub ---------------------------------------------------------------------------


def test_setup_token_from_env(monkeypatch):
    monkeypatch.setenv(world.GITHUB_TOKEN_ENV, " env-token ")
    assert world.github_token() == "env-token"


def test_setup_token_from_the_github_cli(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "audit-read-only-token")
    monkeypatch.setenv("GH_TOKEN", "another-token")

    def gh(args, env, **kwargs):
        assert args == ["gh", "auth", "token"]
        # gh would answer with GITHUB_TOKEN (the audit's read-only token) if it could see it
        assert "GITHUB_TOKEN" not in env and "GH_TOKEN" not in env
        return subprocess.CompletedProcess(args, 0, stdout="cli-token\n", stderr="")

    monkeypatch.setattr(world.subprocess, "run", gh)
    assert world.github_token() == "cli-token"


def test_the_audit_token_is_never_the_setup_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "same-token")
    monkeypatch.setenv(world.GITHUB_TOKEN_ENV, "same-token")
    with pytest.raises(world.SetupError, match="read-only GITHUB_TOKEN"):
        world.github_token()


@pytest.mark.parametrize(
    "problem", [FileNotFoundError("gh"), subprocess.CalledProcessError(1, "gh"), ""]
)
def test_no_github_login_for_the_setup(monkeypatch, problem):
    def gh(args, **kwargs):
        if isinstance(problem, Exception):
            raise problem
        return subprocess.CompletedProcess(args, 0, stdout=problem, stderr="")

    monkeypatch.setattr(world.subprocess, "run", gh)
    with pytest.raises(world.SetupError, match="gh auth login"):
        world.github_token()


def test_protection_body_round_trip():
    body = world.protection_body(PROTECTION)
    assert body["required_pull_request_reviews"]["required_approving_review_count"] == 1
    assert body["required_status_checks"] is None and body["restrictions"] is None
    assert body["allow_force_pushes"] is False and body["enforce_admins"] is False
    checks = {**PROTECTION, "required_status_checks": {"strict": True, "contexts": ["ci"]}}
    assert world.protection_body(checks)["required_status_checks"] == {
        "strict": True,
        "contexts": ["ci"],
    }
    no_reviews = {k: v for k, v in PROTECTION.items() if k != "required_pull_request_reviews"}
    assert world.protection_body(no_reviews)["required_pull_request_reviews"] is None


@pytest.mark.parametrize(
    "extra",
    [
        {"restrictions": {"users": [{"login": "a"}]}},
        {"required_pull_request_reviews": {"dismissal_restrictions": {"users": [{"login": "a"}]}}},
        {
            "required_pull_request_reviews": {
                "bypass_pull_request_allowances": {"teams": [{"slug": "t"}]}
            }
        },
    ],
)
def test_protection_that_cant_be_put_back(extra):
    with pytest.raises(world.SetupError, match="can't put back"):
        world.protection_body({**PROTECTION, **extra})


def test_case_protection():
    original = world.protection_body(PROTECTION)
    body = world.case_protection(
        original, {"approvals": 3, "code_owners": True, "linear_history": True}
    )
    reviews = body["required_pull_request_reviews"]
    assert reviews["required_approving_review_count"] == 3 and reviews["require_code_owner_reviews"]
    assert body["required_linear_history"] is True and body["enforce_admins"] is False
    assert (
        world.case_protection(original, {"pull_request": False})["required_pull_request_reviews"]
        is None
    )
    forced = world.case_protection({**original, "allow_force_pushes": True}, {})
    assert forced["allow_force_pushes"] is False  # force pushes always stay blocked
    assert original["required_pull_request_reviews"]["required_approving_review_count"] == 1


@responses.activate
def test_github_identity_and_scopes(gh):
    responses.get(
        "https://api.github.com/user",
        json={"login": "neels"},
        headers={"X-OAuth-Scopes": "repo, read:org"},
    )
    assert gh.identity({"GH-01"}) == "neels"
    with pytest.raises(world.SetupError, match="admin:org"):
        gh.identity({"GH-06"})
    assert responses.calls[0].request.headers["Authorization"] == "Bearer setup-token-not-real"
    assert "setup-token-not-real" not in repr(gh)


@responses.activate
def test_github_identity_without_repo_scope(gh):
    responses.get(
        "https://api.github.com/user", json={"login": "n"}, headers={"X-OAuth-Scopes": "admin:org"}
    )
    with pytest.raises(world.SetupError, match="refresh -s repo"):
        gh.identity({"GH-01", "GH-06"})


@responses.activate
def test_fine_grained_tokens_list_no_scopes(gh):
    responses.get("https://api.github.com/user", json={"login": "n"})
    assert gh.identity({"GH-01", "GH-06"}) == "n"


@responses.activate
def test_github_protection_and_org(gh):
    responses.get(PROTECTION_URL, json=PROTECTION)
    responses.put(PROTECTION_URL, json={})
    responses.get(ORG_URL, json=ORG)
    responses.patch(ORG_URL, json={})
    original = gh.protection()
    gh.set_protection(original)
    assert json.loads(responses.calls[1].request.body) == original
    settings = gh.org_settings()
    assert settings == {key: ORG[key] for key in world.ORG_KEYS}
    gh.set_org({**settings, "default_repository_permission": "write", "extra": 1})
    sent = json.loads(responses.calls[3].request.body)
    assert sent == {**settings, "default_repository_permission": "write"}  # only ORG_KEYS


@responses.activate
def test_github_errors_say_what_happened(gh):
    responses.get(ORG_URL, json={"message": "Must have admin rights"}, status=403)
    with pytest.raises(world.SetupError, match="HTTP 403 Must have admin rights"):
        gh.org_settings()


@responses.activate
def test_a_hidden_base_permission(gh):
    responses.get(ORG_URL, json={"login": "test-org"})
    with pytest.raises(world.SetupError, match="admin:org"):
        gh.org_settings()


# --- a batch --------------------------------------------------------------------------


@responses.activate
def test_a_batch_saves_changes_and_puts_everything_back(account, gh):
    responses.get(PROTECTION_URL, json=PROTECTION)
    responses.put(PROTECTION_URL, json={})
    responses.get(ORG_URL, json=ORG)
    responses.patch(ORG_URL, json={})
    setup = world.Setup(account, gh)
    original = setup.begin(["AWS-01", "AWS-02", "AWS-05", "GH-01", "GH-06"])
    saved = json.loads(world.state_path().read_text())
    assert saved["rules"] == ["AWS-01", "AWS-02", "AWS-05", "GH-01", "GH-06"]
    assert saved["password_policy"]["MinimumPasswordLength"] == 14
    assert (
        saved["bucket_suffix"] == "abc123"
        and original["org"]["default_repository_permission"] == "read"
    )

    setup.apply(case("AWS-01", {"password_policy": None}), original)
    assert account.password_policy() is None
    setup.apply(case("AWS-02", {"users": [{"name": "clx-x", "console": True}]}), original)
    setup.apply(case("AWS-02", {"users": [], "mfa_for": ["intern-bob"]}), original)
    assert aws.users_without_mfa({})["count"] == 0  # clx-x was removed before the next case
    facts = setup.apply(case("AWS-05", {"bucket": {"name": "ab", "block": False}}), original)
    assert facts == {"bucket": "clx-ab-abc123"}
    setup.apply(case("GH-01", {"protection": {"approvals": 2}}), original)
    setup.apply(case("GH-06", {"org": {"default_repository_permission": "admin"}}), original)
    assert (
        json.loads(responses.calls[-2].request.body)["required_pull_request_reviews"][
            "required_approving_review_count"
        ]
        == 2
    )
    assert json.loads(responses.calls[-1].request.body)["default_repository_permission"] == "admin"

    with pytest.raises(world.SetupError, match="did not finish"):
        world.Setup(account, gh).begin(["AWS-01"])

    done = setup.restore()
    assert done[:3] == [
        "organization settings: put back",
        "main's protection rule: put back",
        "password policy: put back",
    ]
    assert done[3].startswith("test users: removed MFA device clx-intern-bob")
    assert done[4] == "test buckets: removed bucket clx-ab-abc123"
    assert json.loads(responses.calls[-2].request.body)["default_repository_permission"] == "read"
    assert (
        json.loads(responses.calls[-1].request.body)["required_pull_request_reviews"][
            "required_approving_review_count"
        ]
        == 1
    )
    assert account.password_policy() == saved["password_policy"]
    assert account.leftovers() == [] and not world.state_path().exists()
    assert world.Setup(account, gh).restore() == [
        "test users: none left",
        "test buckets: none left",
    ]


def test_restore_keeps_going_and_keeps_the_state_file(account, monkeypatch):
    setup = world.Setup(account)
    setup.begin(["AWS-01"])
    account.add_users([{"name": "clx-z"}], [])

    def broken(policy):
        raise RuntimeError("throttled")

    monkeypatch.setattr(account, "set_password_policy", broken)
    with pytest.raises(world.SetupError, match="password policy: throttled.*restore  again"):
        setup.restore()
    assert account.leftovers() == []  # the users were still removed
    assert world.state_path().exists()  # so restore can run again
