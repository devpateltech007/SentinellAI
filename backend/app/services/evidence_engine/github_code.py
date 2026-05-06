"""GitHub Repository Code Scanning Connector for Evidence Engine.

Scans repository contents for security-relevant configuration files
like Terraform, Dockerfiles, and Kubernetes manifests.
"""

import base64
import fnmatch
import logging
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.models.evidence import EvidenceSourceType
from app.services.evidence_engine.base import ConnectorInterface, NormalizedEvidence, RawEvidence

logger = logging.getLogger(__name__)


class GitHubCodeConnector(ConnectorInterface):
    """Scans repository contents for security-relevant configuration files."""

    # Files that are compliance-relevant
    SCAN_PATTERNS = [
        ".github/workflows/*.yml",
        ".github/SECURITY.md",
        "*.tf",
        "*.tfvars",
        "Dockerfile",
        "docker-compose*.yml",
        "kubernetes/*.yaml",
        "k8s/*.yaml",
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

    async def _get_default_branch(self, client: httpx.AsyncClient) -> str:
        """Fetch the repository's default branch dynamically."""
        resp = await client.get(self.base_url, headers=self._headers)
        resp.raise_for_status()
        return resp.json().get("default_branch", "main")

    async def collect(self) -> list[RawEvidence]:
        """Collect raw evidence from the GitHub repository."""
        async with httpx.AsyncClient() as client:
            # 1. Get default branch
            default_branch = await self._get_default_branch(client)

            # 2. Get full repo tree in one call
            tree_resp = await client.get(
                f"{self.base_url}/git/trees/{default_branch}?recursive=1",
                headers=self._headers,
            )
            tree_resp.raise_for_status()

            # Rate limit check after tree call
            remaining = int(tree_resp.headers.get("X-RateLimit-Remaining", "5000"))
            if remaining < 100:
                logger.warning("GitHub API rate limit critical (Remaining: %d). Skipping content fetch.", remaining)
                return []

            tree = tree_resp.json()

            # 3. Pattern match files
            matching_files = []
            for item in tree.get("tree", []):
                if item.get("type") != "blob":
                    continue
                path = item.get("path", "")
                for pattern in self.SCAN_PATTERNS:
                    if fnmatch.fnmatch(path, pattern):
                        matching_files.append(item)
                        break

            # 4. Fetch content for matching files
            evidence = []
            for file_item in matching_files:
                path = file_item["path"]
                content_resp = await client.get(
                    f"{self.base_url}/contents/{path}",
                    headers=self._headers,
                )
                if content_resp.status_code != 200:
                    logger.warning(f"Failed to fetch {path}: {content_resp.status_code}")
                    continue

                data = content_resp.json()

                # Check file size (reject > 1MB)
                size_bytes = data.get("size", 0)
                if size_bytes > 1024 * 1024:
                    logger.warning(f"File {path} too large ({size_bytes} bytes). Skipping.")
                    continue

                if "content" in data:
                    file_content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                else:
                    file_content = ""

                evidence.append(RawEvidence(
                    source_type=EvidenceSourceType.GITHUB_CODE,
                    source_ref=data.get("html_url", f"github://{self.owner}/{self.repo}/{path}"),
                    raw_data={
                        "filename": path.split("/")[-1],
                        "path": path,
                        "content": file_content,
                        "sha": file_item["sha"],
                        "size_bytes": size_bytes,
                    },
                    collected_at=datetime.now(timezone.utc),
                ))
            return evidence

    def validate(self, evidence: RawEvidence) -> bool:
        """Validate that the evidence has required fields."""
        if evidence.source_type != EvidenceSourceType.GITHUB_CODE:
            return False

        data = evidence.raw_data
        if not isinstance(data, dict):
            return False

        required_keys = {"content", "path", "sha"}
        if not required_keys.issubset(data.keys()):
            return False

        # Optional validation: if we wanted to strictly enforce the 1MB limit here
        # (we already enforce during collect)
        if data.get("size_bytes", 0) > 1024 * 1024:
            return False

        return True

    def normalize(self, evidence: RawEvidence) -> NormalizedEvidence:
        """Normalize the raw evidence into a standard format."""
        data = evidence.raw_data
        content = data.get("content", "")

        # Truncate for DB storage
        truncated_content = content[:5000]

        import hashlib
        sha256_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        return NormalizedEvidence(
            source_type=evidence.source_type,
            source_ref=evidence.source_ref,
            collected_at=evidence.collected_at,
            sha256_hash=sha256_hash,
            content_json={
                "filename": data.get("filename", ""),
                "path": data.get("path", ""),
                "sha": data.get("sha", ""),
                "size_bytes": data.get("size_bytes", 0),
                "content": truncated_content,
            },
            redacted=False,
        )
