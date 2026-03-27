"""Abstract base class for all evidence connectors.

Every connector must implement collect(), validate(), and normalize().
New connectors should require < 20 lines changed outside their own module (NFR-08).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawEvidence:
    source_type: str
    source_ref: str
    raw_data: dict
    collected_at: datetime | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class NormalizedEvidence:
    source_type: str
    source_ref: str
    content_json: dict
    sha256_hash: str
    collected_at: datetime
    redacted: bool = False


class ConnectorInterface(ABC):
    """Base interface that all evidence connectors must implement."""

    @abstractmethod
    async def collect(self) -> list[RawEvidence]:
        """Fetch raw evidence artifacts from the external source.

        Must implement retry with exponential backoff on transient failures (NFR-05).
        """
        ...

    @abstractmethod
    def validate(self, raw: RawEvidence) -> bool:
        """Validate that a raw evidence artifact is well-formed and complete."""
        ...

    @abstractmethod
    def normalize(self, raw: RawEvidence) -> NormalizedEvidence:
        """Transform raw evidence into the platform's internal schema.

        Must compute SHA-256 hash and apply PII/PHI redaction if configured.
        """
        ...
