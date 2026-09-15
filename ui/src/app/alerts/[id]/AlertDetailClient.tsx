/**
 * AlertIQ — Investigation Workspace (Client Component)
 *
 * Full analyst investigation workspace for a single alert.
 * Sections: alert summary, explainability signals, transaction timeline,
 * decision workflow, notes, audit history, model metadata drawer.
 *
 * SECURITY NOTES:
 *   • No SAR ground-truth labels are displayed (never present in API response).
 *   • Analyst notes are saved locally to the AlertIQ backend only — never
 *     forwarded to any external service or LLM.
 *   • The system surfaces risk scores and feature signals as decision support.
 *     The analyst makes the final SAR determination independently.
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  addNote,
  fetchAlert,
  fetchAlertDecisions,
  fetchAlertHistory,
  fetchAlertNotes,
  fetchAlertTransactions,
  openAlert,
  recordDecision,
} from "@/lib/api";
import type {
  AlertDetail,
  AuditEvent,
  AuditHistoryResponse,
  Decision,
  DecisionOutcome,
  DecisionsResponse,
  ExplainabilitySignal,
  InvestigationNote,
  NotesResponse,
  Transaction,
  TransactionListResponse,
} from "@/lib/types";
import { QualityWarning } from "@/components/QualityWarning";
import { RiskBadge } from "@/components/RiskBadge";
import { StatusBadge } from "@/components/StatusBadge";

// ------------------------------------------------------------------ //
// Helpers                                                              //
// ------------------------------------------------------------------ //

function fmt(iso: string) {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function fmtDatetime(iso: string) {
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtEur(amount: number) {
  return new Intl.NumberFormat("en-IE", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-sm font-semibold text-aq-text uppercase tracking-wider">
        {title}
      </h2>
      {subtitle && (
        <p className="text-xs text-aq-text-dim mt-0.5">{subtitle}</p>
      )}
    </div>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-aq-border bg-aq-surface p-5 ${className}`}>
      {children}
    </div>
  );
}

// ------------------------------------------------------------------ //
// Alert Summary Header                                                 //
// ------------------------------------------------------------------ //

function AlertHeader({
  alert,
  onOpen,
  opening,
}: {
  alert: AlertDetail;
  onOpen: () => void;
  opening: boolean;
}) {
  return (
    <div className="mb-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-aq-text-dim mb-3">
        <Link href="/" className="hover:text-aq-text transition-colors">
          Queue
        </Link>
        <span>/</span>
        <span className="text-aq-text font-mono">{alert.alert_id}</span>
      </div>

      {/* Main header row */}
      <div className="flex flex-wrap items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-lg font-semibold text-aq-text font-mono">
              {alert.alert_id}
            </h1>
            <RiskBadge score={alert.risk_score} size="md" />
            <StatusBadge status={alert.status} />
            <QualityWarning
              warning={alert.quality_warning}
              detail={
                alert.quality_flags.zero_feature_names.length > 0
                  ? `Zeroed features: ${alert.quality_flags.zero_feature_names.slice(0, 4).join(", ")}`
                  : "Data quality issue detected"
              }
            />
          </div>
          <p className="text-sm text-aq-text-dim mt-1">
            Rule <span className="text-aq-text font-medium">{alert.rule_id}</span>
            {" · "}
            {alert.rule_name}
            {" · "}
            Alert date <span className="text-aq-text">{fmt(alert.alert_date)}</span>
          </p>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {alert.status === "new" && (
            <button
              onClick={onOpen}
              disabled={opening}
              className="h-8 px-4 rounded bg-aq-accent hover:bg-green-700 text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {opening ? "Opening…" : "Open Investigation"}
            </button>
          )}
          <Link
            href="/"
            className="h-8 px-3 rounded border border-aq-border text-aq-text-dim hover:text-aq-text hover:bg-aq-muted/50 text-sm transition-colors flex items-center"
          >
            ← Back
          </Link>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ //
// Alert Summary Card                                                   //
// ------------------------------------------------------------------ //

function AlertSummaryCard({ alert }: { alert: AlertDetail }) {
  const fields: { label: string; value: React.ReactNode }[] = [
    { label: "Account ID", value: <span className="font-mono">{alert.account_id}</span> },
    { label: "Rule ID", value: <span className="font-mono">{alert.rule_id}</span> },
    { label: "Severity", value: alert.severity },
    { label: "Alert Date", value: fmt(alert.alert_date) },
    { label: "Scored At", value: fmtDatetime(alert.scored_at) },
    { label: "Model Version", value: <span className="font-mono text-xs">{alert.model_version}</span> },
    { label: "Queue Position", value: <span className="font-mono tabular-nums">#{alert.queue_position}</span> },
    {
      label: "Assigned To",
      value: alert.assigned_to ?? <span className="italic text-aq-text-dim">Unassigned</span>,
    },
  ];

  return (
    <Card>
      <SectionHeader title="Alert Summary" />
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
        {fields.map(({ label, value }) => (
          <div key={label}>
            <dt className="text-xs text-aq-text-dim">{label}</dt>
            <dd className="text-sm text-aq-text mt-0.5">{value}</dd>
          </div>
        ))}
      </dl>

      {/* Data quality detail */}
      {alert.quality_warning && (
        <div className="mt-4 pt-4 border-t border-aq-border">
          <p className="text-xs font-medium text-yellow-400 mb-2 flex items-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm8-3a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 018 5zm0 7a1 1 0 110-2 1 1 0 010 2z" />
            </svg>
            Data Quality Warning
          </p>
          {alert.quality_flags.zero_feature_names.length > 0 && (
            <p className="text-xs text-aq-text-dim">
              Zeroed features:{" "}
              <span className="text-yellow-400/80 font-mono">
                {alert.quality_flags.zero_feature_names.join(", ")}
              </span>
            </p>
          )}
          {alert.quality_flags.extreme_feature_names.length > 0 && (
            <p className="text-xs text-aq-text-dim mt-1">
              Extreme values:{" "}
              <span className="text-yellow-400/80 font-mono">
                {alert.quality_flags.extreme_feature_names.join(", ")}
              </span>
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ //
// Explainability Panel                                                 //
// ------------------------------------------------------------------ //

const FLAG_STYLE: Record<ExplainabilitySignal["flag"], string> = {
  high: "bg-red-500/10 text-red-400 border border-red-500/20",
  low: "bg-blue-500/10 text-blue-400 border border-blue-500/20",
  none: "bg-aq-muted/30 text-aq-text-dim border border-aq-border",
};

function ExplainabilityPanel({ signals }: { signals: ExplainabilitySignal[] }) {
  const [showAll, setShowAll] = useState(false);
  const notable = signals.filter((s) => s.notable);
  const rest = signals.filter((s) => !s.notable);
  const displayed = showAll ? signals : notable.length > 0 ? notable : signals.slice(0, 8);

  return (
    <Card>
      <SectionHeader
        title="Risk Signals"
        subtitle="Feature values that contributed to the model score — analyst should verify independently"
      />

      {signals.length === 0 ? (
        <p className="text-sm text-aq-text-dim">No explainability signals available.</p>
      ) : (
        <>
          <div className="space-y-2">
            {displayed.map((sig) => (
              <div
                key={sig.feature}
                className={`flex items-center justify-between rounded px-3 py-2 gap-3 text-xs ${FLAG_STYLE[sig.flag]}`}
              >
                <div className="min-w-0 flex-1">
                  <span className="font-medium truncate block">{sig.label}</span>
                  <span className="opacity-70 font-mono text-[10px]">{sig.feature}</span>
                </div>
                <span className="font-mono tabular-nums flex-shrink-0 font-semibold">
                  {sig.display_value}
                </span>
                {sig.flag !== "none" && (
                  <span className="flex-shrink-0 uppercase text-[10px] font-bold tracking-wide opacity-80">
                    {sig.flag}
                  </span>
                )}
              </div>
            ))}
          </div>

          {(notable.length > 0 && rest.length > 0) || signals.length > 8 ? (
            <button
              onClick={() => setShowAll((v) => !v)}
              className="mt-3 text-xs text-aq-accent hover:text-blue-300 transition-colors"
            >
              {showAll
                ? "Show notable only"
                : `Show all ${signals.length} signals`}
            </button>
          ) : null}
        </>
      )}

      <p className="text-xs text-aq-text-dim/60 mt-4 italic">
        Decision-support only — feature signals are threshold-based indicators,
        not causal explanations. All SAR determinations require analyst judgement.
      </p>
    </Card>
  );
}

// ------------------------------------------------------------------ //
// Transaction Timeline                                                 //
// ------------------------------------------------------------------ //

interface ChartPoint {
  date: string;
  amount: number;
  txn_type: string;
}

const CHANNEL_COLOUR: Record<string, string> = {
  online: "#3B82F6",
  branch: "#22C55E",
  atm: "#F97316",
  pos: "#A855F7",
  wire: "#EF4444",
};

function TransactionTimeline({ data }: { data: TransactionListResponse }) {
  const [showTable, setShowTable] = useState(false);

  // Aggregate daily amounts for area chart
  const dailyMap = new Map<string, number>();
  for (const txn of data.transactions) {
    const day = txn.txn_date.slice(0, 10);
    dailyMap.set(day, (dailyMap.get(day) ?? 0) + txn.amount_eur);
  }
  const chartData: ChartPoint[] = Array.from(dailyMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-60) // last 60 days with activity
    .map(([date, amount]) => ({ date, amount: Math.round(amount), txn_type: "" }));

  const thCls = "px-3 py-2 text-left text-xs font-medium text-aq-text-dim uppercase tracking-wider";
  const tdCls = "px-3 py-2 text-xs";

  return (
    <Card>
      <SectionHeader
        title="Account Transaction History"
        subtitle={`${data.count} transactions for account`}
      />

      {data.count === 0 ? (
        <p className="text-sm text-aq-text-dim">No transactions found for this account.</p>
      ) : (
        <>
          {/* Area chart */}
          <div className="h-40 mb-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                <defs>
                  <linearGradient id="txnGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1E3050" />
                <XAxis
                  dataKey="date"
                  tick={{ fill: "#6B8CAE", fontSize: 10 }}
                  tickFormatter={(v) => v.slice(5)} // MM-DD
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fill: "#6B8CAE", fontSize: 10 }}
                  tickFormatter={(v) => `€${(v / 1000).toFixed(0)}k`}
                  width={44}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#162033",
                    border: "1px solid #1E3050",
                    borderRadius: 6,
                    fontSize: 12,
                    color: "#C8D6E8",
                  }}
                  formatter={(v: number) => [fmtEur(v), "Daily volume"]}
                  labelStyle={{ color: "#6B8CAE" }}
                />
                <Area
                  type="monotone"
                  dataKey="amount"
                  stroke="#3B82F6"
                  strokeWidth={1.5}
                  fill="url(#txnGradient)"
                  dot={false}
                  activeDot={{ r: 4, fill: "#3B82F6" }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Toggle table */}
          <button
            onClick={() => setShowTable((v) => !v)}
            className="text-xs text-aq-accent hover:text-blue-300 transition-colors mb-3"
          >
            {showTable ? "Hide transaction table" : `Show transaction table (${data.count})`}
          </button>

          {showTable && (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-aq-border text-xs">
                <thead>
                  <tr>
                    <th className={thCls}>Date</th>
                    <th className={thCls}>Type</th>
                    <th className={thCls}>Channel</th>
                    <th className={thCls}>Amount</th>
                    <th className={thCls}>Intl</th>
                    <th className={thCls}>Jurisdiction</th>
                    <th className={thCls}>Shell</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-aq-border">
                  {data.transactions.slice(0, 100).map((txn) => (
                    <tr
                      key={txn.txn_id}
                      className={`${txn.is_typology ? "bg-red-500/5" : ""} hover:bg-aq-muted/20`}
                    >
                      <td className={`${tdCls} font-mono tabular-nums text-aq-text-dim`}>
                        {txn.txn_date}
                      </td>
                      <td className={`${tdCls} text-aq-text`}>{txn.txn_type}</td>
                      <td className={tdCls}>
                        <span
                          className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium"
                          style={{
                            backgroundColor: `${CHANNEL_COLOUR[txn.channel] ?? "#6B7280"}18`,
                            color: CHANNEL_COLOUR[txn.channel] ?? "#6B7280",
                          }}
                        >
                          {txn.channel}
                        </span>
                      </td>
                      <td className={`${tdCls} font-mono tabular-nums text-right text-aq-text`}>
                        {fmtEur(txn.amount_eur)}
                      </td>
                      <td className={`${tdCls} text-center`}>
                        {txn.is_international ? (
                          <span className="text-orange-400">✓</span>
                        ) : (
                          <span className="text-aq-text-dim/40">—</span>
                        )}
                      </td>
                      <td className={`${tdCls} text-aq-text-dim font-mono`}>
                        {txn.destination_jurisdiction ?? "—"}
                      </td>
                      <td className={`${tdCls} text-center`}>
                        {txn.counterparty_is_shell ? (
                          <span className="text-red-400 font-bold">⚠</span>
                        ) : (
                          <span className="text-aq-text-dim/40">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.count > 100 && (
                <p className="text-xs text-aq-text-dim mt-2 text-center">
                  Showing 100 of {data.count} transactions
                </p>
              )}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ //
// Decision Workflow                                                    //
// ------------------------------------------------------------------ //

const OUTCOME_CONFIG: Record<
  DecisionOutcome,
  { label: string; style: string; activeStyle: string }
> = {
  escalate: {
    label: "Escalate to SAR",
    style: "border-red-500/30 text-red-400 hover:bg-red-500/10",
    activeStyle: "border-red-500 bg-red-500/20 text-red-300 ring-1 ring-red-500/40",
  },
  needs_further_review: {
    label: "Needs Further Review",
    style: "border-orange-500/30 text-orange-400 hover:bg-orange-500/10",
    activeStyle:
      "border-orange-500 bg-orange-500/20 text-orange-300 ring-1 ring-orange-500/40",
  },
  close: {
    label: "Close — No Action",
    style: "border-green-500/30 text-green-400 hover:bg-green-500/10",
    activeStyle: "border-green-500 bg-green-500/20 text-green-300 ring-1 ring-green-500/40",
  },
};

function DecisionPanel({
  alertId,
  decisions,
  onDecisionRecorded,
}: {
  alertId: string;
  decisions: Decision[];
  onDecisionRecorded: () => void;
}) {
  const [outcome, setOutcome] = useState<DecisionOutcome | null>(null);
  const [rationale, setRationale] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async () => {
    if (!outcome) return;
    setSubmitting(true);
    setError(null);
    try {
      await recordDecision(alertId, {
        outcome,
        rationale: rationale.trim() || undefined,
        analyst_id: "analyst-001", // Demo analyst ID
      });
      setSuccess(true);
      setOutcome(null);
      setRationale("");
      onDecisionRecorded();
      setTimeout(() => setSuccess(false), 3000);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setError(e?.message ?? "Failed to record decision");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <SectionHeader
        title="Record Decision"
        subtitle="Analyst determination — independent of model recommendation"
      />

      {/* Outcome selection */}
      <div className="space-y-2 mb-4">
        {(Object.entries(OUTCOME_CONFIG) as [DecisionOutcome, typeof OUTCOME_CONFIG[DecisionOutcome]][]).map(
          ([key, cfg]) => (
            <button
              key={key}
              onClick={() => setOutcome(key)}
              className={`w-full text-left px-3 py-2.5 rounded border text-sm font-medium transition-all ${
                outcome === key ? cfg.activeStyle : cfg.style + " bg-transparent"
              }`}
            >
              {cfg.label}
            </button>
          ),
        )}
      </div>

      {/* Rationale */}
      <div className="mb-4">
        <label
          htmlFor="rationale"
          className="block text-xs text-aq-text-dim mb-1.5"
        >
          Rationale{" "}
          <span className="text-aq-text-dim/60">(optional — stored locally, not shared externally)</span>
        </label>
        <textarea
          id="rationale"
          rows={4}
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="Summarise your investigation findings…"
          className="w-full rounded border border-aq-border bg-aq-muted/40 px-3 py-2 text-sm text-aq-text placeholder:text-aq-text-dim/60 focus:outline-none focus:ring-1 focus:ring-aq-accent focus:border-aq-accent resize-none transition-colors"
        />
      </div>

      {error && (
        <p className="text-xs text-red-400 mb-3">{error}</p>
      )}

      {success && (
        <p className="text-xs text-green-400 mb-3">Decision recorded successfully.</p>
      )}

      <button
        onClick={handleSubmit}
        disabled={!outcome || submitting}
        className="w-full h-9 rounded bg-aq-accent hover:bg-green-700 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {submitting ? "Recording…" : "Record Decision"}
      </button>

      {/* Previous decisions */}
      {decisions.length > 0 && (
        <div className="mt-5 pt-4 border-t border-aq-border">
          <p className="text-xs font-medium text-aq-text-dim uppercase tracking-wider mb-3">
            Decision History
          </p>
          <div className="space-y-2">
            {decisions.map((d) => (
              <div
                key={d.decision_id}
                className="rounded border border-aq-border bg-aq-muted/20 px-3 py-2 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={`font-medium ${
                      d.outcome === "escalate"
                        ? "text-red-400"
                        : d.outcome === "close"
                        ? "text-green-400"
                        : "text-orange-400"
                    }`}
                  >
                    {OUTCOME_CONFIG[d.outcome].label}
                  </span>
                  <span className="text-aq-text-dim tabular-nums">
                    {fmtDatetime(d.decided_at)}
                  </span>
                </div>
                {d.rationale && (
                  <p className="text-aq-text-dim mt-1">{d.rationale}</p>
                )}
                <p className="text-aq-text-dim/60 mt-0.5">by {d.analyst_id}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ //
// Notes Panel                                                          //
// ------------------------------------------------------------------ //

function NotesPanel({
  alertId,
  notes,
  onNoteAdded,
}: {
  alertId: string;
  notes: InvestigationNote[];
  onNoteAdded: () => void;
}) {
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = async () => {
    if (!content.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await addNote(alertId, {
        content: content.trim(),
        analyst_id: "analyst-001",
      });
      setContent("");
      onNoteAdded();
    } catch (err: unknown) {
      const e = err as { message?: string };
      setError(e?.message ?? "Failed to save note");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <SectionHeader title="Investigation Notes" />

      {/* Add note */}
      <div className="mb-4">
        <textarea
          rows={3}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Add an investigation note…"
          className="w-full rounded border border-aq-border bg-aq-muted/40 px-3 py-2 text-sm text-aq-text placeholder:text-aq-text-dim/60 focus:outline-none focus:ring-1 focus:ring-aq-accent focus:border-aq-accent resize-none transition-colors"
        />
        {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
        <button
          onClick={handleAdd}
          disabled={!content.trim() || submitting}
          className="mt-2 h-8 px-4 rounded bg-aq-muted hover:bg-aq-muted/80 border border-aq-border text-aq-text text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {submitting ? "Saving…" : "Add Note"}
        </button>
      </div>

      {/* Existing notes */}
      {notes.length === 0 ? (
        <p className="text-xs text-aq-text-dim italic">No notes yet.</p>
      ) : (
        <div className="space-y-3">
          {notes.map((note) => (
            <div
              key={note.note_id}
              className="rounded border border-aq-border bg-aq-muted/20 px-3 py-2.5"
            >
              <p className="text-sm text-aq-text whitespace-pre-wrap">{note.content}</p>
              <p className="text-xs text-aq-text-dim/70 mt-1.5">
                {note.analyst_id} · {fmtDatetime(note.created_at)}
              </p>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ //
// Audit History                                                        //
// ------------------------------------------------------------------ //

function AuditHistory({ events }: { events: AuditEvent[] }) {
  const [expanded, setExpanded] = useState(false);
  const displayed = expanded ? events : events.slice(0, 5);

  const EVENT_ICON: Record<string, string> = {
    alert_opened: "📂",
    decision_recorded: "⚖️",
    note_added: "📝",
    status_changed: "🔄",
  };

  return (
    <Card>
      <SectionHeader title="Audit Trail" />

      {events.length === 0 ? (
        <p className="text-xs text-aq-text-dim italic">No audit events yet.</p>
      ) : (
        <>
          <div className="space-y-2">
            {displayed.map((evt) => (
              <div
                key={evt.event_id}
                className="flex items-start gap-2 text-xs"
              >
                <span className="text-sm mt-0.5 flex-shrink-0" aria-hidden>
                  {EVENT_ICON[evt.event_type] ?? "📋"}
                </span>
                <div className="min-w-0 flex-1">
                  <span className="text-aq-text font-medium">{evt.event_type}</span>
                  {" · "}
                  <span className="text-aq-text-dim">{evt.analyst_id}</span>
                  <br />
                  <span className="text-aq-text-dim/70 tabular-nums">
                    {fmtDatetime(evt.occurred_at)}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {events.length > 5 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="mt-3 text-xs text-aq-accent hover:text-blue-300 transition-colors"
            >
              {expanded ? "Show less" : `Show all ${events.length} events`}
            </button>
          )}
        </>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ //
// Model Metadata Drawer                                                //
// ------------------------------------------------------------------ //

function ModelMetadataDrawer({ alert }: { alert: AlertDetail }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-aq-text-dim hover:text-aq-text transition-colors flex items-center gap-1.5"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 16 16"
          fill="currentColor"
          className={`transition-transform ${open ? "rotate-90" : ""}`}
        >
          <path d="M6 4l4 4-4 4V4z" />
        </svg>
        Model metadata
      </button>

      {open && (
        <div className="mt-2 rounded border border-aq-border bg-aq-muted/20 p-3 text-xs space-y-1.5">
          <div className="flex justify-between">
            <span className="text-aq-text-dim">Model version</span>
            <span className="font-mono text-aq-text">{alert.model_version}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-aq-text-dim">Schema version</span>
            <span className="font-mono text-aq-text">{alert.schema_version}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-aq-text-dim">Risk score</span>
            <span className="font-mono text-aq-text tabular-nums">
              {(alert.risk_score * 100).toFixed(2)}%
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-aq-text-dim">Scored at</span>
            <span className="font-mono text-aq-text">{fmtDatetime(alert.scored_at)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-aq-text-dim">Feature count</span>
            <span className="font-mono text-aq-text">
              {Object.keys(alert.features).length}
            </span>
          </div>
          <p className="text-aq-text-dim/60 italic pt-1">
            Model scores are decision-support signals only. The analyst is
            responsible for the final SAR determination.
          </p>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ //
// Main Client Component                                                //
// ------------------------------------------------------------------ //

interface AlertDetailClientProps {
  alertId: string;
}

export function AlertDetailClient({ alertId }: AlertDetailClientProps) {
  const [alert, setAlert] = useState<AlertDetail | null>(null);
  const [transactions, setTransactions] = useState<TransactionListResponse | null>(null);
  const [notes, setNotes] = useState<InvestigationNote[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [alertData, txnData, notesData, decisionsData, historyData] =
        await Promise.all([
          fetchAlert(alertId),
          fetchAlertTransactions(alertId, 200),
          fetchAlertNotes(alertId),
          fetchAlertDecisions(alertId),
          fetchAlertHistory(alertId),
        ]);

      setAlert(alertData);
      setTransactions(txnData);
      setNotes(notesData.notes);
      setDecisions(decisionsData.decisions);
      setAuditEvents(historyData.events);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setError(e?.message ?? "Failed to load alert");
    } finally {
      setLoading(false);
    }
  }, [alertId]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleOpen = useCallback(async () => {
    setOpening(true);
    try {
      await openAlert(alertId, "analyst-001");
      // Refresh alert data to get updated status
      const updated = await fetchAlert(alertId);
      setAlert(updated);
      // Refresh audit trail
      const history = await fetchAlertHistory(alertId);
      setAuditEvents(history.events);
    } catch (err) {
      console.error("Failed to open alert:", err);
    } finally {
      setOpening(false);
    }
  }, [alertId]);

  const refreshNotes = useCallback(async () => {
    const notesData = await fetchAlertNotes(alertId);
    setNotes(notesData.notes);
    const history = await fetchAlertHistory(alertId);
    setAuditEvents(history.events);
  }, [alertId]);

  const refreshDecisions = useCallback(async () => {
    const decisionsData = await fetchAlertDecisions(alertId);
    setDecisions(decisionsData.decisions);
    const updated = await fetchAlert(alertId);
    setAlert(updated);
    const history = await fetchAlertHistory(alertId);
    setAuditEvents(history.events);
  }, [alertId]);

  // ── Loading state ──────────────────────────────────────────────── //

  if (loading) {
    return (
      <div className="text-center py-20 text-aq-text-dim text-sm animate-pulse">
        Loading investigation workspace…
      </div>
    );
  }

  if (error || !alert) {
    return (
      <div className="max-w-xl mx-auto mt-12">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-5 py-4 text-sm text-red-400">
          <strong>Error:</strong> {error ?? "Alert not found"}
        </div>
        <Link
          href="/"
          className="inline-block mt-4 text-sm text-aq-accent hover:text-blue-300 transition-colors"
        >
          ← Return to queue
        </Link>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────── //

  return (
    <div>
      {/* Header */}
      <AlertHeader alert={alert} onOpen={handleOpen} opening={opening} />

      {/* Two-column workspace */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-5 items-start">
        {/* ── Left column ── */}
        <div className="space-y-5 min-w-0">
          {/* Alert summary */}
          <AlertSummaryCard alert={alert} />

          {/* Explainability */}
          <ExplainabilityPanel signals={alert.explainability_signals} />

          {/* Transaction timeline */}
          {transactions && <TransactionTimeline data={transactions} />}
        </div>

        {/* ── Right column ── */}
        <div className="space-y-5">
          {/* Decision workflow */}
          <DecisionPanel
            alertId={alertId}
            decisions={decisions}
            onDecisionRecorded={refreshDecisions}
          />

          {/* Notes */}
          <NotesPanel
            alertId={alertId}
            notes={notes}
            onNoteAdded={refreshNotes}
          />

          {/* Audit trail */}
          <AuditHistory events={auditEvents} />

          {/* Model metadata */}
          <ModelMetadataDrawer alert={alert} />
        </div>
      </div>
    </div>
  );
}
