"""AWS connector tests against a fake AWS account (moto). Both verdict states per rule."""

import boto3
import pytest
from moto import mock_aws

from compliancelens.connectors import aws


@pytest.fixture
def iam():
    with mock_aws():
        yield boto3.client("iam")


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
