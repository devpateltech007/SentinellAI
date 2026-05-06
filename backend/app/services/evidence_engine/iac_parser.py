"""IaC configuration parsers for extracting security-relevant flags."""

import re
from dataclasses import dataclass


@dataclass
class TerraformSecurityFlags:
    encryption_at_rest: bool = False
    kms_managed: bool = False
    encryption_algorithm: str | None = None
    logging_enabled: bool = False
    versioning_enabled: bool = False
    public_access_blocked: bool = False
    ssl_policy: str | None = None

def parse_terraform_security(content: str) -> TerraformSecurityFlags:
    """Extract security configuration flags from a Terraform .tf file."""
    flags = TerraformSecurityFlags()
    lower = content.lower()

    # Encryption at rest
    encryption_patterns = [
        r'server_side_encryption_configuration\s*\{',
        r'sse_algorithm\s*=\s*"(aws:kms|aes256|AES256)"',
        r'encryption_configuration\s*\{',
        r'encrypted\s*=\s*true',
    ]
    for pattern in encryption_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            flags.encryption_at_rest = True
            break

    # KMS managed
    if re.search(r'kms_key_id\s*=|kms_master_key_id\s*=', content, re.IGNORECASE):
        flags.kms_managed = True

    # Algorithm extraction
    algo_match = re.search(r'sse_algorithm\s*=\s*"([^"]+)"', content, re.IGNORECASE)
    if algo_match:
        flags.encryption_algorithm = algo_match.group(1)

    # Logging
    if re.search(r'logging\s*\{|access_logs\s*\{|cloudtrail|cloudwatch|aws_s3_bucket_logging', lower):
        flags.logging_enabled = True

    # Versioning
    if re.search(r'versioning\s*\{\s*enabled\s*=\s*true', lower):
        flags.versioning_enabled = True

    # Public access
    if re.search(r'block_public_acls\s*=\s*true|block_public_policy\s*=\s*true', lower):
        flags.public_access_blocked = True

    # SSL/TLS policy
    ssl_match = re.search(r'ssl_policy\s*=\s*"([^"]+)"', content)
    if ssl_match:
        flags.ssl_policy = ssl_match.group(1)

    return flags

@dataclass
class K8sSecurityFlags:
    run_as_non_root: bool = False
    read_only_root_fs: bool = False
    capabilities_dropped: bool = False
    resource_limits_set: bool = False
    service_account_automount_disabled: bool = False

def parse_k8s_security(content: str) -> K8sSecurityFlags:
    """Extract security context flags from Kubernetes YAML manifests."""
    flags = K8sSecurityFlags()

    if re.search(r'runAsNonRoot:\s*true', content):
        flags.run_as_non_root = True
    if re.search(r'readOnlyRootFilesystem:\s*true', content):
        flags.read_only_root_fs = True
    if re.search(r'drop:\s*\n\s*-\s*["\']?ALL["\']?', content, re.IGNORECASE):
        flags.capabilities_dropped = True
    if re.search(r'limits:\s*\n\s*(cpu|memory):', content):
        flags.resource_limits_set = True
    if re.search(r'automountServiceAccountToken:\s*false', content):
        flags.service_account_automount_disabled = True

    return flags
