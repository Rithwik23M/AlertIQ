/**
 * AlertQueueClient — Interactive alert queue with capacity strip,
 * sort/filter/search controls, and a paginated alert table.
 *
 * This is a Client Component. It fetches queue stats and alerts from
 * the backend via the typed API client, then re-fetches whenever the
 * filter/sort/page state changes.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchAlerts, fetchQueueStats } from "@/lib/api";
import type { AlertFilters, AlertListResponse, AlertStatus, QueueStats } from "@/lib/types";
import { QualityWarning } from "@/components/QualityWarning";
import { RiskBadge } from "@/components/RiskBadge";
import { StatusBadge } from "@/components/StatusBadge";

// ------------------------------------------------------------------ //
// Constants                                                            //
// ------------------------------------------------------------------ //

const PAGE_SIZE = 25;

const STATUS_OPTIONS: { value: AlertStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "new", label: "New" },
  { value: "in_progress", label: "In Progress" },
  { value: "escalated", label: "Escalated" },
  { value: "needs_further_review", label: "Needs Review" },
  { value: "closed", label: "Closed" },
];

const SORT_OPTIONS: {
  value: NonNullable<AlertFilters["sort_by"]>;
  label: string;
}[] = [
  { value: "risk_score", label: "Risk Score" },
  { value: "queue_position", label: "Queue Position" },
  { value: "alert_date", label: "Alert Date" },
  { value: "severity", label: "Severity" },
];

// ------------------------------------------------------------------ //
// Capacity Strip                                                       //
// ------------------------------------------------------------------ //

function CapacityBanner({ stats }: { stats: QueueStats }) {
  const pct = Math.round(stats.capacity_fraction * 100);
  const inCapacity = stats.capacity_count;
  const total = stats.total_alerts;

  // Capacity bar represents how much of the reserved band is filled.
  const capacityBandSize = Math.max(1, Math.round(total * stats.capacity_fraction));
  const pctFilled = Math.min(100, Math.round((inCapacity / capacityBandSize) * 100));

  const statusPairs: { label: string; status: AlertStatus }[] = [
    { label: "New",         status: "new" },
    { label: "In Progress", status: "in_progress" },
    { label: "Escalated",   status: "escalated" },
    { label: "Needs Review",status: "needs_further_review" },
    { label: "Closed",      status: "closed" },
  ];

  return (
    <div
      className="rounded border border-aq-border bg-aq-surface mb-6 grid grid-cols-1 sm:grid-cols-3"
      role="region"
      aria-label="Queue capacity summary"
    >
      {/* Col 1 — Review Capacity */}
      <div className="px-5 py-4 sm:border-r sm:border-aq-border">
        <p className="text-xs font-medium text-aq-text-secondary uppercase tracking-wide mb-2">
          Review Capacity
        </p>
        <div className="flex items-baseline gap-1.5">
          <span className="text-2xl font-semibold text-aq-text tabular-nums">
            {inCapacity}
          </span>
          <span className="text-sm text-aq-text-dim">
            of {total} alerts
          </span>
        </div>
        <p className="text-xs text-aq-text-dim mt-0.5">
          Capacity policy: top {pct}%
        </p>
      </div>

      {/* Col 2 — Queue Status */}
      <div className="px-5 py-4 border-t border-aq-border sm:border-t-0 sm:border-r sm:border-aq-border">
        <p className="text-xs font-medium text-aq-text-secondary uppercase tracking-wide mb-2">
          Queue Status
        </p>
        <div className="flex flex-wrap gap-x-5 gap-y-1.5">
          {statusPairs.map(({ label, status }) => {
            const count = stats.status_counts[status] ?? 0;
            return (
              <div key={status} className="flex items-center gap-1.5">
                <span className="text-sm font-semibold tabular-nums text-aq-text">
                  {count}
                </span>
                <span className="text-xs text-aq-text-dim">{label}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Col 3 — Capacity Utilisation */}
      <div className="px-5 py-4 border-t border-aq-border sm:border-t-0">
        <p className="text-xs font-medium text-aq-text-secondary uppercase tracking-wide mb-2">
          Capacity Utilisation
        </p>
        <div
          className="h-1.5 rounded-full bg-aq-muted overflow-hidden"
          role="progressbar"
          aria-valuenow={pctFilled}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${pctFilled}% of capacity band filled`}
        >
          <div
            className="h-full rounded-full bg-aq-accent transition-all duration-500"
            style={{ width: `${pctFilled}%` }}
          />
        </div>
        <p className="text-xs text-aq-text-dim mt-2 tabular-nums">
          {pctFilled}% utilised
          <span className="mx-1.5 text-aq-border" aria-hidden="true">·</span>
          {inCapacity} alerts in band
        </p>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ //
// Filter Bar                                                           //
// ------------------------------------------------------------------ //

interface FilterBarProps {
  filters: AlertFilters;
  onFiltersChange: (patch: Partial<AlertFilters>) => void;
  onReset: () => void;
}

function FilterBar({ filters, onFiltersChange, onReset }: FilterBarProps) {
  const [searchDraft, setSearchDraft] = useState(filters.search ?? "");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep draft in sync if parent resets
  useEffect(() => {
    setSearchDraft(filters.search ?? "");
  }, [filters.search]);

  function handleSearchChange(val: string) {
    setSearchDraft(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onFiltersChange({ search: val || undefined, page: 1 });
    }, 300);
  }

  const inputCls =
    "h-9 rounded border border-aq-border bg-aq-surface-raised px-3 text-sm text-aq-text " +
    "placeholder:text-aq-text-dim focus:outline-none focus:ring-1 focus:ring-aq-accent " +
    "focus:border-aq-accent transition-colors";

  const selectCls = `${inputCls} cursor-pointer appearance-none`;

  return (
    <div
      className="flex flex-wrap items-center gap-2 mb-5 px-3 py-2.5 rounded border border-aq-border bg-aq-surface"
      role="search"
      aria-label="Alert filters"
    >
      {/* Search */}
      <input
        type="text"
        placeholder="Search alert or account ID…"
        value={searchDraft}
        onChange={(e) => handleSearchChange(e.target.value)}
        className={`${inputCls} w-52`}
        aria-label="Search alerts"
      />

      {/* Status filter */}
      <select
        value={filters.status ?? ""}
        onChange={(e) =>
          onFiltersChange({
            status: (e.target.value as AlertStatus | "") || undefined,
            page: 1,
          })
        }
        className={`${selectCls} w-40`}
        aria-label="Filter by status"
      >
        {STATUS_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>

      {/* Min risk score */}
      <div className="flex items-center gap-2">
        <label
          className="text-xs text-aq-text-dim whitespace-nowrap"
          htmlFor="filter-min-score"
        >
          Min. risk score
        </label>
        <input
          id="filter-min-score"
          type="number"
          min={0}
          max={1}
          step={0.05}
          placeholder="0.00"
          value={filters.min_score ?? ""}
          onChange={(e) =>
            onFiltersChange({
              min_score: e.target.value ? Number(e.target.value) : undefined,
              page: 1,
            })
          }
          className={`${inputCls} w-20`}
          aria-label="Minimum risk score"
        />
      </div>

      {/* Sort controls — pushed to the right */}
      <div className="flex items-center gap-2 ml-auto">
        <span className="text-xs text-aq-text-dim hidden sm:inline">Sort</span>

        <select
          value={filters.sort_by ?? "risk_score"}
          onChange={(e) =>
            onFiltersChange({
              sort_by: e.target.value as AlertFilters["sort_by"],
              page: 1,
            })
          }
          className={`${selectCls} w-36`}
          aria-label="Sort alerts by"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        {/* Sort direction toggle */}
        <button
          type="button"
          onClick={() =>
            onFiltersChange({
              sort_dir: filters.sort_dir === "asc" ? "desc" : "asc",
              page: 1,
            })
          }
          className={
            "h-9 w-9 flex items-center justify-center rounded border border-aq-border " +
            "bg-aq-surface-raised text-aq-text-dim hover:text-aq-text hover:bg-aq-muted transition-colors"
          }
          aria-label={`Sort ${filters.sort_dir === "asc" ? "descending" : "ascending"}`}
          title={`Currently: ${filters.sort_dir === "asc" ? "ascending" : "descending"}`}
        >
          {filters.sort_dir === "asc" ? (
            <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path d="M8 3.5l-5 9h10L8 3.5z" />
            </svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path d="M8 12.5l5-9H3l5 9z" />
            </svg>
          )}
        </button>

        {/* Reset */}
        <button
          type="button"
          onClick={onReset}
          className={
            "h-9 px-3 rounded border border-aq-border bg-aq-surface-raised " +
            "text-xs text-aq-text-dim hover:text-aq-text hover:bg-aq-muted transition-colors"
          }
        >
          Reset
        </button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ //
// Alert Table                                                          //
// ------------------------------------------------------------------ //

interface AlertTableProps {
  data: AlertListResponse;
  onRowClick: (alertId: string) => void;
}

function AlertTable({ data, onRowClick }: AlertTableProps) {
  if (data.items.length === 0) {
    return (
      <div className="rounded border border-aq-border bg-aq-surface py-16 text-center">
        <p className="text-aq-text-secondary text-sm">
          No alerts match the current filters.
        </p>
        <p className="text-aq-text-dim text-xs mt-1">
          Try adjusting the status or risk score filter.
        </p>
      </div>
    );
  }

  const thCls =
    "px-4 py-3 text-left text-xs font-medium text-aq-text-secondary uppercase tracking-wider whitespace-nowrap bg-aq-surface";

  const tdCls = "px-4 py-3.5 text-sm";

  return (
    <div className="overflow-x-auto rounded border border-aq-border">
      <table
        className="min-w-full divide-y divide-aq-border"
        role="grid"
        aria-label="Alert queue"
      >
        <thead className="sticky top-14 z-10">
          <tr className="divide-x divide-aq-border-subtle">
            <th scope="col" className={`${thCls} w-12`}>#</th>
            <th scope="col" className={thCls}>Alert ID</th>
            <th scope="col" className={thCls}>Account</th>
            <th scope="col" className={thCls}>Rule</th>
            <th scope="col" className={thCls}>Date</th>
            <th scope="col" className={thCls}>Priority</th>
            <th scope="col" className={thCls}>Status</th>
            <th scope="col" className={thCls}>Quality</th>
            <th scope="col" className={thCls}>Assigned</th>
            <th scope="col" className={`${thCls} w-8`} aria-hidden="true" />
          </tr>
        </thead>
        <tbody className="divide-y divide-aq-border bg-aq-navy">
          {data.items.map((alert) => (
            <tr
              key={alert.alert_id}
              aria-label={`#${alert.queue_position}`}
              onClick={() => onRowClick(alert.alert_id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onRowClick(alert.alert_id);
                }
              }}
              className={
                "cursor-pointer hover:bg-aq-surface/70 transition-colors group " +
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-aq-accent"
              }
              role="row"
              tabIndex={0}
            >
              {/* Queue position */}
              <td className={`${tdCls} text-aq-text-dim font-mono tabular-nums text-xs`}>
                #{alert.queue_position}
              </td>

              {/* Alert ID */}
              <td className={tdCls}>
                <span
                  className="font-mono text-xs text-aq-accent group-hover:text-blue-300 transition-colors"
                  title={alert.alert_id}
                >
                  {alert.alert_id.slice(0, 12)}
                  {alert.alert_id.length > 12 && "…"}
                </span>
              </td>

              {/* Account ID */}
              <td className={`${tdCls} font-mono text-xs text-aq-text-secondary`}
                title={alert.account_id}
              >
                {alert.account_id}
              </td>

              {/* Rule — name primary, id secondary */}
              <td className={tdCls}>
                <div
                  className="text-xs font-medium text-aq-text max-w-[11rem] truncate"
                  title={alert.rule_name}
                >
                  {alert.rule_name}
                </div>
                <div className="font-mono text-xs text-aq-text-dim mt-0.5">
                  {alert.rule_id}
                </div>
              </td>

              {/* Alert date */}
              <td className={`${tdCls} text-aq-text-dim text-xs tabular-nums whitespace-nowrap`}>
                {new Date(alert.alert_date).toLocaleDateString("en-GB", {
                  day: "2-digit",
                  month: "short",
                  year: "numeric",
                })}
              </td>

              {/* Priority (risk score) */}
              <td className={tdCls}>
                <RiskBadge score={alert.risk_score} />
              </td>

              {/* Status */}
              <td className={tdCls}>
                <StatusBadge status={alert.status} />
              </td>

              {/* Data quality */}
              <td className={`${tdCls}`}>
                <QualityWarning
                  warning={alert.quality_warning}
                  detail="Data quality issue detected — review features in the detail view"
                />
              </td>

              {/* Assigned to */}
              <td className={`${tdCls} text-xs`}>
                {alert.assigned_to ?? (
                  <span className="text-aq-text-dim">Unassigned</span>
                )}
              </td>

              {/* Row chevron */}
              <td className={`${tdCls} text-aq-text-dim group-hover:text-aq-text-secondary transition-colors text-right pr-3`}
                aria-hidden="true"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M6 4l4 4-4 4" />
                </svg>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------ //
// Pagination Controls                                                  //
// ------------------------------------------------------------------ //

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) return null;

  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  const btnCls = (disabled: boolean) =>
    `h-8 px-3 rounded border text-xs transition-colors tabular-nums ${
      disabled
        ? "border-aq-border text-aq-text-dim/40 cursor-not-allowed"
        : "border-aq-border text-aq-text-dim hover:text-aq-text hover:bg-aq-muted/50 cursor-pointer"
    }`;

  // Build visible page numbers (current ± 2, always show first/last)
  const pages: (number | "…")[] = [];
  const window = 2;
  for (let i = 1; i <= totalPages; i++) {
    if (
      i === 1 ||
      i === totalPages ||
      (i >= page - window && i <= page + window)
    ) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== "…") {
      pages.push("…");
    }
  }

  return (
    <nav
      className="flex items-center justify-between mt-4"
      aria-label="Alert queue pagination"
    >
      <p className="text-xs text-aq-text-dim tabular-nums">
        Showing {from}–{to} of {total} alerts
      </p>

      <div className="flex items-center gap-1">
        <button
          disabled={page === 1}
          onClick={() => onPageChange(page - 1)}
          className={btnCls(page === 1)}
          aria-label="Previous page"
        >
          ← Prev
        </button>

        {pages.map((p, i) =>
          p === "…" ? (
            <span
              key={`ellipsis-${i}`}
              className="px-1 text-aq-text-dim text-xs"
              aria-hidden="true"
            >
              …
            </span>
          ) : (
            <button
              key={p}
              onClick={() => onPageChange(p as number)}
              className={`h-8 w-8 rounded border text-xs transition-colors tabular-nums ${
                p === page
                  ? "border-aq-accent bg-aq-accent/15 text-aq-accent font-medium"
                  : "border-aq-border text-aq-text-dim hover:text-aq-text hover:bg-aq-muted/50"
              }`}
              aria-current={p === page ? "page" : undefined}
              aria-label={`Page ${p}`}
            >
              {p}
            </button>
          ),
        )}

        <button
          disabled={page === totalPages}
          onClick={() => onPageChange(page + 1)}
          className={btnCls(page === totalPages)}
          aria-label="Next page"
        >
          Next →
        </button>
      </div>
    </nav>
  );
}

// ------------------------------------------------------------------ //
// Loading skeleton                                                     //
// ------------------------------------------------------------------ //

function TableSkeleton() {
  return (
    <div className="rounded border border-aq-border overflow-hidden">
      <div className="bg-aq-surface h-10 border-b border-aq-border" />
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="h-14 bg-aq-navy border-b border-aq-border flex items-center px-4 gap-4"
        >
          <div
            className="h-3 rounded bg-aq-surface-raised animate-pulse"
            style={{ width: `${40 + (i * 23) % 60}%`, opacity: 0.6 - i * 0.04 }}
          />
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ //
// Main Client Component                                                //
// ------------------------------------------------------------------ //

const DEFAULT_FILTERS: AlertFilters = {
  sort_by: "risk_score",
  sort_dir: "desc",
  page: 1,
  page_size: PAGE_SIZE,
};

export function AlertQueueClient() {
  const router = useRouter();

  const [stats, setStats] = useState<QueueStats | null>(null);
  const [listData, setListData] = useState<AlertListResponse | null>(null);
  const [filters, setFilters] = useState<AlertFilters>(DEFAULT_FILTERS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch stats once on mount
  useEffect(() => {
    fetchQueueStats()
      .then(setStats)
      .catch((err) => {
        console.error("Failed to load queue stats:", err);
      });
  }, []);

  // Fetch alerts whenever filters change
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchAlerts(filters)
      .then((data) => {
        if (!cancelled) {
          setListData(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err?.message ?? "Failed to load alerts");
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [filters]);

  const handleFiltersChange = useCallback((patch: Partial<AlertFilters>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
  }, []);

  const handleReset = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
  }, []);

  const handleRowClick = useCallback(
    (alertId: string) => {
      router.push(`/alerts/${encodeURIComponent(alertId)}`);
    },
    [router],
  );

  const handlePageChange = useCallback((page: number) => {
    setFilters((prev) => ({ ...prev, page }));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  return (
    <div>
      {/* Capacity strip */}
      {stats && <CapacityBanner stats={stats} />}

      {/* Filter / sort bar */}
      <FilterBar
        filters={filters}
        onFiltersChange={handleFiltersChange}
        onReset={handleReset}
      />

      {/* Results count */}
      {listData && !loading && (
        <p className="text-xs text-aq-text-dim mb-3 tabular-nums">
          {listData.total} alert{listData.total !== 1 ? "s" : ""} found
          {filters.search && (
            <>
              {" "}matching{" "}
              <span className="text-aq-text">"{filters.search}"</span>
            </>
          )}
        </p>
      )}

      {/* Loading state */}
      {loading && <TableSkeleton />}

      {/* Error state */}
      {error && !loading && (
        <div
          className="rounded border border-[var(--status-escalated-border)] bg-[var(--status-escalated-bg)] px-4 py-3 text-sm text-[var(--status-escalated-text)]"
          role="alert"
        >
          <p className="font-medium mb-0.5">Unable to load alerts</p>
          <p className="text-xs opacity-80">{error}</p>
        </div>
      )}

      {/* Table */}
      {!loading && !error && listData && (
        <>
          <AlertTable data={listData} onRowClick={handleRowClick} />
          <Pagination
            page={filters.page ?? 1}
            pageSize={filters.page_size ?? PAGE_SIZE}
            total={listData.total}
            onPageChange={handlePageChange}
          />
        </>
      )}
    </div>
  );
}
