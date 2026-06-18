"""Contract guard for 02-03-SPIKE.md.

This test exists to ensure the spike deliverable is present and well-formed
before Phase 3 plans can be written. The spike is the empirical evidence that
the desktop ROCm path works (or that the fallback is documented per D-07); the
test asserts the file's structure, not its content correctness.

If this test fails, the spike has not been written yet OR the verdict heading
is missing OR one of the required sections is missing. Fix: write the spike.
"""
from pathlib import Path

SPIKE_PATH = (
    Path(__file__).parent.parent
    / ".planning"
    / "phases"
    / "02-gpu-backend-detection-model-manager"
    / "02-03-SPIKE.md"
)

REQUIRED_SECTIONS = [
    "## 1. Target environment",
    "## 2. What worked",
    "## 3. Fallback decision",
    "## 4. Pitfalls hit",
    "## 5. What Phase 3 must do",
]

VALID_VERDICTS = (
    "VERDICT: ROCM_VIA_THEROCK_WORKS",
    "VERDICT: ROCM_FALLBACK_TO_CPU",
)


def test_spike_file_exists() -> None:
    assert SPIKE_PATH.exists(), f"Spike file not found: {SPIKE_PATH}"


def test_spike_file_has_required_sections() -> None:
    body = SPIKE_PATH.read_text(encoding="utf-8")
    for section in REQUIRED_SECTIONS:
        assert section in body, f"Missing required section: {section}"


def test_spike_file_has_valid_verdict() -> None:
    body = SPIKE_PATH.read_text(encoding="utf-8")
    assert any(verdict in body for verdict in VALID_VERDICTS), (
        f"Missing or invalid verdict. Must be one of: {VALID_VERDICTS}"
    )


def test_phase3_section_has_at_least_one_requirement() -> None:
    body = SPIKE_PATH.read_text(encoding="utf-8")
    section_start = body.index("## 5. What Phase 3 must do")
    section_body = body[section_start:]
    next_section_match = section_body.find("\n## ", 1)
    if next_section_match > 0:
        section_body = section_body[:next_section_match]
    assert "must" in section_body.lower(), (
        "Phase 3 section must contain at least one 'must' requirement"
    )