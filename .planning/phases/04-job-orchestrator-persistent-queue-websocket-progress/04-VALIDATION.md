---
phase: 4
slug: job-orchestrator-persistent-queue-websocket-progress
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-22
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `04-RESEARCH.md` § Validation Architecture + § Security Domain.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio (existing — confirm in Wave 0) |
| **Config file** | pyproject.toml / pytest.ini (confirm) |
| **Quick run command** | `pytest tests/test_orchestrator.py tests/test_event_bus.py tests/test_ws.py tests/test_idempotency.py tests/test_cancel.py -x` |
| **Full suite command** | `pytest -x` |
| **Estimated runtime** | ~30 seconds (mocked STTAdapter, no real GPU/model) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_orchestrator.py tests/test_event_bus.py tests/test_ws.py tests/test_idempotency.py tests/test_cancel.py -x`
- **After every plan wave:** Run `pytest -x`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | JOB-02 / SC-1 | — | N/A | unit | `pytest tests/test_orchestrator.py::test_state_machine -x` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | JOB-02 / SC-2 | — | N/A | integration | `pytest tests/test_orchestrator.py::test_restart_rejoin -x` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | D-03 | T-04-05 | boot sweep marks active-stage jobs `failed` preserving source name; runs after reconcile_all, before worker | integration | `pytest tests/test_orchestrator.py::test_boot_interrupted_sweep -x` | ❌ W0 | ⬜ pending |
| 04-02-02 | 02 | 1 | D-10 | — | worker=1 serial — no two jobs transcribe concurrently | unit | `pytest tests/test_orchestrator.py::test_serial_no_concurrency -x` | ❌ W0 | ⬜ pending |
| 04-02-03 | 02 | 1 | JOB-05 / SC-4 | T-04-04 | cancel: queued=instant DB-first+rmtree, running=cooperative stop-after-chunk+discard partial, terminal=no-op returning current row | unit | `pytest tests/test_cancel.py -x` | ❌ W0 | ⬜ pending |
| 04-02-04 | 02 | 1 | D-11 | T-04-stale | stale-sweep watchdog marks stale after 10-min; status-aware (skip done/failed/cancelled) | unit | `pytest tests/test_orchestrator.py::test_watchdog_stale -x` | ❌ W0 | ⬜ pending |
| 04-03-01 | 03 | 3 | JOB-06 / SC-3 | T-04-02 | WS endpoint broadcasts stage/percent/ETA; snapshot-on-connect then live; cap subscribers per job (DoS) | integration | `pytest tests/test_ws.py::test_progress_events -x` | ❌ W0 | ⬜ pending |
| 04-03-02 | 03 | 3 | SC-5 (no JOB-XX) | T-04-03 | POST /jobs same Idempotency-Key → same job_id + 200; UNIQUE(key) + IntegrityError catch for concurrent dup race | unit | `pytest tests/test_idempotency.py::test_dup_key_returns_existing -x` | ❌ W0 | ⬜ pending |
| 04-03-03 | 03 | 3 | D-08 | T-04-bus | event bus pub/sub; Queue maxsize=32 drop-oldest backpressure (no memory blowup) | unit | `pytest tests/test_event_bus.py -x` | ❌ W0 | ⬜ pending |
| 04-03-04 | 03 | 3 | SC-5 (no JOB-XX) | T-04-01 | Idempotency-Key header validation: cap length (~128), charset `^[A-Za-z0-9_-]{1,128}$`, reject before DB | unit | `pytest tests/test_idempotency.py::test_key_validation -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Wave 0 (W0) = test file must be stubbed before execution so the sampling loop has a target.*

---

## Wave 0 Requirements

- [ ] `tests/test_orchestrator.py` — covers JOB-02/SC-1/SC-2, D-03 (boot sweep), D-10 (serial), D-11 (watchdog)
- [ ] `tests/test_event_bus.py` — covers pub/sub per-job, backpressure drop-oldest (Queue maxsize=32)
- [ ] `tests/test_ws.py` — covers SC-3: snapshot-on-connect + live events via `starlette.testclient.TestClient.websocket_connect`
- [ ] `tests/test_idempotency.py` — covers JOB-06/SC-5: dup key → existing job_id + 200, concurrent race (IntegrityError), header validation
- [ ] `tests/test_cancel.py` — covers JOB-05/SC-4: queued (instant) / running (cooperative stop after current chunk, discard partial) / terminal (no-op)
- [ ] `tests/conftest.py` — fake `STTAdapter` fixture (sync, yields chunks, calls `progress_cb` per chunk via `call_soon_threadsafe`, honors `threading.Event` cancel_flag), `tmp_data_dir` SQLite queue, TestClient with lifespan; **`settings.run_worker` flag** so tests can disable the auto-started worker and drive it manually
- [ ] Confirm `pytest-asyncio` + `starlette` TestClient available — add to dev deps if missing
- [ ] Confirm `httpx` CANNOT do WebSockets — all WS tests go through Starlette TestClient (not httpx AsyncClient)

*Existing infra (tmp_data_dir, app_under_test, httpx AsyncClient, mocked-seams) covers HTTP-side tests; WS + worker-driving fixtures are new in Wave 0.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| None | — | — | — |

*All phase behaviors have automated verification (mocked STTAdapter substitutes for real GPU/model).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (5 new test files + conftest fixtures)
- [ ] No watch-mode flags (use `-x` fail-fast, not `--ff`/watch)
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending