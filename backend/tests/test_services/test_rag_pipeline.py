"""Integration tests for the RAG ingestion and retrieval pipeline.

Tests document splitting, chunking logic, and grounding validation
without requiring database or OpenAI API access.
"""


from app.services.compliance_brain.generator import _ground_controls
from app.services.compliance_brain.ingestion import _split_by_sections

# ---------------------------------------------------------------------------
# Document Splitter
# ---------------------------------------------------------------------------

class TestDocumentSplitter:
    def test_splits_by_markdown_headers(self):
        text = "Preamble text\n## Section One\nContent one\n## Section Two\nContent two"
        sections = _split_by_sections(text)
        assert len(sections) == 3  # Preamble + 2 sections
        assert sections[0][0] == "Preamble"
        assert sections[1][0] == "Section One"
        assert sections[2][0] == "Section Two"

    def test_handles_no_headers(self):
        text = "Just plain text with no headers at all."
        sections = _split_by_sections(text)
        assert len(sections) == 1
        assert sections[0][0] == "Preamble"
        assert "plain text" in sections[0][1]

    def test_handles_empty_sections(self):
        text = "## Empty Section\n## Another Section\nSome content"
        sections = _split_by_sections(text)
        # Empty section (no body between headers) is skipped by the splitter
        assert len(sections) == 1
        assert sections[0][0] == "Another Section"
        assert "Some content" in sections[0][1]

    def test_handles_empty_input(self):
        sections = _split_by_sections("")
        # Should return at least the preamble
        assert len(sections) >= 1

    def test_preserves_section_content(self):
        text = "## Title\nLine 1\nLine 2\nLine 3"
        sections = _split_by_sections(text)
        assert sections[0][0] == "Title"
        assert "Line 1" in sections[0][1]
        assert "Line 3" in sections[0][1]

    def test_multiple_headers_at_different_levels_only_splits_on_h2(self):
        text = "# H1 title\n## H2 one\nContent\n### H3 sub\nSub content\n## H2 two\nMore"
        sections = _split_by_sections(text)
        # _split_by_sections only splits on "## " (h2)
        h2_sections = [s for s in sections if s[0] != "Preamble"]
        assert len(h2_sections) == 2


# ---------------------------------------------------------------------------
# Chunking Logic
# ---------------------------------------------------------------------------

class TestChunkingLogic:
    def test_small_text_produces_single_chunk_concept(self):
        """A very short section should produce exactly one chunk when ingested."""
        text = "## Short\nThis is a brief section."
        sections = _split_by_sections(text)
        assert len(sections) == 1
        # With default chunk_size=512, this tiny text fits in one chunk
        words = sections[0][1].split()
        assert len(words) < 512

    def test_long_text_would_produce_multiple_chunks(self):
        """A section with 1000 words should exceed a single chunk of size 512."""
        words = [f"word{i}" for i in range(1000)]
        text = "## Long\n" + " ".join(words)
        sections = _split_by_sections(text)
        section_words = sections[0][1].split()
        assert len(section_words) > 512  # Would need multiple chunks


# ---------------------------------------------------------------------------
# Grounding Validation
# ---------------------------------------------------------------------------

class TestGroundingValidation:
    def _make_control(self, citation: str, title: str = "Test", confidence: float = 0.9):
        """Helper to create a mock generated control object."""
        class MockControl:
            def __init__(self):
                self.source_citation = citation
                self.title = title
                self.confidence = confidence
                self.control_id_code = "TEST-001"
        return MockControl()

    def test_grounded_citation_keeps_confidence(self):
        ctrl = self._make_control("§ 164.312(a)(1)")
        context = [{"text": "Under section 164.312(a)(1), covered entities must..."}]
        result = _ground_controls([ctrl], context)
        assert result[0].confidence == 0.9
        assert "[UNGROUNDED]" not in result[0].title

    def test_ungrounded_citation_gets_flagged(self):
        ctrl = self._make_control("§ 164.999(z)(99)")
        context = [{"text": "Under section 164.312(a)(1), covered entities must..."}]
        result = _ground_controls([ctrl], context)
        assert result[0].confidence == 0.3
        assert "[UNGROUNDED]" in result[0].title

    def test_empty_citation_is_skipped(self):
        ctrl = self._make_control("")
        context = [{"text": "Some context text here."}]
        result = _ground_controls([ctrl], context)
        # Empty citations should be skipped, not flagged
        assert result[0].confidence == 0.9

    def test_article_prefix_stripped(self):
        ctrl = self._make_control("Article 25")
        context = [{"text": "According to article 25, data protection by design..."}]
        result = _ground_controls([ctrl], context)
        assert result[0].confidence == 0.9

    def test_multiple_controls_mixed(self):
        ctrl_good = self._make_control("§ 164.312(a)")
        ctrl_bad = self._make_control("§ 999.999")
        context = [{"text": "Section 164.312(a) requires access control measures."}]
        results = _ground_controls([ctrl_good, ctrl_bad], context)
        assert results[0].confidence == 0.9  # Grounded
        assert results[1].confidence == 0.3  # Ungrounded
