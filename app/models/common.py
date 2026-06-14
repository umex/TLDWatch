from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StageTimestamps(BaseModel):
    """Wall-clock timestamps for each pipeline stage that a job can reach.

    All values are ISO 8601 strings produced by :func:`app.util.time.utcnow_iso`
    (always terminating in ``+00:00``). A ``None`` value means the stage has
    not been reached yet.
    """

    model_config = ConfigDict(extra="forbid")

    queued: str
    ingested: str | None = None
    transcribed: str | None = None
    diarized: str | None = None
    summarized: str | None = None
    done: str | None = None
