/**
 * AlertIQ — Shared TypeScript types for the Investigation Workspace.
 *
 * These types mirror the JSON shapes returned by the backend API.
 * All types are read-only to prevent accidental mutation.
 */

// ------------------------------------------------------------------ //
// Risk & status                                                        //
// ------------------------------------------------------------------ //

export type RiskBand = "critical" | "high" | "medium" | "low" | "minimal";
export type AlertStatus =
  | "new"
  | "in_progress"
  | "escalated"
  | "closed"
  | "needs_further_review";
export type DecisionOutcome =
  | "escalate"
  | "close"
  | "needs_further_review";

// ------------------------------------------------------------------ //
// Queue                                                                //
// ------------------------------------------------------------------ //

export interface QueueStats {
  total_alerts: number;
  capacity_fraction: number; // 0.0–1.0 (e.g. 0.20 = top 20%)
  capacity_count: number;   // alerts inside the capacity band
  status_counts: Record<AlertStatus, number>;
}

// ------------------------------------------------------------------ //
// Alert list                                                           //
// ------------------------------------------------------------------ //

export interface AlertSummary {
  alert_id: string;
  account_id: string;
  rule_id: string;
  rule_name: string;
  severity: string;
  alert_date: string;           // ISO date
  risk_score: number;           // 0.0–1.0
  queue_position: number;
  status: AlertStatus;
  assigned_to: string | null;
  quality_warning: boolean;
  model_version: string;
}

export interface AlertListResponse {
  total: number;
  page: number;
  page_size: number;
  items: AlertSummary[];
}

// ------------------------------------------------------------------ //
// Alert detail                                                         //
// ------------------------------------------------------------------ //

export interface DataQualityFlags {
  has_zeroed_features: boolean;
  zero_feature_names: string[];
  has_extreme_values: boolean;
  extreme_feature_names: string[];
  quality_warning: boolean;
}

export interface ExplainabilitySignal {
  feature: string;
  label: string;
  value: number;
  display_value: string;
  notable: boolean;
  flag: "high" | "low" | "none";
}

export interface AlertDetail extends AlertSummary {
  schema_version: number;
  scored_at: string;            // ISO datetime
  features: Record<string, number>;
  quality_flags: DataQualityFlags;
  explainability_signals: ExplainabilitySignal[];
}

// ------------------------------------------------------------------ //
// Transactions                                                         //
// ------------------------------------------------------------------ //

export interface Transaction {
  txn_id: string;
  account_id: string;
  txn_date: string;
  txn_datetime: string | null;
  txn_type: string;
  channel: string;
  amount_eur: number;
  is_international: 0 | 1;
  destination_jurisdiction: string | null;
  counterparty_id: string | null;
  counterparty_jurisdiction: string | null;
  counterparty_is_shell: 0 | 1;
  is_typology: 0 | 1;
}

export interface TransactionListResponse {
  alert_id: string;
  transactions: Transaction[];
  count: number;
}

// ------------------------------------------------------------------ //
// Audit history                                                        //
// ------------------------------------------------------------------ //

export interface AuditEvent {
  event_id: string;
  alert_id: string;
  event_type: string;
  analyst_id: string;
  occurred_at: string;          // ISO datetime
  payload: Record<string, unknown>;
}

export interface AuditHistoryResponse {
  alert_id: string;
  events: AuditEvent[];
  count: number;
}

// ------------------------------------------------------------------ //
// Notes                                                                //
// ------------------------------------------------------------------ //

export interface InvestigationNote {
  note_id: string;
  alert_id: string;
  analyst_id: string;
  content: string;
  created_at: string;           // ISO datetime
}

export interface NotesResponse {
  alert_id: string;
  notes: InvestigationNote[];
  count: number;
}

// ------------------------------------------------------------------ //
// Decisions                                                            //
// ------------------------------------------------------------------ //

export interface Decision {
  decision_id: string;
  alert_id: string;
  analyst_id: string;
  outcome: DecisionOutcome;
  rationale: string | null;
  decided_at: string;           // ISO datetime
}

export interface DecisionsResponse {
  alert_id: string;
  decisions: Decision[];
  count: number;
}

// ------------------------------------------------------------------ //
// Write request bodies                                                 //
// ------------------------------------------------------------------ //

export interface AddNoteBody {
  content: string;
  analyst_id?: string;
}

export interface RecordDecisionBody {
  outcome: DecisionOutcome;
  rationale?: string;
  analyst_id?: string;
}

// ------------------------------------------------------------------ //
// Alert queue filter state                                             //
// ------------------------------------------------------------------ //

export interface AlertFilters {
  status?: AlertStatus | "";
  rule_id?: string;
  min_score?: number | "";
  search?: string;
  sort_by?: "risk_score" | "alert_date" | "severity" | "queue_position";
  sort_dir?: "asc" | "desc";
  page?: number;
  page_size?: number;
}
