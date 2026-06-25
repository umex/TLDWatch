#!/usr/bin/env bash
# openapi-typescript codegen: generates web/src/api/types.ts from the
# FastAPI OpenAPI schema served at http://localhost:8000/openapi.json
# (D-12; Phase 1/2 already patched the schema to expose JobResponse,
# Transcript, TranscriptSegment, plus the 'uploading' status added by 05-01).
#
# Usage:
#   bash web/scripts/gen-types.sh        # from repo root
#   npm --prefix web run gen-types       # via package.json script
#
# Requires the back-end to be running on localhost:8000. If it is not up,
# start it first (e.g. `python -m uvicorn app.main:app --port 8000`),
# then re-run this script.
set -euo pipefail

SCHEMA_URL="${OPENAPI_URL:-http://localhost:8000/openapi.json}"
OUT="web/src/api/types.ts"

# Run from the web/ directory regardless of where the script is invoked from.
WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_PATH="${WEB_DIR}/src/api/types.ts"

echo "[gen-types] fetching ${SCHEMA_URL} -> ${OUT_PATH}"
cd "${WEB_DIR}"
npx --no-install openapi-typescript "${SCHEMA_URL}" -o "${OUT_PATH}"
echo "[gen-types] done."