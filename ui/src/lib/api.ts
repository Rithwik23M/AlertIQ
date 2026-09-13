/**
 * AlertIQ — Typed API client for the Investigation Workspace.
 *
 * All calls go through /api/* which Next.js rewrites to the backend
 * at http://localhost:8000/* in development (next.config.ts).
 *
 * All functions return the parsed response body on success and throw
 * an ApiError on HTTP 4xx/5xx or network failure.
 */

import type {
  AlertDetail,
  AlertFilters,
  AlertListResponse,
  AddNoteBody,
  AuditHistoryResponse,
  Decision,
  DecisionsResponse,
  InvestigationNote,
  NotesResponse,
  QueueStats,
  RecordDecisionBody,
  TransactionListResponse,
} from "./types";

// ------------------------------------------------------------------ //
// Error class                                                          //
// ------------------------------------------------------------------ //

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: Record<string, unknown>,
  ) {
    super(
      (body?.error as string) ??
        `HTTP ${status} error from AlertIQ API`,
    );
    this.name = "ApiError";
  }
}

// ------------------------------------------------------------------ //
// Internal helpers                                                     //
// ------------------------------------------------------------------ //

const BASE = "/api";

async function _get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body);
  }
  return res.json() as Promise<T>;
}

async function _post<T>(
  path: string,
  body?: Record<string, unknown>,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new ApiError(res.status, errBody);
  }
  return res.json() as Promise<T>;
}

function _buildQs(filters: AlertFilters): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== "" && v !== null) {
      params.set(k, String(v));
    }
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

// ------------------------------------------------------------------ //
// Queue                                                                //
// ------------------------------------------------------------------ //

export function fetchQueueStats(): Promise<QueueStats> {
  return _get<QueueStats>("/queue/stats");
}

// ------------------------------------------------------------------ //
// Alert list                                                           //
// ------------------------------------------------------------------ //

export function fetchAlerts(
  filters: AlertFilters = {},
): Promise<AlertListResponse> {
  return _get<AlertListResponse>(`/alerts${_buildQs(filters)}`);
}

// ------------------------------------------------------------------ //
// Alert detail                                                         //
// ------------------------------------------------------------------ //

export function fetchAlert(alertId: string): Promise<AlertDetail> {
  return _get<AlertDetail>(`/alerts/${encodeURIComponent(alertId)}`);
}

export function fetchAlertTransactions(
  alertId: string,
  limit = 100,
): Promise<TransactionListResponse> {
  return _get<TransactionListResponse>(
    `/alerts/${encodeURIComponent(alertId)}/transactions?limit=${limit}`,
  );
}

export function fetchAlertHistory(
  alertId: string,
): Promise<AuditHistoryResponse> {
  return _get<AuditHistoryResponse>(
    `/alerts/${encodeURIComponent(alertId)}/history`,
  );
}

export function fetchAlertNotes(alertId: string): Promise<NotesResponse> {
  return _get<NotesResponse>(`/alerts/${encodeURIComponent(alertId)}/notes`);
}

export function fetchAlertDecisions(
  alertId: string,
): Promise<DecisionsResponse> {
  return _get<DecisionsResponse>(
    `/alerts/${encodeURIComponent(alertId)}/decisions`,
  );
}

// ------------------------------------------------------------------ //
// Write operations                                                     //
// ------------------------------------------------------------------ //

export function openAlert(
  alertId: string,
  analystId?: string,
): Promise<{ alert_id: string; analyst_id: string; status: string }> {
  return _post(`/alerts/${encodeURIComponent(alertId)}/open`, {
    analyst_id: analystId,
  });
}

export function addNote(
  alertId: string,
  body: AddNoteBody,
): Promise<InvestigationNote> {
  return _post<InvestigationNote>(
    `/alerts/${encodeURIComponent(alertId)}/notes`,
    body as unknown as Record<string, unknown>,
  );
}

export function recordDecision(
  alertId: string,
  body: RecordDecisionBody,
): Promise<Decision> {
  return _post<Decision>(
    `/alerts/${encodeURIComponent(alertId)}/decision`,
    body as unknown as Record<string, unknown>,
  );
}
