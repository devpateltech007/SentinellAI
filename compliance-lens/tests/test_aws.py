"""AWS connector tests against a fake AWS account (moto). Both verdict states per rule.

moto can't produce a few states (root MFA on, "last used" dates, more than one
page of users), so those use botocore's Stubber or a recorded credential report.
"""

import datetime
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from moto import mock_aws

from compliancelens import engine
from compliancelens.connectors import aws

REPORT = (Path(__file__).parent / "fixtures" / "aws" / "credential_report.csv").read_text()
REPORT_NOW = datetime.datetime(2026, 10, 15, 10, 0, tzinfo=datetime.UTC)


@pytest.fixture
def iam():
    with mock_aws():
        yield boto3.client("iam")


@pytest.fixture
def s3():
    with mock_aws():
        yield boto3.client("s3")


def add_console_user(iam, name):
    iam.create_user(UserName=name)
    iam.create_login_profile(UserName=name, Password="Str0ng-Passw0rd!")


def add_mfa(iam, name):
    device = iam.create_virtual_mfa_device(VirtualMFADeviceName=f"{name}-mfa")
    iam.enable_mfa_device(
        UserName=name,
        SerialNumber=device["VirtualMFADevice"]["SerialNumber"],
        AuthenticationCode1="123456",
        AuthenticationCode2="654321",
    )


def days_from_now(monkeypatch, days):
    """Pretend `days` days have passed."""
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=days)
    monkeypatch.setattr(aws, "_now", lambda: later)


def stubbed(service):
    """A client whose replies a test scripts with Stubber (for what moto can't fake)."""
    client = boto3.client(service, region_name="us-east-1")
    return client, Stubber(client)


def run(rule_id, collector, check):
    return engine.run_rule({"id": rule_id, "title": "t", "collector": collector, "check": check})


# --- AWS-01: password policy ---------------------------------------------


def test_no_password_policy_counts_as_length_zero(iam):
    assert aws.password_policy({})["MinimumPasswordLength"] == 0


def test_password_policy_returns_minimum_length(iam):
    iam.update_account_password_policy(MinimumPasswordLength=14)
    assert aws.password_policy({})["MinimumPasswordLength"] == 14


# --- AWS-02: console users without MFA -----------------------------------


def test_no_users_means_none_missing(iam):
    assert aws.users_without_mfa({}) == {"count": 0, "users": []}


def test_console_user_without_mfa_is_counted(iam):
    add_console_user(iam, "intern-bob")
    assert aws.users_without_mfa({}) == {"count": 1, "users": ["intern-bob"]}


def test_access_key_only_user_is_skipped(iam):
    iam.create_user(UserName="compliancelens-audit")
    iam.create_access_key(UserName="compliancelens-audit")
    assert aws.users_without_mfa({})["count"] == 0


def test_console_user_with_mfa_is_not_counted(iam):
    add_console_user(iam, "alice")
    add_mfa(iam, "alice")
    assert aws.users_without_mfa({})["count"] == 0


def test_mixed_users(iam):
    add_console_user(iam, "alice")
    add_mfa(iam, "alice")
    add_console_user(iam, "intern-bob")
    iam.create_user(UserName="compliancelens-audit")
    assert aws.users_without_mfa({}) == {"count": 1, "users": ["intern-bob"]}


def test_has_console_password(iam):
    add_console_user(iam, "alice")
    iam.create_user(UserName="robot")
    assert aws.has_console_password("alice") is True
    assert aws.has_console_password("robot") is False


# --- user listing and pagination -------------------------------------------


def test_iam_users_lists_every_user(iam):
    for i in range(150):
        iam.create_user(UserName=f"user-{i:03d}")
    result = aws.iam_users({})
    assert result["count"] == 150
    assert result["users"][0] == "user-000"


def test_users_are_read_across_pages(monkeypatch):
    # moto returns every user on one page, so script two pages by hand.
    client, stub = stubbed("iam")
    created = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    def users(names):
        return [
            {
                "UserName": n,
                "UserId": f"AIDA{n.upper():0>16}",
                "Arn": "arn:aws:iam::1:user/x",
                "Path": "/",
                "CreateDate": created,
            }
            for n in names
        ]

    first = [f"u{i:03d}" for i in range(100)]
    stub.add_response("list_users", {"Users": users(first), "IsTruncated": True, "Marker": "m1"})
    stub.add_response(
        "list_users", {"Users": users(["u100", "u101"]), "IsTruncated": False}, {"Marker": "m1"}
    )
    monkeypatch.setattr(aws, "_iam", lambda: client)
    with stub:
        assert aws.iam_users({})["count"] == 102


# --- AWS-03: root account MFA ----------------------------------------------


def test_root_without_mfa(iam):
    # moto always reports root MFA as off.
    assert aws.root_account_mfa({}) == {"AccountMFAEnabled": 0, "AccountAccessKeysPresent": 0}


def test_root_with_mfa_passes(monkeypatch):
    client, stub = stubbed("iam")
    stub.add_response(
        "get_account_summary",
        {"SummaryMap": {"AccountMFAEnabled": 1, "AccountAccessKeysPresent": 0}},
    )
    monkeypatch.setattr(aws, "_iam", lambda: client)
    with stub:
        r = run(
            "AWS-03", "aws.root_account_mfa", {"field": "AccountMFAEnabled", "op": "==", "value": 1}
        )
    assert r["verdict"] == "PASS"


def test_root_mfa_missing_from_summary_needs_review(monkeypatch):
    client, stub = stubbed("iam")
    stub.add_response("get_account_summary", {"SummaryMap": {}})
    monkeypatch.setattr(aws, "_iam", lambda: client)
    with stub:
        r = run(
            "AWS-03", "aws.root_account_mfa", {"field": "AccountMFAEnabled", "op": "==", "value": 1}
        )
    assert r["verdict"] == "NEEDS REVIEW"


def test_permission_error_needs_review(monkeypatch):
    client, stub = stubbed("iam")
    stub.add_client_error("get_account_summary", "AccessDenied", "not allowed")
    monkeypatch.setattr(aws, "_iam", lambda: client)
    with stub:
        r = run(
            "AWS-03", "aws.root_account_mfa", {"field": "AccountMFAEnabled", "op": "==", "value": 1}
        )
    assert r["verdict"] == "NEEDS REVIEW"
    assert "AccessDenied" in r["reason"]


# --- AWS-04: access key age ------------------------------------------------


def test_no_access_keys_is_nothing_old(iam):
    iam.create_user(UserName="compliancelens-audit")
    assert aws.access_key_age({}) == {
        "count": 0,
        "keys": [],
        "active_keys_checked": 0,
        "max_age_days": 90,
    }


def test_new_key_is_not_old(iam):
    iam.create_user(UserName="robot")
    iam.create_access_key(UserName="robot")
    result = aws.access_key_age({})
    assert result["count"] == 0
    assert result["active_keys_checked"] == 1


def test_key_older_than_90_days_is_counted(iam, monkeypatch):
    iam.create_user(UserName="robot")
    key_id = iam.create_access_key(UserName="robot")["AccessKey"]["AccessKeyId"]
    days_from_now(monkeypatch, 100)
    result = aws.access_key_age({})
    assert result["count"] == 1
    assert result["keys"] == [{"user": "robot", "key": f"...{key_id[-4:]}", "age_days": 100}]


def test_inactive_old_key_is_skipped(iam, monkeypatch):
    iam.create_user(UserName="robot")
    key_id = iam.create_access_key(UserName="robot")["AccessKey"]["AccessKeyId"]
    iam.update_access_key(UserName="robot", AccessKeyId=key_id, Status="Inactive")
    days_from_now(monkeypatch, 100)
    assert aws.access_key_age({})["count"] == 0


def test_max_age_is_a_param(iam, monkeypatch):
    iam.create_user(UserName="robot")
    iam.create_access_key(UserName="robot")
    days_from_now(monkeypatch, 40)
    assert aws.access_key_age({"max_age_days": 30})["count"] == 1
    assert aws.access_key_age({"max_age_days": 90})["count"] == 0


# --- AWS-05: S3 public access --------------------------------------------

ALL_ON = dict.fromkeys(aws.S3_BLOCK_FLAGS, True)


def test_bucket_with_all_flags_on(s3):
    s3.create_bucket(Bucket="locked-bucket")
    s3.put_public_access_block(Bucket="locked-bucket", PublicAccessBlockConfiguration=ALL_ON)
    result = aws.s3_public_access({})
    assert result["buckets_fully_blocked"] == {"locked-bucket": True}
    assert result["bucket_flags"]["locked-bucket"] == ALL_ON


def test_bucket_with_one_flag_off(s3):
    s3.create_bucket(Bucket="leaky-bucket")
    s3.put_public_access_block(
        Bucket="leaky-bucket", PublicAccessBlockConfiguration={**ALL_ON, "BlockPublicPolicy": False}
    )
    assert aws.s3_public_access({})["buckets_fully_blocked"] == {"leaky-bucket": False}


def test_bucket_without_settings_counts_as_off(s3):
    s3.create_bucket(Bucket="plain-bucket")
    result = aws.s3_public_access({})
    assert result["buckets_fully_blocked"] == {"plain-bucket": False}
    assert result["bucket_flags"]["plain-bucket"] == dict.fromkeys(aws.S3_BLOCK_FLAGS, False)


def test_account_level_flags_are_recorded(s3):
    account = boto3.client("sts").get_caller_identity()["Account"]
    boto3.client("s3control").put_public_access_block(
        AccountId=account, PublicAccessBlockConfiguration=ALL_ON
    )
    assert aws.s3_public_access({})["account_flags"] == ALL_ON


def test_account_level_not_set_counts_as_off(s3):
    assert aws.s3_public_access({})["account_flags"] == dict.fromkeys(aws.S3_BLOCK_FLAGS, False)


def test_account_level_error_is_recorded_not_raised(monkeypatch):
    def denied(service):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetCallerIdentity")

    monkeypatch.setattr(aws, "_client", denied)
    assert "AccessDenied" in aws._account_public_access_block()["error"]


def test_bucket_error_is_raised(monkeypatch):
    client, stub = stubbed("s3")
    stub.add_response("list_buckets", {"Buckets": [{"Name": "some-bucket"}]})
    stub.add_client_error("get_public_access_block", "AccessDenied", "no")
    monkeypatch.setattr(aws, "_client", lambda service: client)
    with stub, pytest.raises(ClientError):
        aws.s3_public_access({})


def test_public_access_verdicts(s3):
    check = {"field": "buckets_fully_blocked", "op": "all_true"}
    s3.create_bucket(Bucket="locked-bucket")
    s3.put_public_access_block(Bucket="locked-bucket", PublicAccessBlockConfiguration=ALL_ON)
    assert run("AWS-05", "aws.s3_public_access", check)["verdict"] == "PASS"
    s3.create_bucket(Bucket="plain-bucket")
    r = run("AWS-05", "aws.s3_public_access", check)
    assert r["verdict"] == "FAIL"
    assert "plain-bucket" in r["reason"]


def test_no_buckets_needs_review(s3):
    r = run("AWS-05", "aws.s3_public_access", {"field": "buckets_fully_blocked", "op": "all_true"})
    assert r["verdict"] == "NEEDS REVIEW"


# --- AWS-06: S3 versioning -------------------------------------------------


def test_versioning_states(s3):
    for name in ("on-bucket", "paused-bucket", "never-bucket"):
        s3.create_bucket(Bucket=name)
    s3.put_bucket_versioning(Bucket="on-bucket", VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_versioning(
        Bucket="paused-bucket", VersioningConfiguration={"Status": "Suspended"}
    )
    result = aws.s3_versioning({})
    assert result["versioning_enabled"] == {
        "never-bucket": False,
        "on-bucket": True,
        "paused-bucket": False,
    }
    assert result["versioning_status"]["never-bucket"] == "NeverEnabled"
    assert result["versioning_status"]["paused-bucket"] == "Suspended"


def test_versioning_verdicts(s3):
    check = {"field": "versioning_enabled", "op": "all_true"}
    s3.create_bucket(Bucket="on-bucket")
    s3.put_bucket_versioning(Bucket="on-bucket", VersioningConfiguration={"Status": "Enabled"})
    assert run("AWS-06", "aws.s3_versioning", check)["verdict"] == "PASS"
    s3.put_bucket_versioning(Bucket="on-bucket", VersioningConfiguration={"Status": "Suspended"})
    assert run("AWS-06", "aws.s3_versioning", check)["verdict"] == "FAIL"


# --- AWS-07: CloudTrail ----------------------------------------------------


@pytest.fixture
def cloudtrail(s3):
    s3.create_bucket(Bucket="trail-logs")
    return boto3.client("cloudtrail")


def test_no_trails(cloudtrail):
    assert aws.cloudtrail_logging({}) == {"logging_count": 0, "logging_trails": [], "trails": []}


def test_trail_not_logging(cloudtrail):
    cloudtrail.create_trail(Name="main", S3BucketName="trail-logs")
    result = aws.cloudtrail_logging({})
    assert result["logging_count"] == 0
    assert result["trails"][0]["is_logging"] is False


def test_trail_logging(cloudtrail):
    cloudtrail.create_trail(Name="main", S3BucketName="trail-logs", IsMultiRegionTrail=True)
    cloudtrail.start_logging(Name="main")
    result = aws.cloudtrail_logging({})
    assert result["logging_count"] == 1
    assert result["logging_trails"] == ["main"]
    assert result["trails"][0]["multi_region"] is True


def test_trail_from_another_region_is_seen(cloudtrail, monkeypatch):
    cloudtrail.create_trail(Name="main", S3BucketName="trail-logs", IsMultiRegionTrail=True)
    cloudtrail.start_logging(Name="main")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    assert aws.cloudtrail_logging({})["logging_trails"] == ["main"]


def test_cloudtrail_verdicts(cloudtrail):
    check = {"field": "logging_count", "op": ">=", "value": 1}
    assert run("AWS-07", "aws.cloudtrail_logging", check)["verdict"] == "FAIL"
    cloudtrail.create_trail(Name="main", S3BucketName="trail-logs")
    cloudtrail.start_logging(Name="main")
    assert run("AWS-07", "aws.cloudtrail_logging", check)["verdict"] == "PASS"


# --- AWS-08: unused users --------------------------------------------------


def test_inactive_users_from_recorded_report():
    inactive, checked = aws._inactive_users(REPORT, REPORT_NOW, 90)
    assert checked == 6  # root is skipped
    assert {u["user"]: u["basis"] for u in inactive} == {
        "old-console": "last used",
        "old-robot": "last used",
        "never-used": "created, never used",
    }


def test_new_user_who_never_signed_in_is_not_inactive():
    inactive, _ = aws._inactive_users(REPORT, REPORT_NOW, 90)
    assert "intern-bob" not in [u["user"] for u in inactive]


def test_newest_activity_counts():
    # busy-robot's key 1 is old but key 2 was used two days ago.
    inactive, _ = aws._inactive_users(REPORT, REPORT_NOW, 90)
    assert "busy-robot" not in [u["user"] for u in inactive]


def test_unreadable_date_is_an_error():
    bad = REPORT.replace("2026-05-01T10:00:00+00:00", "yesterday-ish")
    with pytest.raises(ValueError):
        aws._inactive_users(bad, REPORT_NOW, 90)


def test_user_with_no_dates_is_an_error():
    header = REPORT.splitlines()[0]
    row = "ghost,arn,N/A,false,not_supported" + ",N/A" * 17
    with pytest.raises(ValueError, match="ghost"):
        aws._inactive_users(f"{header}\n{row}\n", REPORT_NOW, 90)


def test_unused_users_with_moto(iam, monkeypatch, no_sleep):
    add_console_user(iam, "intern-bob")
    result = aws.unused_users({})
    assert result["count"] == 0
    assert result["users_checked"] == 1
    assert result["report_generated_at"]
    assert no_sleep == [aws.REPORT_POLL_SECONDS]  # moto says STARTED once, then COMPLETE

    days_from_now(monkeypatch, 100)
    result = aws.unused_users({})
    assert result["users"] == ["intern-bob"]
    assert result["details"][0]["basis"] == "created, never used"


def test_unused_users_verdicts(iam, monkeypatch):
    check = {"field": "count", "op": "==", "value": 0}
    add_console_user(iam, "intern-bob")
    assert run("AWS-08", "aws.unused_users", check)["verdict"] == "PASS"
    days_from_now(monkeypatch, 100)
    r = run("AWS-08", "aws.unused_users", check)
    assert r["verdict"] == "FAIL"
    assert "intern-bob" in r["reason"]


def test_report_that_never_finishes_needs_review(monkeypatch, no_sleep):
    class SlowIam:
        def generate_credential_report(self):
            return {"State": "INPROGRESS"}

    monkeypatch.setattr(aws, "_iam", SlowIam)
    r = run("AWS-08", "aws.unused_users", {"field": "count", "op": "==", "value": 0})
    assert r["verdict"] == "NEEDS REVIEW"
    assert "not ready" in r["reason"]
    assert sum(no_sleep) == aws.REPORT_WAIT_SECONDS


# --- shared --------------------------------------------------------------------


def test_clients_retry_throttling(iam):
    retries = aws._iam().meta.config.retries
    assert retries["mode"] == "standard"
    assert retries["total_max_attempts"] == 5
