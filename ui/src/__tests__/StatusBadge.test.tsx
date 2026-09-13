/**
 * StatusBadge component tests.
 */

import { render, screen } from "@testing-library/react";
import { StatusBadge } from "@/components/StatusBadge";
import type { AlertStatus } from "@/lib/types";

const CASES: { status: AlertStatus; label: string }[] = [
  { status: "new", label: "New" },
  { status: "in_progress", label: "In Progress" },
  { status: "escalated", label: "Escalated" },
  { status: "closed", label: "Closed" },
  { status: "needs_further_review", label: "Needs Review" },
];

describe("StatusBadge", () => {
  it.each(CASES)(
    "renders correct label for status '$status'",
    ({ status, label }) => {
      render(<StatusBadge status={status} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    },
  );

  it("renders as an inline element", () => {
    const { container } = render(<StatusBadge status="new" />);
    const el = container.querySelector("span");
    expect(el).toBeInTheDocument();
  });
});
