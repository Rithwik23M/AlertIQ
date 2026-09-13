/**
 * StatusBadge — displays an alert investigation status.
 */

import type { AlertStatus } from "@/lib/types";

const STATUS_STYLE: Record<AlertStatus, string> = {
  new:
    "bg-[var(--status-new-bg)] text-[var(--status-new-text)] border border-[var(--status-new-border)]",
  in_progress:
    "bg-[var(--status-progress-bg)] text-[var(--status-progress-text)] border border-[var(--status-progress-border)]",
  escalated:
    "bg-[var(--status-escalated-bg)] text-[var(--status-escalated-text)] border border-[var(--status-escalated-border)]",
  closed:
    "bg-[var(--status-closed-bg)] text-[var(--status-closed-text)] border border-[var(--status-closed-border)]",
  needs_further_review:
    "bg-[var(--status-review-bg)] text-[var(--status-review-text)] border border-[var(--status-review-border)]",
};

const STATUS_LABEL: Record<AlertStatus, string> = {
  new:                  "New",
  in_progress:          "In Progress",
  escalated:            "Escalated",
  closed:               "Closed",
  needs_further_review: "Needs Review",
};

interface StatusBadgeProps {
  status: AlertStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium leading-4 ${STATUS_STYLE[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}
