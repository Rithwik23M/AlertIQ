/**
 * QualityWarning — small inline indicator shown when an alert's feature
 * vector has data quality issues (zeroed or extreme values).
 *
 * This is a passive informational signal, never a block on analyst action.
 */

interface QualityWarningProps {
  warning: boolean;
  /** Optional tooltip detail, e.g. zero feature names */
  detail?: string;
}

export function QualityWarning({ warning, detail }: QualityWarningProps) {
  if (!warning) return null;
  return (
    <span
      className="inline-flex items-center gap-1 text-amber-500/75 text-xs"
      title={detail ?? "Data quality warning — one or more features may be unreliable"}
    >
      <svg
        width="11"
        height="11"
        viewBox="0 0 16 16"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0 1 14.082 15H1.918a1.75 1.75 0 0 1-1.543-2.575zm1.763.707a.25.25 0 0 0-.44 0L1.698 13.132a.25.25 0 0 0 .22.368h12.164a.25.25 0 0 0 .22-.368zm.53 3.996v2.5a.75.75 0 0 1-1.5 0v-2.5a.75.75 0 0 1 1.5 0M9 11a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
      </svg>
      Data issue
    </span>
  );
}
