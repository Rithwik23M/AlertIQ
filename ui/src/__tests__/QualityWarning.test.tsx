/**
 * QualityWarning component tests.
 */

import { render, screen } from "@testing-library/react";
import { QualityWarning } from "@/components/QualityWarning";

describe("QualityWarning", () => {
  it("renders nothing when warning=false", () => {
    const { container } = render(<QualityWarning warning={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders DQ indicator when warning=true", () => {
    render(<QualityWarning warning={true} />);
    expect(screen.getByText("DQ")).toBeInTheDocument();
  });

  it("uses default tooltip when no detail provided", () => {
    const { container } = render(<QualityWarning warning={true} />);
    const el = container.querySelector("[title]");
    expect(el?.getAttribute("title")).toContain("Data quality warning");
  });

  it("uses custom detail as tooltip when provided", () => {
    const detail = "Zeroed features: txn_count_7d, txn_volume_30d";
    const { container } = render(<QualityWarning warning={true} detail={detail} />);
    const el = container.querySelector("[title]");
    expect(el?.getAttribute("title")).toBe(detail);
  });

  it("applies amber colour class", () => {
    const { container } = render(<QualityWarning warning={true} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("amber");
  });
});
