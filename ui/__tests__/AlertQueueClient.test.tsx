/**
 * AlertQueueClient integration-style tests.
 *
 * Mocks the API module so tests run without a backend.
 * Verifies: capacity strip rendering, alert table, empty state,
 * error state, filter changes, and row click navigation.
 */

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useRouter } from "next/navigation";
import { AlertQueueClient } from "@/app/AlertQueueClient";
import { fetchAlerts, fetchQueueStats } from "@/lib/api";
import type { AlertListResponse, AlertSummary, QueueStats } from "@/lib/types";

// Mock Next.js router
jest.mock("next/navigation", () => ({
  useRouter: jest.fn(),
}));

// Mock API module
jest.mock("@/lib/api", () => ({
  fetchAlerts: jest.fn(),
  fetchQueueStats: jest.fn(),
}));

const mockPush = jest.fn();
const mockFetchAlerts = fetchAlerts as jest.MockedFunction<typeof fetchAlerts>;
const mockFetchStats = fetchQueueStats as jest.MockedFunction<typeof fetchQueueStats>;

// ------------------------------------------------------------------ //
// Fixtures                                                             //
// ------------------------------------------------------------------ //

const MOCK_STATS: QueueStats = {
  total_alerts: 500,
  capacity_fraction: 0.2,
  capacity_count: 100,
  status_counts: {
    new: 60,
    in_progress: 20,
    escalated: 5,
    closed: 10,
    needs_further_review: 5,
  },
};

function makeAlert(overrides: Partial<AlertSummary> = {}): AlertSummary {
  return {
    alert_id: "ALRT-0001",
    account_id: "ACC-001",
    rule_id: "R001",
    rule_name: "High Cash Transactions",
    severity: "high",
    alert_date: "2023-01-15",
    risk_score: 0.92,
    queue_position: 1,
    status: "new",
    assigned_to: null,
    quality_warning: false,
    model_version: "v1.2.3",
    ...overrides,
  };
}

function makeListResponse(
  items: AlertSummary[],
  total?: number,
): AlertListResponse {
  return {
    total: total ?? items.length,
    page: 1,
    page_size: 25,
    items,
  };
}

// ------------------------------------------------------------------ //
// Setup / Teardown                                                     //
// ------------------------------------------------------------------ //

beforeEach(() => {
  (useRouter as jest.Mock).mockReturnValue({ push: mockPush });
  mockFetchStats.mockResolvedValue(MOCK_STATS);
  mockFetchAlerts.mockResolvedValue(makeListResponse([makeAlert()]));
  mockPush.mockReset();
});

afterEach(() => {
  jest.clearAllMocks();
});

// ------------------------------------------------------------------ //
// Capacity strip                                                       //
// ------------------------------------------------------------------ //

describe("Capacity Banner", () => {
  it("shows capacity count and total", async () => {
    render(<AlertQueueClient />);
    await waitFor(() => {
      expect(screen.getByText("100")).toBeInTheDocument();
    });
    expect(screen.getByText(/of 500 alerts/)).toBeInTheDocument();
  });

  it("shows status counts from stats", async () => {
    render(<AlertQueueClient />);
    await waitFor(() => screen.getByText("100"));
    // New: 60
    expect(screen.getByText("60")).toBeInTheDocument();
    // Escalated: 5 (appears at least twice across different badges, use getAllByText)
    const fives = screen.getAllByText("5");
    expect(fives.length).toBeGreaterThanOrEqual(1);
  });

  it("does not crash when stats are still loading", () => {
    // Delay the stats fetch — strip should just not render yet
    mockFetchStats.mockReturnValue(new Promise(() => {}));
    render(<AlertQueueClient />);
    expect(screen.queryByText(/Review Capacity/)).not.toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ //
// Alert table                                                          //
// ------------------------------------------------------------------ //

describe("Alert Table", () => {
  it("renders alert rows after loading", async () => {
    const alert = makeAlert({ alert_id: "ALRT-ABCD1234", account_id: "ACC-999" });
    mockFetchAlerts.mockResolvedValue(makeListResponse([alert]));
    render(<AlertQueueClient />);
    await waitFor(() => {
      // Alert ID is truncated to first 12 chars
      expect(screen.getByText(/ALRT-ABC/)).toBeInTheDocument();
    });
    expect(screen.getByText("ACC-999")).toBeInTheDocument();
  });

  it("shows risk badge", async () => {
    const alert = makeAlert({ risk_score: 0.92 });
    mockFetchAlerts.mockResolvedValue(makeListResponse([alert]));
    render(<AlertQueueClient />);
    await waitFor(() => {
      expect(screen.getByText("Critical")).toBeInTheDocument();
    });
  });

  it("shows status badge", async () => {
    const alert = makeAlert({ status: "escalated" });
    mockFetchAlerts.mockResolvedValue(makeListResponse([alert]));
    render(<AlertQueueClient />);
    await waitFor(() => {
      expect(screen.getByText("Escalated")).toBeInTheDocument();
    });
  });

  it("shows Data issue warning when quality_warning=true", async () => {
    const alert = makeAlert({ quality_warning: true });
    mockFetchAlerts.mockResolvedValue(makeListResponse([alert]));
    render(<AlertQueueClient />);
    await waitFor(() => {
      expect(screen.getByText("Data issue")).toBeInTheDocument();
    });
  });

  it("does not show Data issue warning when quality_warning=false", async () => {
    const alert = makeAlert({ quality_warning: false });
    mockFetchAlerts.mockResolvedValue(makeListResponse([alert]));
    render(<AlertQueueClient />);
    await waitFor(() => {
      // Table should be visible
      expect(screen.getByText(/ALRT/)).toBeInTheDocument();
    });
    expect(screen.queryByText("Data issue")).not.toBeInTheDocument();
  });

  it("shows 'Unassigned' for null assigned_to", async () => {
    const alert = makeAlert({ assigned_to: null });
    mockFetchAlerts.mockResolvedValue(makeListResponse([alert]));
    render(<AlertQueueClient />);
    await waitFor(() => {
      expect(screen.getByText("Unassigned")).toBeInTheDocument();
    });
  });

  it("navigates to alert detail on row click", async () => {
    const alert = makeAlert({ alert_id: "ALRT-CLICK001" });
    mockFetchAlerts.mockResolvedValue(makeListResponse([alert]));
    render(<AlertQueueClient />);
    await waitFor(() => screen.getByText(/ALRT-CLI/));

    const row = screen.getByRole("row", { name: /#1/ });
    fireEvent.click(row);
    expect(mockPush).toHaveBeenCalledWith(
      `/alerts/${encodeURIComponent("ALRT-CLICK001")}`,
    );
  });

  it("navigates on Enter key", async () => {
    const alert = makeAlert({ alert_id: "ALRT-KEYTEST" });
    mockFetchAlerts.mockResolvedValue(makeListResponse([alert]));
    render(<AlertQueueClient />);
    await waitFor(() => screen.getByText(/ALRT-KEY/));
    const row = screen.getByRole("row", { name: /#1/ });
    fireEvent.keyDown(row, { key: "Enter" });
    expect(mockPush).toHaveBeenCalledWith(
      `/alerts/${encodeURIComponent("ALRT-KEYTEST")}`,
    );
  });
});

// ------------------------------------------------------------------ //
// Empty state                                                          //
// ------------------------------------------------------------------ //

describe("Empty state", () => {
  it("shows empty message when no alerts returned", async () => {
    mockFetchAlerts.mockResolvedValue(makeListResponse([], 0));
    render(<AlertQueueClient />);
    await waitFor(() => {
      expect(
        screen.getByText(/No alerts match the current filters/),
      ).toBeInTheDocument();
    });
  });
});

// ------------------------------------------------------------------ //
// Error state                                                          //
// ------------------------------------------------------------------ //

describe("Error state", () => {
  it("shows error message when fetch fails", async () => {
    mockFetchAlerts.mockRejectedValue(new Error("Network failure"));
    render(<AlertQueueClient />);
    await waitFor(() => {
      expect(screen.getByText(/Network failure/)).toBeInTheDocument();
    });
  });

  it("shows generic error when no message", async () => {
    mockFetchAlerts.mockRejectedValue({});
    render(<AlertQueueClient />);
    await waitFor(() => {
      expect(screen.getByText(/Failed to load alerts/)).toBeInTheDocument();
    });
  });
});

// ------------------------------------------------------------------ //
// Filter controls                                                      //
// ------------------------------------------------------------------ //

describe("Filter controls", () => {
  it("refetches with status filter when status changes", async () => {
    render(<AlertQueueClient />);
    await waitFor(() => screen.getByRole("combobox", { name: /Filter by status/ }));

    fireEvent.change(
      screen.getByRole("combobox", { name: /Filter by status/ }),
      { target: { value: "escalated" } },
    );

    await waitFor(() => {
      const lastCall = mockFetchAlerts.mock.calls.at(-1)?.[0];
      expect(lastCall?.status).toBe("escalated");
    });
  });

  it("resets filters on Reset button click", async () => {
    render(<AlertQueueClient />);
    await waitFor(() => screen.getByRole("button", { name: /Reset/ }));

    // Set a status filter first
    fireEvent.change(
      screen.getByRole("combobox", { name: /Filter by status/ }),
      { target: { value: "closed" } },
    );

    await waitFor(() => {
      const call = mockFetchAlerts.mock.calls.at(-1)?.[0];
      expect(call?.status).toBe("closed");
    });

    fireEvent.click(screen.getByRole("button", { name: /Reset/ }));

    await waitFor(() => {
      const lastCall = mockFetchAlerts.mock.calls.at(-1)?.[0];
      expect(lastCall?.status).toBeUndefined();
    });
  });

  it("sorts descending by default", async () => {
    render(<AlertQueueClient />);
    await waitFor(() => screen.getByLabelText(/Sort alerts by/));
    const initialCall = mockFetchAlerts.mock.calls[0]?.[0];
    expect(initialCall?.sort_dir).toBe("desc");
    expect(initialCall?.sort_by).toBe("risk_score");
  });

  it("toggles sort direction", async () => {
    render(<AlertQueueClient />);
    await waitFor(() =>
      screen.getByRole("button", { name: /Sort (ascending|descending)/ }),
    );
    const toggleBtn = screen.getByRole("button", { name: /Sort/ });
    fireEvent.click(toggleBtn);
    await waitFor(() => {
      const lastCall = mockFetchAlerts.mock.calls.at(-1)?.[0];
      expect(lastCall?.sort_dir).toBe("asc");
    });
  });
});

// ------------------------------------------------------------------ //
// Results count                                                        //
// ------------------------------------------------------------------ //

describe("Results count", () => {
  it("shows total count after load", async () => {
    const items = [makeAlert(), makeAlert({ alert_id: "ALRT-0002", queue_position: 2 })];
    mockFetchAlerts.mockResolvedValue(makeListResponse(items, 42));
    render(<AlertQueueClient />);
    await waitFor(() => {
      expect(screen.getByText(/42 alerts found/)).toBeInTheDocument();
    });
  });

  it("shows singular 'alert' for count of 1", async () => {
    mockFetchAlerts.mockResolvedValue(makeListResponse([makeAlert()], 1));
    render(<AlertQueueClient />);
    await waitFor(() => {
      expect(screen.getByText(/1 alert found/)).toBeInTheDocument();
    });
  });
});
