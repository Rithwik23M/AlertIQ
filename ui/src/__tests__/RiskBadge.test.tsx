/**
 * RiskBadge component tests.
 */

import { render, screen } from "@testing-library/react";
import { RiskBadge, getRiskBand } from "@/components/RiskBadge";

describe("getRiskBand", () => {
  it("returns critical for score >= 0.80", () => {
    expect(getRiskBand(0.80)).toBe("critical");
    expect(getRiskBand(0.95)).toBe("critical");
    expect(getRiskBand(1.0)).toBe("critical");
  });

  it("returns high for 0.60 <= score < 0.80", () => {
    expect(getRiskBand(0.60)).toBe("high");
    expect(getRiskBand(0.79)).toBe("high");
  });

  it("returns medium for 0.40 <= score < 0.60", () => {
    expect(getRiskBand(0.40)).toBe("medium");
    expect(getRiskBand(0.59)).toBe("medium");
  });

  it("returns low for 0.20 <= score < 0.40", () => {
    expect(getRiskBand(0.20)).toBe("low");
    expect(getRiskBand(0.39)).toBe("low");
  });

  it("returns minimal for score < 0.20", () => {
    expect(getRiskBand(0.0)).toBe("minimal");
    expect(getRiskBand(0.19)).toBe("minimal");
  });
});

describe("RiskBadge", () => {
  it("renders the band label", () => {
    render(<RiskBadge score={0.85} />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("renders numeric score by default", () => {
    render(<RiskBadge score={0.85} />);
    // score * 100 = 85, toFixed(0) = "85"
    expect(screen.getByText("85")).toBeInTheDocument();
  });

  it("hides score when showScore=false", () => {
    render(<RiskBadge score={0.85} showScore={false} />);
    expect(screen.queryByText("85")).not.toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("renders high band for 0.70", () => {
    render(<RiskBadge score={0.70} />);
    expect(screen.getByText("High")).toBeInTheDocument();
  });

  it("includes tooltip with full precision score", () => {
    const { container } = render(<RiskBadge score={0.854} />);
    const badge = container.querySelector("[title]");
    expect(badge).toBeTruthy();
    expect(badge?.getAttribute("title")).toContain("85.4%");
  });
});
