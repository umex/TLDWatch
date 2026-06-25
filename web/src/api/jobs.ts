// TanStack Query hooks for the job history list, single-job detail,
// and transcript fetch (D-12, D-14; UI-SPEC §5; RESEARCH Pattern 3).
//
// All hooks consume the codegen'd OpenAPI types in types.ts -- no
// hand-written model interfaces, no `any` for job/transcript shapes
// (RESEARCH Anti-Patterns). The `invalidateJobs` helper is used by
// 05-02b's ActiveJobCard terminal transition + 05-03 to refetch the
// completed history list when a job reaches done/failed/cancelled.

import { useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query"
import type { QueryClient } from "@tanstack/react-query"

import { apiFetch, ApiError } from "./client"
import type { components } from "./types"

export type JobResponse = components["schemas"]["JobResponse"]
export type JobStatus = JobResponse["status"]
export type Transcript = components["schemas"]["Transcript"]
export type TranscriptSegment = components["schemas"]["TranscriptSegment"]

/** Sentinel returned by {@link useTranscript} when the job has no
 *  transcript yet (404 from `GET /jobs/{id}/transcript`). The detail
 *  view renders a "Transcribing..." state in this case (D-14). */
export const TRANSCRIBING = "transcribing" as const
export type TranscriptResult = Transcript | typeof TRANSCRIBING

/** Query key factory for the jobs + transcripts cache. */
export const jobsKeys = {
  all: ["jobs"] as const,
  list: (status?: JobStatus) => ["jobs", status ?? null] as const,
  detail: (id: string) => ["jobs", "detail", id] as const,
  transcript: (id: string) => ["transcripts", id] as const,
}

/** Helper to fetch the job list, optionally filtered by status. */
async function fetchJobs(status?: JobStatus): Promise<JobResponse[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ""
  return apiFetch<JobResponse[]>(`/jobs${qs}`)
}

/** Helper to fetch a single job by id. */
async function fetchJob(id: string): Promise<JobResponse> {
  return apiFetch<JobResponse>(`/jobs/${encodeURIComponent(id)}`)
}

/** Helper to fetch a job's transcript. Returns the {@link TRANSCRIBING}
 *  sentinel when the back-end reports 404 (transcript not ready yet). */
async function fetchTranscript(id: string): Promise<TranscriptResult> {
  try {
    return await apiFetch<Transcript>(`/jobs/${encodeURIComponent(id)}/transcript`)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return TRANSCRIBING
    throw err
  }
}

/**
 * List jobs, optionally filtered by status. Default (no filter) returns
 * all jobs newest-first (the `GET /jobs` default ordering).
 *
 * @param status optional status filter (e.g. "done" for the completed
 *   history list per D-05, or an active status for active cards).
 */
export function useJobs(status?: JobStatus) {
  return useQuery<JobResponse[]>({
    queryKey: jobsKeys.list(status),
    queryFn: () => fetchJobs(status),
    placeholderData: keepPreviousData,
  })
}

/** Fetch a single job by id. Disabled when `id` is null. */
export function useJob(id: string | null) {
  return useQuery<JobResponse>({
    queryKey: id ? jobsKeys.detail(id) : ["jobs", "detail", null],
    queryFn: () => fetchJob(id as string),
    enabled: !!id,
  })
}

/**
 * Fetch a job's transcript. Returns {@link TRANSCRIBING} when the job
 * has no transcript yet (404 -> "Transcribing..." state, D-14). Disabled
 * when `id` is null.
 */
export function useTranscript(id: string | null) {
  return useQuery<TranscriptResult>({
    queryKey: id ? jobsKeys.transcript(id) : ["transcripts", null],
    queryFn: () => fetchTranscript(id as string),
    enabled: !!id,
    // A 404 is the expected "not ready" state, not a transient failure.
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false
      return failureCount < 3
    },
  })
}

/**
 * Invalidate every cached query under the `["jobs"]` namespace so the
 * history list + any detail view refetch on the next mount/focus.
 *
 * Called by 05-02b's ActiveJobCard when a job reaches a terminal state
 * (done/failed/cancelled) and by 05-03's scroll-spy integration when a
 * transcript transitions from "transcribing" to ready.
 */
export function invalidateJobs(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: jobsKeys.all })
}

/** Re-export the query client hook for callers that need to invalidate. */
export { useQueryClient }