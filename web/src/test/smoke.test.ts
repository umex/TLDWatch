// Smoke test: proves the Vitest jsdom infra + setup.ts mocks load and
// that idempotencyKey (D-11 / Open Questions #3) produces a stable
// 32-hex-char key. The full FE test suite (jobs.test.ts, DetailPage.test.tsx,
// useScrollSpy.test.ts) lands in 05-02b / 05-03 per VALIDATION.md.
import { describe, expect, it } from "vitest"

import { idempotencyKey } from "../api/client"

describe("vitest infra smoke", () => {
  it("exposes the mocked IntersectionObserver", () => {
    expect(typeof IntersectionObserver).toBe("function")
    const io = new IntersectionObserver(() => {})
    io.observe(document.createElement("div"))
    io.disconnect()
    expect(io.takeRecords()).toEqual([])
  })

  it("exposes a mocked XMLHttpRequest with an upload object", () => {
    expect(typeof XMLHttpRequest).toBe("function")
    const xhr = new XMLHttpRequest()
    expect(xhr.upload).toBeDefined()
    expect(typeof xhr.upload.onprogress).toBe("object")
    xhr.open("POST", "/jobs/upload")
    xhr.setRequestHeader("Idempotency-Key", "abc")
    expect((xhr as any).__getUrl()).toBe("/jobs/upload")
    expect((xhr as any).__getHeaders()["Idempotency-Key"]).toBe("abc")
  })

  it("exposes a mocked WebSocket constructor", () => {
    expect(typeof WebSocket).toBe("function")
    const ws = new WebSocket("ws://localhost:8000/ws/jobs/x/events")
    expect(ws.url).toContain("/ws/jobs/x/events")
    expect(typeof ws.close).toBe("function")
  })
})

describe("idempotencyKey (D-11 / Open Questions #3)", () => {
  it("returns a 32-char hex string", async () => {
    const key = await idempotencyKey("video.mp4", 1024, 1700000000000)
    expect(key).toMatch(/^[0-9a-f]{32}$/)
    expect(key.length).toBe(32)
  })

  it("is deterministic for the same (filename, size, lastModified)", async () => {
    const a = await idempotencyKey("video.mp4", 1024, 1700000000000)
    const b = await idempotencyKey("video.mp4", 1024, 1700000000000)
    expect(a).toBe(b)
  })

  it("differs when the inputs differ", async () => {
    const a = await idempotencyKey("video.mp4", 1024, 1700000000000)
    const b = await idempotencyKey("video.mp4", 1025, 1700000000000)
    expect(a).not.toBe(b)
  })
})