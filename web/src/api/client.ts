// API client: fetch wrapper + idempotency key derivation (D-11, D-07,
// UI-SPEC §1, RESEARCH Open Questions #3 RESOLVED).
//
// The browser upload (05-02b useUpload, XHR-primary) consumes
// `idempotencyKey` to set the `Idempotency-Key` header so a re-drop
// mid-upload collapses to the existing job (Phase 4 D-07). The key is
// `[filename]-[size]-[lastmodified]` hashed via crypto.subtle SHA-256
// and truncated to 32 hex chars (stays well under the 128-char
// [A-Za-z0-9_-] back-end cap -- T-05-10 mitigation).

/** Base URL of the FastAPI back-end. The Vite dev server proxies / API
 *  calls here in production builds; in dev the FE talks to it directly
 *  (CORS is already configured for localhost:5173 in app/main.py). */
export const API_BASE = "http://localhost:8000";

/** Shape of a parsed error body from a non-2xx response. */
export interface ApiErrorBody {
  detail?: string | { msg: string; loc: (string | number)[] }[];
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | undefined;
  constructor(message: string, status: number, body?: ApiErrorBody) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

/**
 * Fetch wrapper that prefixes the back-end base URL, sets JSON headers,
 * and throws an {@link ApiError} on a non-2xx response carrying the
 * parsed JSON error body (if any). Returns the parsed JSON body on
 * success.
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  })
  const text = await res.text()
  const body: unknown = text ? safeJsonParse(text) : null
  if (!res.ok) {
    throw new ApiError(
      `API ${path} failed: ${res.status} ${res.statusText}`,
      res.status,
      body as ApiErrorBody | undefined,
    )
  }
  return body as T
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

/**
 * Derive the `Idempotency-Key` header value for a file upload
 * (UI-SPEC §1 + RESEARCH Open Questions #3 RESOLVED).
 *
 * Hashes `[filename]-[size]-[lastmodified]` via crypto.subtle SHA-256
 * and truncates the hex digest to 32 chars. The result is a stable
 * `[0-9a-f]{32}` string — well within the back-end
 * `validate_idempotency_key` `[A-Za-z0-9_-]{1,128}` envelope (T-05-10),
 * and deterministic so a re-drop of the same file collapses to the
 * existing in-progress job (Phase 4 D-07).
 */
export async function idempotencyKey(
  filename: string,
  size: number,
  lastModified: number,
): Promise<string> {
  const material = `${filename}-${size}-${lastModified}`
  const data = new TextEncoder().encode(material)
  // crypto.subtle.digest is available in all modern browsers and in
  // the vitest jsdom setup (mocked -- see src/test/setup.ts).
  const digest = await crypto.subtle.digest("SHA-256", data)
  const hex = bytesToHex(new Uint8Array(digest))
  // 32 hex chars = 128 bits of entropy; comfortably under the 128-char cap.
  return hex.slice(0, 32)
}

function bytesToHex(bytes: Uint8Array): string {
  let out = ""
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i].toString(16).padStart(2, "0")
  }
  return out
}