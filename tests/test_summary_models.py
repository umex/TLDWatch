"""Round-trip and validation tests for the summary Pydantic models.

The ``SummaryKind`` Literal is the four-template discriminator
(``meeting``, ``investment``, ``concept``, ``quick_recap``); an
unknown kind is rejected at the model boundary.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.summary import Summary, SummaryKind


@pytest.mark.parametrize("kind", ["meeting", "investment", "concept", "quick_recap"])
def test_roundtrip_meeting(kind: str) -> None:
    s = Summary(
        job_id="abc",
        kind=kind,  # type: ignore[arg-type]
        created_at="2026-06-11T00:00:00+00:00",
        sections={"a": "b"},
        model="qwen-7b",
    )
    assert s.kind == kind
    restored = Summary.model_validate_json(s.model_dump_json())
    assert restored.kind == kind
    assert restored.sections == {"a": "b"}
    assert restored.model == "qwen-7b"


def test_summary_unknown_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        Summary(
            job_id="abc",
            kind="not-a-kind",  # type: ignore[arg-type]
            created_at="2026-06-11T00:00:00+00:00",
        )


def test_summary_kind_literal_args() -> None:
    assert SummaryKind.__args__ == (
        "meeting",
        "investment",
        "concept",
        "quick_recap",
    )


def test_summary_default_sections_is_empty_dict() -> None:
    s = Summary(
        job_id="abc",
        kind="meeting",
        created_at="2026-06-11T00:00:00+00:00",
    )
    assert s.sections == {}
    assert s.model is None
    assert s.schema_version == 1
