"""Tests for the prompt grounding guard in generator.py."""

from __future__ import annotations

from app.services.compliance_brain.generator import GeneratedControl, _ground_controls


def _make_control(
    citation: str,
    title: str = "Test Control",
    confidence: float = 1.0,
) -> GeneratedControl:
    return GeneratedControl(
        control_id_code="HIPAA-TEST-001",
        title=title,
        description="A test control",
        source_citation=citation,
        source_text="Some source text",
        requirements=[],
        confidence=confidence,
    )


class TestGroundControls:
    def test_grounded_citation_keeps_confidence(self):
        """Citation that exists in context should not be modified."""
        controls = [_make_control("§ 164.312(a)(1)")]
        context_chunks = [{"text": "Under § 164.312(a)(1), access controls must be implemented."}]

        result = _ground_controls(controls, context_chunks)

        assert len(result) == 1
        assert result[0].confidence == 1.0
        assert not result[0].title.startswith("[UNGROUNDED]")

    def test_ungrounded_citation_gets_flagged(self):
        """Citation NOT in context should get confidence=0.3 and [UNGROUNDED] prefix."""
        controls = [_make_control("§ 164.308(a)(7)(ii)(A)")]
        context_chunks = [{"text": "This chunk only discusses § 164.312(a)(1)."}]

        result = _ground_controls(controls, context_chunks)

        assert len(result) == 1
        assert result[0].confidence == 0.3
        assert result[0].title.startswith("[UNGROUNDED]")

    def test_empty_citation_is_skipped(self):
        """Controls with empty citations should not be modified."""
        controls = [_make_control("", title="No Citation Control", confidence=0.8)]
        context_chunks = [{"text": "Some regulatory text."}]

        result = _ground_controls(controls, context_chunks)

        assert result[0].confidence == 0.8
        assert result[0].title == "No Citation Control"

    def test_article_prefix_stripped(self):
        """'Article' prefix should be stripped before matching."""
        controls = [_make_control("Article 25")]
        context_chunks = [{"text": "GDPR Article 25 requires data protection by design."}]

        result = _ground_controls(controls, context_chunks)

        assert result[0].confidence == 1.0
        assert not result[0].title.startswith("[UNGROUNDED]")

    def test_section_symbol_stripped(self):
        """'§' prefix should be stripped before matching."""
        controls = [_make_control("§ 164.312(e)(1)")]
        context_chunks = [{"text": "Transmission security per 164.312(e)(1) ..."}]

        result = _ground_controls(controls, context_chunks)

        assert result[0].confidence == 1.0

    def test_case_insensitive_matching(self):
        """Matching should be case-insensitive."""
        controls = [_make_control("HIPAA Section ABC")]
        context_chunks = [{"text": "According to hipaa section abc, organizations must..."}]

        result = _ground_controls(controls, context_chunks)

        assert result[0].confidence == 1.0

    def test_multiple_controls_mixed(self):
        """Mix of grounded and ungrounded controls."""
        controls = [
            _make_control("§ 164.312(a)(1)", title="Grounded"),
            _make_control("§ 999.999(z)(9)", title="Not Grounded"),
        ]
        context_chunks = [{"text": "Only contains 164.312(a)(1) references."}]

        result = _ground_controls(controls, context_chunks)

        assert result[0].confidence == 1.0
        assert result[0].title == "Grounded"
        assert result[1].confidence == 0.3
        assert result[1].title == "[UNGROUNDED] Not Grounded"

    def test_multiple_context_chunks(self):
        """Citation appearing in any chunk counts as grounded."""
        controls = [_make_control("§ 164.308(a)(6)")]
        context_chunks = [
            {"text": "First chunk about access controls."},
            {"text": "Second chunk referencing 164.308(a)(6) incident procedures."},
        ]

        result = _ground_controls(controls, context_chunks)

        assert result[0].confidence == 1.0
