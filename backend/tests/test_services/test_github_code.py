import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.evidence_engine.github_code import GitHubCodeConnector
from app.models.evidence import EvidenceSourceType
from app.services.evidence_engine.base import RawEvidence
from datetime import datetime, timezone
from datetime import datetime, timezone

@pytest.fixture
def connector():
    return GitHubCodeConnector(owner="testowner", repo="testrepo", token="fake-token")

@pytest.mark.asyncio
async def test_collect_success(connector):
    mock_tree_response = MagicMock()
    mock_tree_response.headers = {"X-RateLimit-Remaining": "4000"}
    mock_tree_response.json.return_value = {
        "tree": [
            {"path": "main.tf", "type": "blob", "sha": "123"},
            {"path": "README.md", "type": "blob", "sha": "456"},
            {"path": ".github/workflows/deploy.yml", "type": "blob", "sha": "789"},
        ]
    }
    
    mock_content_response_tf = MagicMock()
    mock_content_response_tf.status_code = 200
    mock_content_response_tf.json.return_value = {
        "size": 500,
        "content": "dGVzdCBjb250ZW50", # "test content" base64
        "html_url": "https://github.com/testowner/testrepo/blob/main/main.tf"
    }

    mock_content_response_yml = MagicMock()
    mock_content_response_yml.status_code = 200
    mock_content_response_yml.json.return_value = {
        "size": 300,
        "content": "YW5vdGhlciB0ZXN0", # "another test" base64
        "html_url": "https://github.com/testowner/testrepo/blob/main/.github/workflows/deploy.yml"
    }

    async def mock_get(url, headers, **kwargs):
        if url.endswith("/git/trees/main?recursive=1"):
            return mock_tree_response
        elif url.endswith("/contents/main.tf"):
            return mock_content_response_tf
        elif url.endswith("/contents/.github/workflows/deploy.yml"):
            return mock_content_response_yml
        elif url.endswith("testrepo"):
            mock_repo_resp = MagicMock()
            mock_repo_resp.json.return_value = {"default_branch": "main"}
            mock_repo_resp.raise_for_status = MagicMock()
            return mock_repo_resp
        return MagicMock()

    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=mock_get)):
        evidence = await connector.collect()
        
    assert len(evidence) == 2
    assert evidence[0].raw_data["path"] == "main.tf"
    assert evidence[0].raw_data["content"] == "test content"
    assert evidence[1].raw_data["path"] == ".github/workflows/deploy.yml"
    assert evidence[1].raw_data["content"] == "another test"

@pytest.mark.asyncio
async def test_collect_rate_limit(connector):
    mock_repo_resp = MagicMock()
    mock_repo_resp.json.return_value = {"default_branch": "main"}
    
    mock_tree_response = MagicMock()
    mock_tree_response.headers = {"X-RateLimit-Remaining": "50"} # Critical rate limit
    mock_tree_response.json.return_value = {"tree": [{"path": "main.tf", "type": "blob", "sha": "123"}]}
    
    async def mock_get(url, headers, **kwargs):
        if url.endswith("testrepo"): return mock_repo_resp
        return mock_tree_response

    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=mock_get)):
        evidence = await connector.collect()
        
    assert len(evidence) == 0

def test_validate_valid(connector):
    ev = RawEvidence(
        source_type=EvidenceSourceType.GITHUB_CODE,
        source_ref="ref",
        raw_data={"content": "foo", "path": "main.tf", "sha": "abc", "size_bytes": 100},
        collected_at=datetime.now(timezone.utc)
    )
    assert connector.validate(ev) is True

def test_validate_invalid_type(connector):
    ev = RawEvidence(
        source_type=EvidenceSourceType.GITHUB_ACTIONS,
        source_ref="ref",
        raw_data={"content": "foo", "path": "main.tf", "sha": "abc"},
        collected_at=datetime.now(timezone.utc)
    )
    assert connector.validate(ev) is False

def test_validate_missing_fields(connector):
    ev = RawEvidence(
        source_type=EvidenceSourceType.GITHUB_CODE,
        source_ref="ref",
        raw_data={"path": "main.tf"}, # missing content and sha
        collected_at=datetime.now(timezone.utc)
    )
    assert connector.validate(ev) is False

def test_validate_size_limit(connector):
    ev = RawEvidence(
        source_type=EvidenceSourceType.GITHUB_CODE,
        source_ref="ref",
        raw_data={"content": "foo", "path": "main.tf", "sha": "abc", "size_bytes": 1024 * 1024 + 1},
        collected_at=datetime.now(timezone.utc)
    )
    assert connector.validate(ev) is False

def test_normalize(connector):
    ev = RawEvidence(
        source_type=EvidenceSourceType.GITHUB_CODE,
        source_ref="https://github.com/ref",
        raw_data={"content": "test string", "path": "main.tf", "sha": "abc", "size_bytes": 11, "filename": "main.tf"},
        collected_at=datetime.now(timezone.utc)
    )
    norm = connector.normalize(ev)
    assert norm.source_type == EvidenceSourceType.GITHUB_CODE
    assert norm.source_ref == "https://github.com/ref"
    assert norm.content_json["path"] == "main.tf"
    assert norm.content_json["content"] == "test string"
    assert norm.sha256_hash is not None
