"""Infrastructure-as-Code configuration evidence connector.

Collects configuration snapshots from Terraform .tf files,
Kubernetes YAML manifests, or AWS Config. Implements ConnectorInterface.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.services.evidence_engine.base import ConnectorInterface, NormalizedEvidence, RawEvidence
from app.services.evidence_engine.normalizer import compute_sha256


class IaCConfigConnector(ConnectorInterface):
    def __init__(self, config_path: str, config_type: str = "terraform"):
        """
        Args:
            config_path: Path to the directory containing IaC config files.
            config_type: One of "terraform", "kubernetes", "aws_config".
        """
        self.config_path = Path(config_path)
        self.config_type = config_type
        self._extensions = {
            "terraform": [".tf", ".tfvars"],
            "kubernetes": [".yaml", ".yml"],
            "aws_config": [".json"],
        }

    async def collect(self) -> list[RawEvidence]:
        """Scan the config directory and collect all relevant config files."""
        evidence: list[RawEvidence] = []
        extensions = self._extensions.get(self.config_type, [])

        if not self.config_path.exists():
            return evidence

        for filepath in self.config_path.rglob("*"):
            if filepath.is_file() and filepath.suffix in extensions:
                content = filepath.read_text()
                evidence.append(
                    RawEvidence(
                        source_type="iac_config",
                        source_ref=str(filepath),
                        raw_data={
                            "filename": filepath.name,
                            "path": str(filepath),
                            "config_type": self.config_type,
                            "content": content,
                            "size_bytes": filepath.stat().st_size,
                            "last_modified": datetime.fromtimestamp(
                                filepath.stat().st_mtime, tz=timezone.utc
                            ).isoformat(),
                        },
                        collected_at=datetime.now(timezone.utc),
                    )
                )

        return evidence

    def validate(self, raw: RawEvidence) -> bool:
        return bool(
            raw.raw_data.get("content")
            and raw.raw_data.get("filename")
            and raw.source_type == "iac_config"
        )

    def normalize(self, raw: RawEvidence) -> NormalizedEvidence:
        content = {
            "filename": raw.raw_data["filename"],
            "config_type": raw.raw_data.get("config_type"),
            "content_preview": raw.raw_data.get("content", "")[:2000],
            "size_bytes": raw.raw_data.get("size_bytes"),
            "last_modified": raw.raw_data.get("last_modified"),
        }
        full_content = raw.raw_data.get("content", "")

        return NormalizedEvidence(
            source_type=raw.source_type,
            source_ref=raw.source_ref,
            content_json=content,
            sha256_hash=compute_sha256(full_content),
            collected_at=raw.collected_at or datetime.now(timezone.utc),
        )
