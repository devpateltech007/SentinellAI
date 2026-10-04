"""AWS connector: collects IAM, S3 and CloudTrail evidence with boto3 (read-only).

Credentials come from the AWS CLI profile (`aws login --profile compliancelens`),
selected with AWS_PROFILE in .env. Each collector takes the rule's `params` and
returns a dict. Collectors never change a setting; the only call that is not a
plain read is iam.generate_credential_report, which builds a report and changes
nothing in the account.
"""

import csv
import datetime
import io
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Try throttled calls up to 5 times in total, with backoff; any other error goes straight
# to the engine, which turns it into NEEDS REVIEW.
RETRY_CONFIG = Config(retries={"mode": "standard", "total_max_attempts": 5})

S3_BLOCK_FLAGS = (
    "BlockPublicAcls",
    "IgnorePublicAcls",
    "BlockPublicPolicy",
    "RestrictPublicBuckets",
)
REPORT_WAIT_SECONDS = 60  # give up on the credential report after this long
REPORT_POLL_SECONDS = 2
NO_DATE = {"", "N/A", "no_information", "not_supported"}  # credential report "no value" markers

_sleep = time.sleep  # tests replace this so they never really wait


def _now() -> datetime.datetime:
    # One place to read the clock, so tests can pretend 100 days have passed.
    return datetime.datetime.now(datetime.UTC)


def _client(service: str):
    # Create the client when a collector runs, not at import time. This picks up
    # the current AWS_PROFILE/region and lets tests replace AWS with moto.
    return boto3.client(service, config=RETRY_CONFIG)


def _iam():
    return _client("iam")


def _user_names(iam) -> list[str]:
    return [
        user["UserName"]
        for page in iam.get_paginator("list_users").paginate()
        for user in page["Users"]
    ]


def _bucket_names(s3) -> list[str]:
    return [
        bucket["Name"]
        for page in s3.get_paginator("list_buckets").paginate()
        for bucket in page["Buckets"]
    ]


def _error_code(error: ClientError) -> str:
    return error.response.get("Error", {}).get("Code", "")


# --------------------------------------------------------------- IAM ----


def iam_users(params: dict) -> dict:
    """Every IAM user name (used by HR-01 to compare with the employee list)."""
    names = _user_names(_iam())
    return {"count": len(names), "users": names}


def password_policy(params: dict) -> dict:
    """AWS-01: the account password policy. No policy at all counts as length 0."""
    iam = _iam()
    try:
        return iam.get_account_password_policy()["PasswordPolicy"]
    except iam.exceptions.NoSuchEntityException:
        return {"MinimumPasswordLength": 0}


def has_console_password(user: str, iam=None) -> bool:
    """True if the IAM user can log in to the AWS console."""
    iam = iam or _iam()
    try:
        iam.get_login_profile(UserName=user)
        return True
    except iam.exceptions.NoSuchEntityException:
        return False


def users_without_mfa(params: dict) -> dict:
    """AWS-02: console users that have no MFA device.

    Only console users need MFA (CIS). Access-key-only users, such as the tool's
    own audit user, are skipped; otherwise they would always fail the rule.
    """
    iam = _iam()
    missing = [
        name
        for name in _user_names(iam)
        if has_console_password(name, iam) and not iam.list_mfa_devices(UserName=name)["MFADevices"]
    ]
    return {"count": len(missing), "users": missing}


def root_account_mfa(params: dict) -> dict:
    """AWS-03: whether the root user has MFA (1) or not (0), plus root access keys."""
    summary = _iam().get_account_summary()["SummaryMap"]
    return {
        "AccountMFAEnabled": summary.get("AccountMFAEnabled"),
        "AccountAccessKeysPresent": summary.get("AccountAccessKeysPresent"),
    }


def access_key_age(params: dict) -> dict:
    """AWS-04: active access keys older than `max_age_days` (default 90).

    Inactive keys can't be used, so they are skipped. No keys at all is a PASS:
    there is nothing old to rotate.
    """
    max_age = int(params.get("max_age_days", 90))
    iam, now = _iam(), _now()
    old, checked = [], 0
    for user in _user_names(iam):
        for page in iam.get_paginator("list_access_keys").paginate(UserName=user):
            for key in page["AccessKeyMetadata"]:
                if key["Status"] != "Active":
                    continue
                checked += 1
                age = (now - key["CreateDate"]).days
                if age > max_age:
                    # Only the last 4 characters: enough to find the key, not a full ID.
                    key_end = key["AccessKeyId"][-4:]
                    old.append({"user": user, "key": f"...{key_end}", "age_days": age})
    return {"count": len(old), "keys": old, "active_keys_checked": checked, "max_age_days": max_age}


def _credential_report(iam) -> tuple[str, str]:
    """Ask AWS for the credential report and wait (up to a limit) until it is ready.

    AWS rebuilds the report at most every 4 hours, so it can be a little old.
    """
    for _ in range(REPORT_WAIT_SECONDS // REPORT_POLL_SECONDS):
        if iam.generate_credential_report()["State"] == "COMPLETE":
            break
        _sleep(REPORT_POLL_SECONDS)
    else:
        raise TimeoutError(f"credential report not ready after {REPORT_WAIT_SECONDS}s")
    report = iam.get_credential_report()
    return report["Content"].decode("utf-8"), report["GeneratedTime"].isoformat()


def _report_date(value: str | None) -> datetime.datetime | None:
    """A credential-report date, or None for its "no value" markers (N/A, no_information...)."""
    if value is None or value.strip() in NO_DATE:
        return None
    return datetime.datetime.fromisoformat(value.strip())


def _inactive_users(report_csv: str, now: datetime.datetime, max_days: int) -> tuple[list, int]:
    """Users with no activity for more than `max_days`, from a credential report.

    Activity is the newest of: password last used, access key 1 or 2 last used.
    A user who never signed in is measured from when the user was created, so a
    brand-new user is not counted as inactive. The root user is skipped (AWS-03).
    Returns (inactive users, number of users checked).
    """
    inactive, checked = [], 0
    for row in csv.DictReader(io.StringIO(report_csv)):
        if row["user"] == "<root_account>":
            continue
        checked += 1
        used = [
            _report_date(row.get(column))
            for column in (
                "password_last_used",
                "access_key_1_last_used_date",
                "access_key_2_last_used_date",
            )
        ]
        used = [date for date in used if date]
        if used:
            last, basis = max(used), "last used"
        else:
            last, basis = _report_date(row.get("user_creation_time")), "created, never used"
        if last is None:
            raise ValueError(f"credential report has no usable date for user {row['user']}")
        days = (now - last).days
        if days > max_days:
            inactive.append(
                {"user": row["user"], "since": last.isoformat(), "basis": basis, "days": days}
            )
    return inactive, checked


def unused_users(params: dict) -> dict:
    """AWS-08: IAM users with no sign-in or key use for more than `max_inactive_days` (90)."""
    max_days = int(params.get("max_inactive_days", 90))
    report, generated_at = _credential_report(_iam())
    inactive, checked = _inactive_users(report, _now(), max_days)
    return {
        "count": len(inactive),
        "users": [entry["user"] for entry in inactive],
        "details": inactive,
        "users_checked": checked,
        "max_inactive_days": max_days,
        "report_generated_at": generated_at,
    }


# ---------------------------------------------------------------- S3 ----


def _account_public_access_block() -> dict:
    """Account-wide Block Public Access flags. Recorded for context only."""
    try:
        account = _client("sts").get_caller_identity()["Account"]
        config = _client("s3control").get_public_access_block(AccountId=account)
        flags = config["PublicAccessBlockConfiguration"]
        return {flag: bool(flags.get(flag, False)) for flag in S3_BLOCK_FLAGS}
    except ClientError as e:
        if _error_code(e) == "NoSuchPublicAccessBlockConfiguration":
            return {flag: False for flag in S3_BLOCK_FLAGS}
        return {"error": str(e)}


def s3_public_access(params: dict) -> dict:
    """AWS-05: whether each bucket has all four Block Public Access flags turned on.

    A bucket with no Block Public Access settings counts as all four flags off.
    """
    s3 = _client("s3")
    flags_by_bucket = {}
    for name in _bucket_names(s3):
        try:
            config = s3.get_public_access_block(Bucket=name)["PublicAccessBlockConfiguration"]
        except ClientError as e:
            if _error_code(e) != "NoSuchPublicAccessBlockConfiguration":
                raise
            config = {}
        flags_by_bucket[name] = {flag: bool(config.get(flag, False)) for flag in S3_BLOCK_FLAGS}
    return {
        "buckets_fully_blocked": {name: all(f.values()) for name, f in flags_by_bucket.items()},
        "bucket_flags": flags_by_bucket,
        "account_flags": _account_public_access_block(),
    }


def s3_versioning(params: dict) -> dict:
    """AWS-06: whether versioning is turned on for each bucket."""
    s3 = _client("s3")
    status = {
        # No Status at all means versioning was never turned on.
        name: s3.get_bucket_versioning(Bucket=name).get("Status") or "NeverEnabled"
        for name in _bucket_names(s3)
    }
    return {
        "versioning_enabled": {name: value == "Enabled" for name, value in status.items()},
        "versioning_status": status,
    }


# -------------------------------------------------------- CloudTrail ----


def cloudtrail_logging(params: dict) -> dict:
    """AWS-07: every trail and whether it is logging right now.

    Shadow trails (multi-region trails from another region) are included, and
    their status is read by ARN so it works from any region.
    """
    cloudtrail = _client("cloudtrail")
    trails = []
    for trail in cloudtrail.describe_trails(includeShadowTrails=True)["trailList"]:
        status = cloudtrail.get_trail_status(Name=trail["TrailARN"])
        trails.append(
            {
                "name": trail["Name"],
                "home_region": trail.get("HomeRegion"),
                "multi_region": trail.get("IsMultiRegionTrail"),
                "is_logging": bool(status.get("IsLogging")),
            }
        )
    logging = [trail["name"] for trail in trails if trail["is_logging"]]
    return {"logging_count": len(logging), "logging_trails": logging, "trails": trails}
