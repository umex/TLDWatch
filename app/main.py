"""FastAPI app entry point.

The :func:`lifespan` context manager is the single boot-time path
for the service. It:

1. Resolves the STABLE bootstrap settings path via
   :func:`app.storage.fs.bootstrap_settings_path` (the file lives
   next to the backend executable and is the SAME absolute path for
   every run - patching ``data_dir`` does not move it).
2. On first boot, atomically writes an initial ``data/settings.json``
   whose ``data_dir`` value is the absolute path of the bootstrap
   data directory (this is the fix for the circular data_dir
   bootstrap, Codex HIGH).
3. Loads and validates the file via the :class:`Settings` Pydantic
   model (D-14, D-15).
4. Creates the data directory, builds the SQLAlchemy async engine
   with a per-connection WAL listener, applies any pending
   migrations, and fails to start on any migration error (D-08).
5. Installs the session factory + settings on the request scope
   via :func:`app.api.dependencies.configure`.
6. On shutdown, disposes the engine so SQLite releases the file.

The FastAPI app itself is built outside the lifespan so routers
register at import time (Codex MEDIUM). Middleware is added before
the lifespan runs.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.dependencies import configure
from app.api.routes_health import router as health_router
from app.api.routes_jobs import router as jobs_router
from app.api.routes_settings import router as settings_router
from app.models.settings import Settings
from app.models.summary import Summary
from app.models.transcript import Transcript, TranscriptSegment
from app.settings import service as settings_service
from app.storage.atomic import atomic_write_json
from app.storage.db import apply_migrations, make_engine, make_sessionmaker
from app.storage.fs import bootstrap_settings_path

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_path = bootstrap_settings_path()
    bootstrap_dir = bootstrap_path.parent

    if not bootstrap_path.exists():
        # First boot. The default ``data_dir`` is the ABSOLUTE path of
        # the bootstrap directory so the data dir is decoupled from
        # the process working directory (Codex HIGH fix).
        default_data_dir = str(bootstrap_dir.resolve())
        bootstrap_dir.mkdir(parents=True, exist_ok=True)
        await atomic_write_json(
            bootstrap_path, Settings(data_dir=default_data_dir).model_dump()
        )
        logger.info("Wrote initial settings file at %s", bootstrap_path)

    settings = settings_service.load_settings_from_disk(bootstrap_path)

    # Surface a manual override at boot (does not block startup).
    try:
        default_data_dir = str(bootstrap_dir.resolve())
        if settings.data_dir != default_data_dir:
            logger.warning(
                "settings.data_dir=%s differs from default=%s - manual override",
                settings.data_dir,
                default_data_dir,
            )
    except Exception:  # pragma: no cover - defensive logging only
        logger.exception("Could not compute default data_dir for override check")

    # Ensure the configured data directory exists.
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

    engine = make_engine(settings)
    await apply_migrations(engine)

    session_factory = make_sessionmaker(engine)
    configure(session_factory, settings)

    # Startup reconciliation: walk every per-job folder and UPDATE
    # any DB row that has drifted from its manifest (Codex HIGH #1
    # follow-up). A reconcile failure means the DB and FS are in a
    # state the app cannot safely serve, so re-raise and refuse to
    # start (D-08 posture).
    from app.jobs import reconcile as reconcile_module

    try:
        reconcile_summary = await reconcile_module.reconcile_all(
            settings, session_factory
        )
        logger.info(
            "reconcile summary: scanned=%d updated=%d missing_manifests=%d",
            reconcile_summary.get("scanned", 0),
            reconcile_summary.get("updated", 0),
            len(reconcile_summary.get("missing_manifests", [])),
        )
    except Exception:
        logger.exception("startup reconciliation failed; refusing to start")
        raise

    # Announce ready to anyone watching stdout (uvicorn re-prints
    # access logs, but this is the one-line ready banner the
    # acceptance criteria check for).
    print(f"TranscriptionAndNotes backend ready: data_dir={settings.data_dir}")

    try:
        yield
    finally:
        await engine.dispose()
        # Reset module-level references so a second lifespan (e.g. in
        # tests) starts from a known state.
        configure(None, None)  # type: ignore[arg-type]


app = FastAPI(title="TranscriptionAndNotes", version="0.1.0", lifespan=lifespan)

# Storage models that the typed OpenAPI surface must expose to
# downstream consumers (openapi-typescript in Phase 5) even before
# their /transcripts and /summaries routes are added. We patch
# ``app.openapi`` to inject their JSON schemas into
# ``components.schemas``; without this, Pydantic only registers
# models that are reachable from a route handler.
#
# See Plan 01-02 success criteria: TranscriptSegment, Summary,
# Settings, UpdateSettingsRequest must all appear in
# components.schemas.
#
# Plan 01-03 adds the new internal-mutator request/response models
# (StageUpdateRequest, StaleCheckResponse, ManifestPatch) so the
# OpenAPI schema carries the full per-job control surface.
from app.models.job import ManifestPatch, StageUpdateRequest, StaleCheckResponse

_EXTRA_OPENAPI_MODELS = [
    TranscriptSegment,
    Transcript,
    Summary,
    ManifestPatch,
    StageUpdateRequest,
    StaleCheckResponse,
]


def _custom_openapi():  # noqa: ANN202
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    for model in _EXTRA_OPENAPI_MODELS:
        key = model.__name__
        if key in schemas:
            continue
        # ``model_json_schema`` is the Pydantic v2 way to get the
        # JSON-schema representation. ``ref_template`` is left at
        # the FastAPI default (``#/components/schemas/{model}``).
        schemas[key] = model.model_json_schema(ref_template="#/components/schemas/{model}")
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi  # type: ignore[assignment]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
    allow_credentials=False,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "0.0.0.0"],
)

app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(settings_router)
