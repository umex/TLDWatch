// Vitest jsdom setup (VALIDATION.md Wave 0).
// Mocks the browser APIs the FE code + tests depend on:
//   - IntersectionObserver (scroll-spy, UI-03, used by 05-03 useScrollSpy)
//   - WebSocket (useJobEvents native WS hook, D-08)
//   - fetch (TanStack Query hooks in jobs.ts)
//   - XMLHttpRequest + xhr.upload (05-02b useUpload XHR-primary path, D-02)
//   - crypto.subtle (idempotencyKey SHA-256, D-11/Open Questions #3)
//
// `__trigger` / `__progress` / `__respond` helpers are exposed so tests can
// drive observers / XHR callbacks deterministically without relying on real
// async timing. Mock classes are intentionally loose (no `implements`) and
// cast at the global assignment to avoid DOM interface-conformance noise.

import { afterEach, vi } from 'vitest'
import '@testing-library/react'

// --- IntersectionObserver mock -------------------------------------------------
type IOCallback = (entries: IntersectionObserverEntry[]) => void

class MockIntersectionObserver {
  static instances: MockIntersectionObserver[] = []
  callback: IOCallback
  elements: Set<Element> = new Set()
  readonly root: Element | Document | null = null
  readonly rootMargin: string = '0px'
  readonly thresholds: ReadonlyArray<number> = [0]
  scrollMargin: string = '0px'
  constructor(cb: IOCallback, _options?: IntersectionObserverInit) {
    this.callback = cb
    MockIntersectionObserver.instances.push(this)
  }
  observe(target: Element): void {
    this.elements.add(target)
  }
  unobserve(target: Element): void {
    this.elements.delete(target)
  }
  disconnect(): void {
    this.elements.clear()
  }
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
  // Test helper: fire an intersection event for the observed targets.
  __trigger(entries: Array<{ target: Element; isIntersecting: boolean }>): void {
    const mapped = entries.map(
      (e) =>
        ({
          target: e.target,
          isIntersecting: e.isIntersecting,
          intersectionRatio: e.isIntersecting ? 1 : 0,
          boundingClientRect: { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 } as DOMRectReadOnly,
          intersectionRect: { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 } as DOMRectReadOnly,
          rootBounds: null,
          time: performance.now(),
        }) as IntersectionObserverEntry,
    )
    this.callback(mapped)
  }
}

globalThis.IntersectionObserver =
  MockIntersectionObserver as unknown as typeof IntersectionObserver

// --- WebSocket mock -----------------------------------------------------------
class MockWebSocket {
  static instances: MockWebSocket[] = []
  url: string
  readyState: 0 | 1 | 2 | 3 = 0
  onmessage: ((ev: MessageEvent) => void) | null = null
  onopen: ((ev: Event) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  onclose: ((ev: CloseEvent) => void) | null = null
  bufferedAmount: number = 0
  extensions: string = ''
  protocol: string = ''
  binaryType: BinaryType = 'blob'
  constructor(url: string | URL, _protocols?: string | string[]) {
    this.url = String(url)
    MockWebSocket.instances.push(this)
  }
  send(_data: string | ArrayBuffer | Blob | ArrayBufferView): void {
    // no-op for tests
  }
  close(_code?: number, _reason?: string): void {
    this.readyState = 3
  }
  addEventListener(): void {}
  removeEventListener(): void {}
  dispatchEvent(): boolean {
    return true
  }
  // Test helpers
  __open(): void {
    this.readyState = 1
    if (this.onopen) this.onopen(new Event('open'))
  }
  __message(data: unknown): void {
    if (this.onmessage)
      this.onmessage({ data: typeof data === 'string' ? data : JSON.stringify(data) } as MessageEvent)
  }
  __error(): void {
    if (this.onerror) this.onerror(new Event('error'))
  }
}

globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket

// --- fetch mock ---------------------------------------------------------------
globalThis.fetch = vi.fn() as unknown as typeof fetch

// --- XMLHttpRequest mock (XHR-primary upload path, D-02) ----------------------
class MockXMLHttpRequest {
  static instances: MockXMLHttpRequest[] = []
  onreadystatechange: ((ev: Event) => void) | null = null
  onabort: ((ev: ProgressEvent) => void) | null = null
  onerror: ((ev: ProgressEvent) => void) | null = null
  onload: ((ev: ProgressEvent) => void) | null = null
  onloadstart: ((ev: ProgressEvent) => void) | null = null
  onloadend: ((ev: ProgressEvent) => void) | null = null
  onprogress: ((ev: ProgressEvent) => void) | null = null
  ontimeout: ((ev: ProgressEvent) => void) | null = null
  upload: {
    onprogress: ((ev: ProgressEvent) => void) | null
    onabort: ((ev: ProgressEvent) => void) | null
    onerror: ((ev: ProgressEvent) => void) | null
    onload: ((ev: ProgressEvent) => void) | null
    onloadend: ((ev: ProgressEvent) => void) | null
    onloadstart: ((ev: ProgressEvent) => void) | null
    ontimeout: ((ev: ProgressEvent) => void) | null
    addEventListener: () => void
    removeEventListener: () => void
    dispatchEvent: () => boolean
  }
  readyState: number = 0
  response: unknown = ''
  responseText: string = ''
  responseType: XMLHttpRequestResponseType = ''
  responseURL: string = ''
  status: number = 0
  statusText: string = ''
  timeout: number = 0
  withCredentials: boolean = false
  private _headers: Record<string, string> = {}
  private _method: string = ''
  private _url: string = ''

  constructor() {
    this.upload = {
      onprogress: null,
      onabort: null,
      onerror: null,
      onload: null,
      onloadend: null,
      onloadstart: null,
      ontimeout: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => true,
    }
  }
  open(method: string, url: string | URL): void {
    this._method = method
    this._url = String(url)
    this.readyState = 1
  }
  setRequestHeader(name: string, value: string): void {
    this._headers[name] = value
  }
  getResponseHeader(_name: string): string | null {
    return null
  }
  getAllResponseHeaders(): string {
    return ''
  }
  send(_body?: Document | XMLHttpRequestBodyInit | null): void {
    MockXMLHttpRequest.instances.push(this)
    this.readyState = 2
  }
  abort(): void {
    this.readyState = 4
  }
  overrideMimeType(_mime: string): void {}
  addEventListener(): void {}
  removeEventListener(): void {}
  dispatchEvent(): boolean {
    return true
  }
  // Test helpers
  __getHeaders(): Record<string, string> {
    return this._headers
  }
  __getMethod(): string {
    return this._method
  }
  __getUrl(): string {
    return this._url
  }
  __progress(loaded: number, total: number, lengthComputable = true): void {
    const ev = { lengthComputable, loaded, total } as ProgressEvent
    const fn = this.upload.onprogress
    if (fn) fn(ev)
  }
  __respond(status: number, body: unknown): void {
    this.status = status
    this.readyState = 4
    this.response = body
    this.responseText = typeof body === 'string' ? body : JSON.stringify(body)
    if (this.onload) this.onload({ lengthComputable: true, loaded: 0, total: 0 } as ProgressEvent)
  }
  __fail(): void {
    this.readyState = 4
    if (this.onerror) this.onerror({ lengthComputable: false, loaded: 0, total: 0 } as ProgressEvent)
  }
}

globalThis.XMLHttpRequest =
  MockXMLHttpRequest as unknown as typeof XMLHttpRequest

// --- crypto.subtle mock (idempotencyKey SHA-256) ------------------------------
// A deterministic fake SHA-256: returns a 32-byte digest derived from the
// input bytes. Good enough for tests that only need a stable 32-hex-char
// string; the real crypto.subtle is used in the browser at runtime.
async function fakeDigest(
  _alg: string,
  data: ArrayBuffer | ArrayBufferView,
): Promise<ArrayBuffer> {
  const view = 'buffer' in data ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength) : new Uint8Array(data as ArrayBuffer)
  const out = new Uint8Array(32)
  for (let i = 0; i < view.length; i++) {
    out[i % 32] = (out[i % 32] ^ view[i]) & 0xff
  }
  return out.buffer
}

if (!globalThis.crypto) {
  ;(globalThis as unknown as { crypto: Crypto }).crypto = {} as Crypto
}
const cryptoObj = globalThis.crypto as unknown as {
  subtle: SubtleCrypto
  getRandomValues: <T extends ArrayBufferView>(arr: T) => T
}
if (!cryptoObj.subtle) {
  cryptoObj.subtle = {
    digest: fakeDigest as SubtleCrypto['digest'],
    encrypt: vi.fn(),
    decrypt: vi.fn(),
    sign: vi.fn(),
    verify: vi.fn(),
    generateKey: vi.fn(),
    deriveKey: vi.fn(),
    deriveBits: vi.fn(),
    importKey: vi.fn(),
    exportKey: vi.fn(),
    wrapKey: vi.fn(),
    unwrapKey: vi.fn(),
  } as SubtleCrypto
}
if (!cryptoObj.getRandomValues) {
  cryptoObj.getRandomValues = <T extends ArrayBufferView>(arr: T): T => arr
}

// Suppress the default TextEncoder if absent (jsdom may lack it).
if (typeof globalThis.TextEncoder === 'undefined') {
  ;(globalThis as unknown as { TextEncoder: typeof TextEncoder }).TextEncoder =
    class {
      encode(input = ''): Uint8Array {
        return new Uint8Array(input.split('').map((c) => c.charCodeAt(0) & 0xff))
      }
    } as unknown as typeof TextEncoder
}

// --- Reset mocks + instance trackers between tests ----------------------------
afterEach(() => {
  vi.restoreAllMocks()
  MockIntersectionObserver.instances.length = 0
  MockWebSocket.instances.length = 0
  MockXMLHttpRequest.instances.length = 0
})

// Re-expose mock classes for tests via a typed global.
;(globalThis as unknown as {
  __MOCKS__: {
    IntersectionObserver: typeof MockIntersectionObserver
    WebSocket: typeof MockWebSocket
    XMLHttpRequest: typeof MockXMLHttpRequest
  }
}).__MOCKS__ = {
  IntersectionObserver: MockIntersectionObserver,
  WebSocket: MockWebSocket,
  XMLHttpRequest: MockXMLHttpRequest,
}

export {}