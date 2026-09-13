/**
 * RiskBadge — displays a numeric risk score as a coloured priority band badge.
 *
 * Uses the AlertIQ five-band taxonomy:
 *   ≥ 0.80  critical  (highest)
 *   ≥ 0.60  high
 *   ≥ 0.40  medium
 *   ≥ 0.20  low
 *   < 0.20  minimal
 *
 * The priority label ("Critical") is in UI font.
 * Only the numeric score is rendered in monospace.
 */

import type { RiskBand } from "@/lib/types";

export function getRiskBand(score: number): RiskBand {
  if (score >= 0.8) return "critical";
  if (score >= 0.6) return "high";
  if (score >= 0.4) return "medium";
  if (score >= 0.2) return "low";
  return "minimal";
}

const BAND_STYLE: Record<RiskBand, string> = {
  critical:
    "bg-[var(--risk-critical-bg)] text-[var(--risk-critical-text)] border border-[var(--risk-critical-border)]",
  high:
    "bg-[var(--risk-high-bg)] text-[var(--risk-high-text)] border border-[var(--risk-high-border)]",
  medium:
    "bg-[var(--risk-medium-bg)] text-[var(--risk-medium-text)] border border-[var(--risk-medium-border)]",
  low:
    "bg-[var(--risk-low-bg)] text-[var(--risk-low-text)] border border-[var(--risk-low-border)]",
  minimal:
    "bg-[var(--risk-minimal-bg)] text-[var(--risk-minimal-text)] border border-[var(--risk-minimal-border)]",
};

const BAND_LABEL: Record<RiskBand, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  minimal: "Minimal",
};

interface RiskBadgeProps {
  score: number;
  showScore?: boolean;
  size?: "sm" | "md";
}

export function RiskBadge({
  score,
  showScore = true,
  size = "sm",
}: RiskBadgeProps) {
  const band = getRiskBand(score);
  const px = size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded font-medium ${px} ${BAND_STYLE[band]}`}
      title={`Risk score: ${(score * 100).toFixed(1)}%`}
    >
      {BAND_LABEL[band]}
      {showScore && (
        <>
          <span className="opacity-40 select-none">·</span>
          <span className="font-mono tabular-nums">{(score * 100).toFixed(0)}</span>
        </>
      )}
    </span>
  );
}
