"use client";

/**
 * Investigations page — active investigations workview.
 * Shows all alerts that are in_progress, escalated, or needs_further_review.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchAlerts } from "@/lib/api";
import type { AlertSummary, AlertStatus } from "@/lib/types";
import { RiskBadge } from "@/components/RiskBadge";
import { StatusBadge } from "@/components/StatusBadge";

interface GroupedAlerts {
  escalated: AlertSummary[];
  needs_further_review: AlertSummary[];
  in_progress: AlertSummary[];
}

export default function InvestigationsPage() {
  const router = useRouter();
  const [groups, setGroups] = useState<GroupedAlerts>({
    escalated: [],
    needs_further_review: [],
    in_progress: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);

    Promise.all([
      fetchAlerts({ status: "escalated",            sort_by: "risk_score", sort_dir: "desc", page: 1, page_size: 50 }),
      fetchAlerts({ status: "needs_further_review", sort_by: "risk_score", sort_dir: "desc", page: 1, page_size: 50 }),
      fetchAlerts({ status: "in_progress",          sort_by: "risk_score", sort_dir: "desc", page: 1, page_size: 50 }),
    ])
      .then(([esc, review, prog]) => {
        setGroups({
          escalated: esc.items,
          needs_further_review: review.items,
          in_progress: prog.items,
        });
        setLoading(false);
      })
      .catch((err) => {
        setError(err?.message ?? "Failed to load investigations");
        setLoading(false);
      });
  }, []);

  const total = groups.escalated.length + groups.needs_further_review.length + groups.in_progress.length;

  const handleOpen = (id: string) => router.push(`/alerts/${encodeURIComponent(id)}`);

  return (
    <div>
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-aq-text tracking-tight">Investigations</h1>
        <p className="text-sm text-aq-text-dim mt-0.5">
          Active alerts under analyst review — escalated, in progress, and flagged for further review.
        </p>
      </div>

      {/* Summary strip */}
      {!loading && !error && (
        <div className="rounded border border-gray-200 bg-white shadow-sm mb-6 px-5 py-4">
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
            <div className="flex items-baseline gap-1.5">
              <span className="text-2xl font-bold text-aq-text tabular-nums">{total}</span>
              <span className="text-xs text-aq-text-dim">active investigations</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-full bg-red-500" />
              <span className="text-xs text-aq-text-secondary">{groups.escalated.length} escalated</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-full bg-amber-500" />
              <span className="text-xs text-aq-text-secondary">{groups.needs_further_review.length} needs review</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-full bg-violet-500" />
              <span className="text-xs text-aq-text-secondary">{groups.in_progress.length} in progress</span>
            </div>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="rounded border border-gray-200 bg-white shadow-sm px-6 py-16 text-center">
          <p className="text-sm text-aq-text-dim animate-pulse">Loading investigations…</p>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          <p className="font-medium mb-0.5">Unable to load investigations</p>
          <p className="text-xs opacity-80">{error}</p>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && total === 0 && (
        <div className="rounded border border-gray-200 bg-white shadow-sm px-6 py-16 text-center">
          <p className="text-sm font-medium text-aq-text mb-1">No active investigations</p>
          <p className="text-xs text-aq-text-dim">
            Open alerts from the{" "}
            <a href="/" className="text-aq-accent hover:underline">Queue</a>{" "}
            to start an investigation.
          </p>
        </div>
      )}

      {/* Groups */}
      {!loading && !error && total > 0 && (
        <div className="space-y-8">
          <AlertGroup title="Escalated"           color="red"    alerts={groups.escalated}            onOpen={handleOpen} />
          <AlertGroup title="Needs Further Review" color="amber"  alerts={groups.needs_further_review} onOpen={handleOpen} />
          <AlertGroup title="In Progress"          color="violet" alerts={groups.in_progress}          onOpen={handleOpen} />
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ //
// Alert group table                                                    //
// ------------------------------------------------------------------ //

const DOT: Record<string, string> = {
  red:    "bg-red-500",
  amber:  "bg-amber-500",
  violet: "bg-violet-500",
};

function AlertGroup({
  title,
  color,
  alerts,
  onOpen,
}: {
  title: string;
  color: string;
  alerts: AlertSummary[];
  onOpen: (id: string) => void;
}) {
  if (alerts.length === 0) return null;

  const thCls =
    "px-4 py-3 text-left text-xs font-medium text-aq-text-secondary uppercase tracking-wider whitespace-nowrap bg-gray-50 border-b border-gray-200";
  const tdCls = "px-4 py-3.5 text-sm";

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className={`inline-block w-2.5 h-2.5 rounded-full ${DOT[color]}`} />
        <h2 className="text-sm font-semibold text-aq-text">{title}</h2>
        <span className="text-xs text-aq-text-dim tabular-nums">({alerts.length})</span>
      </div>

      <div className="overflow-x-auto rounded border border-gray-200 shadow-sm">
        <table className="min-w-full divide-y divide-aq-border" role="grid">
          <thead>
            <tr className="divide-x divide-gray-100">
              <th scope="col" className={thCls}>Alert ID</th>
              <th scope="col" className={thCls}>Account</th>
              <th scope="col" className={thCls}>Rule</th>
              <th scope="col" className={thCls}>Date</th>
              <th scope="col" className={thCls}>Risk</th>
              <th scope="col" className={thCls}>Status</th>
              <th scope="col" className={thCls}>Assigned</th>
              <th scope="col" className={`${thCls} w-8`} aria-hidden="true" />
            </tr>
          </thead>
          <tbody className="divide-y divide-aq-border">
            {alerts.map((alert, idx) => (
              <tr
                key={alert.alert_id}
                onClick={() => onOpen(alert.alert_id)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(alert.alert_id); } }}
                tabIndex={0}
                className={
                  "cursor-pointer transition-colors group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-aq-accent " +
                  (idx % 2 === 0 ? "bg-white hover:bg-green-50/60" : "bg-gray-50/70 hover:bg-green-50/60")
                }
              >
                <td className={tdCls}>
                  <span className="font-mono text-xs text-aq-accent group-hover:text-green-700 transition-colors">
                    {alert.alert_id.slice(0, 12)}{alert.alert_id.length > 12 && "…"}
                  </span>
                </td>
                <td className={`${tdCls} font-mono text-xs text-aq-text-secondary`}>{alert.account_id}</td>
                <td className={tdCls}>
                  <div className="text-xs font-medium text-aq-text max-w-[10rem] truncate" title={alert.rule_name}>{alert.rule_name}</div>
                  <div className="font-mono text-xs text-aq-text-dim mt-0.5">{alert.rule_id}</div>
                </td>
                <td className={`${tdCls} text-aq-text-dim text-xs tabular-nums whitespace-nowrap`}>
                  {new Date(alert.alert_date).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}
                </td>
                <td className={tdCls}><RiskBadge score={alert.risk_score} /></td>
                <td className={tdCls}><StatusBadge status={alert.status} /></td>
                <td className={`${tdCls} text-xs`}>
                  {alert.assigned_to ?? <span className="text-aq-text-dim">Unassigned</span>}
                </td>
                <td className={`${tdCls} text-aq-text-dim group-hover:text-aq-text-secondary transition-colors text-right pr-3`} aria-hidden="true">
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M6 4l4 4-4 4" />
                  </svg>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
