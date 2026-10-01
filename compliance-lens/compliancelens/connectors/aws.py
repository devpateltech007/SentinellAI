"""AWS connector: collects IAM evidence with boto3 (read-only).

Credentials come from the AWS CLI profile (`aws configure`), selected with
AWS_PROFILE in .env. Each collector takes the rule's `params` and returns a dict.
"""

import boto3


def _iam():
    # Create the client when a collector runs, not at import time. This picks up
    # the current AWS_PROFILE/region and lets tests replace AWS with moto.
    return boto3.client("iam")


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
    names = [
        user["UserName"]
        for page in iam.get_paginator("list_users").paginate()
        for user in page["Users"]
    ]
    missing = [
        name
        for name in names
        if has_console_password(name, iam) and not iam.list_mfa_devices(UserName=name)["MFADevices"]
    ]
    return {"count": len(missing), "users": missing}
