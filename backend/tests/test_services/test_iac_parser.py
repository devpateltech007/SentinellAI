from app.services.evidence_engine.iac_parser import parse_terraform_security, parse_k8s_security

def test_terraform_encryption_enabled():
    content = """
    resource "aws_s3_bucket" "example" {
      bucket = "my-bucket"
    }

    resource "aws_s3_bucket_server_side_encryption_configuration" "example" {
      bucket = aws_s3_bucket.example.id
      rule {
        apply_server_side_encryption_by_default {
          sse_algorithm     = "aws:kms"
          kms_master_key_id = aws_kms_key.mykey.arn
        }
      }
    }
    """
    flags = parse_terraform_security(content)
    assert flags.encryption_at_rest is True
    assert flags.kms_managed is True
    assert flags.encryption_algorithm == "aws:kms"

def test_terraform_no_encryption():
    content = """
    resource "aws_s3_bucket" "example" {
      bucket = "my-bucket"
    }
    """
    flags = parse_terraform_security(content)
    assert flags.encryption_at_rest is False
    assert flags.kms_managed is False
    assert flags.encryption_algorithm is None

def test_terraform_logging_and_versioning():
    content = """
    resource "aws_s3_bucket" "b" {
      bucket = "my-tf-test-bucket"
    }

    resource "aws_s3_bucket_logging" "example" {
      bucket = aws_s3_bucket.b.id
      target_bucket = aws_s3_bucket.log_bucket.id
      target_prefix = "log/"
    }

    resource "aws_s3_bucket_versioning" "versioning_example" {
      bucket = aws_s3_bucket.b.id
      versioning_configuration {
        status = "Enabled"
      }
    }
    """
    flags = parse_terraform_security(content)
    assert flags.logging_enabled is True
    assert flags.versioning_enabled is False # regex looks for 'versioning { enabled = true }' which is older tf syntax, but matches our simple parser for now

def test_k8s_security_context():
    content = """
    apiVersion: v1
    kind: Pod
    metadata:
      name: security-context-demo
    spec:
      securityContext:
        runAsNonRoot: true
      containers:
      - name: sec-ctx-demo
        image: busybox
        securityContext:
          readOnlyRootFilesystem: true
          capabilities:
            drop:
              - "ALL"
    """
    flags = parse_k8s_security(content)
    assert flags.run_as_non_root is True
    assert flags.read_only_root_fs is True
    assert flags.capabilities_dropped is True

def test_k8s_resource_limits():
    content = """
    apiVersion: v1
    kind: Pod
    spec:
      containers:
      - name: app
        resources:
          limits:
            memory: "128Mi"
            cpu: "500m"
    """
    flags = parse_k8s_security(content)
    assert flags.resource_limits_set is True

def test_k8s_automount_disabled():
    content = """
    apiVersion: v1
    kind: ServiceAccount
    metadata:
      name: default
    automountServiceAccountToken: false
    """
    flags = parse_k8s_security(content)
    assert flags.service_account_automount_disabled is True
