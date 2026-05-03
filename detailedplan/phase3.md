# Phase 3 — Connector Framework Hardening

> **Estimated Total**: 24 engineering hours
> **Dependencies**: Phase 1 Task 1.4 (redaction middleware) should be done first so new connectors automatically get PII scrubbing.
> **Rationale**: The evidence engine currently only has two connectors (GitHub Actions + IaC Config), and the connector management API lacks update/delete/health-check capabilities. This phase adds a code-scanning connector, IaC-specific parsers, and full connector lifecycle management.

---

## Current State

| Component | File | Status |
|---|---|---|
| ConnectorInterface (ABC) | `evidence_engine/base.py` | ✅ Solid contract: collect → validate → normalize |
| GitHub Actions Connector | `evidence_engine/github_actions.py` | ✅ Fetches workflow runs with retry |
| IaC Config Connector | `evidence_engine/iac_config.py` | 🟡 Reads files but no semantic parsing of encryption/RBAC flags |
| Connector API | `api/connectors.py` | 🟡 Create + List + Trigger only — no Update, Delete, or Health |
| Evidence Tasks | `workers/evidence_tasks.py` | 🟡 Only handles `github_actions` source type |
| Scheduling | `workers/celery_app.py` | 🔴 All connectors run every 5 min regardless of their `schedule` field |

---

## Task 3.1: Add GitHub Repository Code Scanning Connector

**Estimated Time**: 4 hours

**Files to Create**:
- `backend/app/services/evidence_engine/github_code.py`

**Files to Reference**:
- `backend/app/services/evidence_engine/base.py` — `ConnectorInterface` ABC
- `backend/app/services/evidence_engine/github_actions.py` — reference implementation for GitHub API auth + retry pattern

**Detailed Logic Brief**:

The existing `GitHubActionsConnector` only fetches CI/CD workflow run metadata (pass/fail status, branch, timing). It does NOT look at actual source code. For compliance checks like "Is encryption configured in your infrastructure?" or "Does the app have a SECURITY.md?", we need to scan the repository's file contents.

```python
class GitHubCodeConnector(ConnectorInterface):
    """Scans repository contents for security-relevant configuration files."""

    # Files that are compliance-relevant
    SCAN_PATTERNS = [
        ".github/workflows/*.yml",    # CI/CD security steps
        ".github/SECURITY.md",        # Incident response documentation
        "*.tf",                        # Terraform infrastructure
        "*.tfvars",                    # Terraform variables (check for secrets)
        "Dockerfile",                  # Container security
        "docker-compose*.yml",         # Service configuration
        "kubernetes/*.yaml",           # K8s manifests
        "k8s/*.yaml",                 # K8s manifests (alternate path)
    ]

    def __init__(self, owner: str, repo: str, token: str | None = None):
        self.owner = owner
        self.repo = repo
        self.token = token or settings.GITHUB_TOKEN
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
```

**The `collect()` method** works in two phases:

**Phase A — Tree Discovery**: Call `GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1` to get the full file tree in a single API call. Filter file paths against `SCAN_PATTERNS` using `fnmatch`. This is far more efficient than recursively calling the Contents API directory by directory.

```python
async def collect(self) -> list[RawEvidence]:
    async with httpx.AsyncClient() as client:
        # Get full repo tree in one call
        tree_resp = await client.get(
            f"{self.base_url}/git/trees/main?recursive=1",
            headers=self._headers,
        )
        tree_resp.raise_for_status()
        tree = tree_resp.json()

        matching_files = []
        for item in tree.get("tree", []):
            if item["type"] != "blob":
                continue
            for pattern in self.SCAN_PATTERNS:
                if fnmatch.fnmatch(item["path"], pattern):
                    matching_files.append(item)
                    break
```

**Phase B — Content Fetching**: For each matching file, call `GET /repos/{owner}/{repo}/contents/{path}`. GitHub returns Base64-encoded content. Decode it and store as `RawEvidence`.

```python
        evidence = []
        for file_item in matching_files:
            content_resp = await client.get(
                f"{self.base_url}/contents/{file_item['path']}",
                headers=self._headers,
            )
            content_resp.raise_for_status()
            data = content_resp.json()

            file_content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")

            evidence.append(RawEvidence(
                source_type="github_code",
                source_ref=data.get("html_url", ""),
                raw_data={
                    "filename": file_item["path"].split("/")[-1],
                    "path": file_item["path"],
                    "content": file_content,
                    "sha": file_item["sha"],
                    "size_bytes": file_item.get("size", 0),
                },
                collected_at=datetime.now(timezone.utc),
            ))
        return evidence
```

**Rate limiting**: GitHub API allows 5000 requests/hour for authenticated users. A typical repo might have 5-20 matching files, so each collection run uses 2-21 API calls. Add a rate-limit check by reading the `X-RateLimit-Remaining` header after the tree call; if < 100, log a warning and skip content fetching.

**The `validate()` method**: Check that `raw_data` contains `content`, `path`, and `sha`. Reject files larger than 1MB (likely not config files).

**The `normalize()` method**: Store `content` (truncated to 5000 chars for DB storage), `filename`, `path`, `sha`, and `size_bytes` in `content_json`. Compute SHA-256 over the full content string.

**Definition of Done**:
1. Point at a public repo (e.g., `hashicorp/terraform-provider-aws` or your own repo with `.tf` files).
2. `await connector.collect()` returns `RawEvidence` items with decoded Terraform/Dockerfile contents.
3. `validate()` accepts well-formed items, rejects items missing `content` or `sha`.
4. `normalize()` produces `NormalizedEvidence` with correct SHA-256 hash.

---

## Task 3.2: Add IaC Encryption Flag Parser

**Estimated Time**: 4 hours

**Files to Create**:
- `backend/app/services/evidence_engine/iac_parser.py`

**Detailed Logic Brief**:

The existing `IaCConfigConnector` collects raw file contents but does NO semantic analysis. A Terraform file with `server_side_encryption_configuration` block is stored as a raw string. The evaluator rules then do crude keyword matching (`"encrypt" in raw`). This task creates dedicated parsers that extract structured security flags.

```python
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
    if re.search(r'logging\s*\{|access_logs\s*\{|cloudtrail|cloudwatch', lower):
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
```

Similarly, create a Kubernetes parser:

```python
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
```

**How these parsers integrate**: The evaluator rules (Phase 4) will call these parsers on IaC evidence `content_json["content"]` to get structured booleans instead of doing raw string matching. For example, `check_encryption_at_rest` would call `parse_terraform_security(content)` and check `flags.encryption_at_rest` instead of `"encrypt" in raw_string`.

**Definition of Done**:
1. Terraform test: file containing `server_side_encryption_configuration { rule { apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }}}` → returns `TerraformSecurityFlags(encryption_at_rest=True, kms_managed=True, encryption_algorithm="aws:kms")`.
2. Terraform test: file with NO encryption blocks → returns `TerraformSecurityFlags(encryption_at_rest=False)`.
3. K8s test: manifest with `securityContext: { runAsNonRoot: true, readOnlyRootFilesystem: true }` → returns correct flags.
4. Write tests in `backend/tests/test_services/test_iac_parser.py` covering at least 5 variations of each file type.

---

## Task 3.3: Wire GitHub Code Connector into Evidence Tasks

**Estimated Time**: 3 hours

**Files to Edit**:
- `backend/app/workers/evidence_tasks.py` — add `github_code` branch
- `backend/app/models/evidence.py` — add `GITHUB_CODE` to enum

**Files to Create**:
- `backend/alembic/versions/007_github_code_source_type.py` — migration for new enum value

**Detailed Logic Brief**:

Currently `_collect_evidence_async()` only handles `github_actions` (line 152). Add a new branch for `github_code`:

```python
elif connector.source_type == "github_code":
    from app.services.evidence_engine.github_code import GitHubCodeConnector
    config = connector.config_json
    gc = GitHubCodeConnector(
        owner=config.get("owner", ""),
        repo=config.get("repo", ""),
    )
    raw_items = await gc.collect()
    count = 0
    for raw in raw_items:
        if gc.validate(raw):
            normalized = normalize_evidence(raw, DEFAULT_REDACTION_CONFIG)
            evidence = EvidenceItem(
                source_type=EvidenceSourceType.GITHUB_CODE,
                source_ref=normalized.source_ref,
                collected_at=normalized.collected_at,
                sha256_hash=normalized.sha256_hash,
                content_json=normalized.content_json,
                redacted=normalized.redacted,
            )
            db.add(evidence)
            count += 1
```

**Alembic migration for enum**: PostgreSQL enums require explicit `ALTER TYPE` to add values:

```python
def upgrade():
    op.execute("ALTER TYPE evidence_source_type_enum ADD VALUE IF NOT EXISTS 'github_code'")

def downgrade():
    # PostgreSQL does not support removing enum values easily
    pass
```

Update `EvidenceSourceType` enum in `models/evidence.py`:
```python
class EvidenceSourceType(enum.Enum):
    GITHUB_ACTIONS = "github_actions"
    IAC_CONFIG = "iac_config"
    GITHUB_CODE = "github_code"  # NEW
```

**Definition of Done**:
1. Run migration. Create connector via API: `POST /connectors` with `{"source_type": "github_code", "config_json": {"owner": "your-org", "repo": "your-repo"}}`.
2. Trigger: `POST /connectors/{id}/trigger`.
3. Verify evidence items appear in DB with `source_type = 'github_code'` and `content_json` containing decoded file contents.
4. Verify PII redaction ran (check container logs for redaction message from Task 1.4).

---

## Task 3.4: Add Connector Health Check Endpoint

**Estimated Time**: 3 hours

**Files to Edit**:
- `backend/app/api/connectors.py` — add health endpoint
- `backend/app/schemas/connector.py` — add response schema

**Detailed Logic Brief**:

Before triggering a full evidence collection (which is expensive and slow), users should be able to verify that a connector's credentials are valid and the target system is reachable.

**Pydantic v2 Schema**:
```python
class ConnectorHealthResponse(BaseModel):
    connector_id: UUID
    source_type: str
    reachable: bool
    rate_limit_remaining: int | None = None
    error: str | None = None
    checked_at: datetime
```

**Endpoint**:
```python
@router.get("/{connector_id}/health", response_model=ConnectorHealthResponse)
async def check_connector_health(
    connector_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_role(
        UserRole.ADMIN, UserRole.DEVOPS_ENGINEER, UserRole.COMPLIANCE_MANAGER
    )),
):
```

**For GitHub connectors** (`github_actions` or `github_code`): Make a lightweight `GET /repos/{owner}/{repo}` call. Parse `X-RateLimit-Remaining` from the response headers. If the call succeeds, `reachable = True`. If it returns 401, the token is invalid. If 404, the repo doesn't exist or the token lacks access.

```python
config = connector.config_json
async with httpx.AsyncClient() as client:
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{config['owner']}/{config['repo']}",
            headers={"Authorization": f"Bearer {settings.GITHUB_TOKEN}", ...},
            timeout=10.0,
        )
        return ConnectorHealthResponse(
            connector_id=connector.id,
            source_type=connector.source_type,
            reachable=resp.status_code == 200,
            rate_limit_remaining=int(resp.headers.get("X-RateLimit-Remaining", 0)),
            error=None if resp.status_code == 200 else f"HTTP {resp.status_code}: {resp.text[:200]}",
            checked_at=datetime.now(timezone.utc),
        )
    except httpx.HTTPError as e:
        return ConnectorHealthResponse(
            connector_id=connector.id,
            source_type=connector.source_type,
            reachable=False,
            error=str(e),
            checked_at=datetime.now(timezone.utc),
        )
```

**For IaC connectors**: Check if `config_path` exists on the filesystem.

**Definition of Done**:
1. Health check on valid GitHub connector → `reachable: true`, `rate_limit_remaining: 4950` (or similar).
2. Health check with invalid token → `reachable: false`, `error: "HTTP 401: Bad credentials"`.
3. Health check with nonexistent repo → `reachable: false`, `error: "HTTP 404: Not Found"`.
4. Frontend can call this before showing "Trigger" button to warn user if connector is broken.

---

## Task 3.5: Add Connector CRUD (Update + Delete)

**Estimated Time**: 4 hours

**Files to Edit**:
- `backend/app/api/connectors.py` — add PUT and DELETE endpoints
- `backend/app/schemas/connector.py` — add update schema

**Files to Create**:
- `backend/alembic/versions/008_connector_is_active.py`

**Detailed Logic Brief**:

Currently connectors can only be created and listed. Add full lifecycle management.

**Migration** — add `is_active` column:
```python
def upgrade():
    op.add_column("connectors", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))

def downgrade():
    op.drop_column("connectors", "is_active")
```

**Update Schema**:
```python
class ConnectorUpdate(BaseModel):
    config_json: dict | None = None
    schedule: str | None = None
    is_active: bool | None = None
```

**PUT Endpoint**: Updates only the provided fields (partial update pattern). Log the action to `audit_logs`.

**DELETE Endpoint**: Soft-delete by setting `is_active = false`. Don't actually remove the row — we need the audit trail. Return 204 No Content.

**Update scheduled collection** in `evidence_tasks.py` `_scheduled_evidence_async()`:
```python
result = await db.execute(
    select(Connector).where(Connector.is_active == True)  # CHANGED: filter active only
)
```

**Definition of Done**:
1. `PUT /connectors/{id}` with `{"schedule": "0 */12 * * *"}` → updates the connector. Verify in DB.
2. `DELETE /connectors/{id}` → connector's `is_active` is now `false`. Row still exists.
3. Scheduled evidence collection task skips inactive connectors (check Celery logs).
4. Audit logs contain entries for both update and delete actions.

---

## Task 3.6: Add Cron Validation for Connector Scheduling

**Estimated Time**: 3 hours

**Files to Edit**:
- `backend/app/schemas/connector.py` — add Pydantic validator
- `backend/app/workers/evidence_tasks.py` — respect per-connector schedules
- `backend/requirements.txt` — add `croniter`

**Detailed Logic Brief**:

Currently the Celery beat schedule runs `scheduled_evidence_collection` every 5 minutes for ALL connectors, ignoring each connector's individual `schedule` field (which is stored but never read). Fix this in two parts.

**Part A — Validate cron syntax** at API creation time using Pydantic v2 field validator:

```python
from croniter import croniter

class ConnectorCreate(BaseModel):
    source_type: str
    config_json: dict
    schedule: str = "0 */6 * * *"  # default: every 6 hours

    @field_validator("schedule")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        if not croniter.is_valid(v):
            raise ValueError(f"Invalid cron expression: '{v}'. Example: '0 */6 * * *'")
        return v
```

**Part B — Respect individual schedules** in `_scheduled_evidence_async()`:

```python
from croniter import croniter

async def _scheduled_evidence_async() -> dict:
    async with async_session() as db:
        result = await db.execute(
            select(Connector).where(Connector.is_active == True)
        )
        connectors = result.scalars().all()

    now = datetime.now(timezone.utc)
    dispatched = 0
    for c in connectors:
        # Check if this connector should run now based on its cron schedule
        cron = croniter(c.schedule, c.last_run_at or now - timedelta(days=1))
        next_run = cron.get_next(datetime)
        if next_run <= now:
            collect_evidence.delay(str(c.id))
            dispatched += 1

    return {"status": "scheduled", "connectors_dispatched": dispatched}
```

The Celery beat still runs every 5 minutes (as a polling interval), but each individual connector only gets dispatched if its cron schedule says it's time. This means a connector with `"0 */12 * * *"` only runs every 12 hours, even though the beat checks every 5 minutes.

**Add `croniter` to `requirements.txt`**: `croniter>=2.0.0`

**Definition of Done**:
1. `POST /connectors` with `{"schedule": "not-a-cron", ...}` → returns 422 with clear error message.
2. `POST /connectors` with `{"schedule": "0 */6 * * *", ...}` → creates successfully.
3. Create two connectors: one with `"* * * * *"` (every minute) and one with `"0 0 * * *"` (daily). Wait 10 minutes. Only the first connector should have been triggered. The second should remain untouched (verify `last_run_at` unchanged).

---

## Phase 3 — Dependency Graph

```
Task 3.1 (GitHub Code Connector)   — No dependencies
Task 3.2 (IaC Parser)              — No dependencies
Task 3.3 (Wire into Evidence Tasks) — Depends on 3.1
Task 3.4 (Health Check Endpoint)   — No dependencies
Task 3.5 (CRUD Update + Delete)    — No dependencies
Task 3.6 (Cron Validation)         — Depends on 3.5 (needs is_active column)
```

**Parallelization**: Tasks 3.1, 3.2, 3.4, and 3.5 can all start simultaneously. Task 3.3 follows 3.1. Task 3.6 follows 3.5.

**Recommended assignment**:
- **Person A**: Tasks 3.1 → 3.3 (new connector end-to-end)
- **Person B**: Task 3.2 (IaC parsers + tests)
- **Person C**: Tasks 3.5 → 3.6 (CRUD + scheduling)
- **Person D**: Task 3.4 (health check — small task, can pair with Phase 2 or Phase 4 work)
