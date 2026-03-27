"""GitHub Actions evidence connector.

Collects build logs, test result artifacts, and workflow run metadata
from the GitHub Actions API. Implements ConnectorInterface.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.services.evidence_engine.base import ConnectorInterface, NormalizedEvidence, RawEvidence
from app.services.evidence_engine.normalizer import compute_sha256


class GitHubActionsConnector(ConnectorInterface):
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

    async def collect(self) -> list[RawEvidence]:
        """Fetch recent workflow runs from GitHub Actions API.

        Implements retry with exponential backoff (NFR-05).
        """
        evidence: list[RawEvidence] = []
        max_retries = 3

        async with httpx.AsyncClient() as client:
            for attempt in range(max_retries):
                try:
                    response = await client.get(
                        f"{self.base_url}/actions/runs",
                        headers=self._headers,
                        params={"per_page": 10},
                    )
                    response.raise_for_status()
                    data = response.json()

                    for run in data.get("workflow_runs", []):
                        evidence.append(
                            RawEvidence(
                                source_type="github_actions",
                                source_ref=run.get("html_url", ""),
                                raw_data={
                                    "run_id": run["id"],
                                    "name": run.get("name"),
                                    "status": run.get("status"),
                                    "conclusion": run.get("conclusion"),
                                    "head_branch": run.get("head_branch"),
                                    "created_at": run.get("created_at"),
                                    "updated_at": run.get("updated_at"),
                                    "run_attempt": run.get("run_attempt"),
                                    "workflow_id": run.get("workflow_id"),
                                },
                                collected_at=datetime.now(timezone.utc),
                            )
                        )
                    break
                except httpx.HTTPStatusError:
                    if attempt == max_retries - 1:
                        raise
                    import asyncio
                    await asyncio.sleep(2 ** attempt)

        return evidence

    def validate(self, raw: RawEvidence) -> bool:
        return bool(
            raw.raw_data.get("run_id")
            and raw.source_ref
            and raw.source_type == "github_actions"
        )

    def normalize(self, raw: RawEvidence) -> NormalizedEvidence:
        content = raw.raw_data.copy()
        content_str = json.dumps(content, sort_keys=True)

        return NormalizedEvidence(
            source_type=raw.source_type,
            source_ref=raw.source_ref,
            content_json=content,
            sha256_hash=compute_sha256(content_str),
            collected_at=raw.collected_at or datetime.now(timezone.utc),
        )
