/**
 * API client unit tests.
 *
 * Uses fetch mocking to verify that each function:
 *   1. Calls the correct path
 *   2. Returns the parsed response on success
 *   3. Throws ApiError on HTTP error
 */

import { ApiError, fetchAlerts, fetchAlert, fetchQueueStats } from "@/lib/api";

const mockFetch = jest.fn();
global.fetch = mockFetch;

function ok(body: unknown) {
  return {
    ok: true,
    json: () => Promise.resolve(body),
  };
}

function fail(status: number, body: unknown = {}) {
  return {
    ok: false,
    status,
    json: () => Promise.resolve(body),
  };
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe("fetchQueueStats", () => {
  it("calls /api/queue/stats", async () => {
    const stats = { total_alerts: 500, capacity_fraction: 0.2, capacity_count: 100, status_counts: {} };
    mockFetch.mockResolvedValue(ok(stats));
    const result = await fetchQueueStats();
    expect(mockFetch).toHaveBeenCalledWith("/api/queue/stats", expect.any(Object));
    expect(result.total_alerts).toBe(500);
    expect(result.capacity_count).toBe(100);
  });

  it("throws ApiError on 503", async () => {
    mockFetch.mockResolvedValue(fail(503, { error: "service unavailable" }));
    await expect(fetchQueueStats()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchAlerts", () => {
  it("calls /api/alerts with no query string when no filters", async () => {
    const resp = { total: 10, page: 1, page_size: 25, items: [] };
    mockFetch.mockResolvedValue(ok(resp));
    await fetchAlerts();
    const [url] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/alerts");
  });

  it("builds query string from filters", async () => {
    mockFetch.mockResolvedValue(ok({ total: 0, page: 1, page_size: 25, items: [] }));
    await fetchAlerts({ status: "new", sort_by: "risk_score", page: 2 });
    const [url] = mockFetch.mock.calls[0];
    expect(url).toContain("status=new");
    expect(url).toContain("sort_by=risk_score");
    expect(url).toContain("page=2");
  });

  it("omits empty-string and undefined filter values", async () => {
    mockFetch.mockResolvedValue(ok({ total: 0, page: 1, page_size: 25, items: [] }));
    await fetchAlerts({ status: "", rule_id: undefined });
    const [url] = mockFetch.mock.calls[0];
    expect(url).not.toContain("status");
    expect(url).not.toContain("rule_id");
  });

  it("throws ApiError on 404", async () => {
    mockFetch.mockResolvedValue(fail(404, { error: "not found" }));
    await expect(fetchAlerts()).rejects.toBeInstanceOf(ApiError);
    await expect(fetchAlerts()).rejects.toMatchObject({ status: 404 });
  });
});

describe("fetchAlert", () => {
  it("URL-encodes the alert ID", async () => {
    const detail = {
      alert_id: "ALRT-001/x",
      account_id: "ACC-1",
      rule_id: "R001",
      rule_name: "High Cash",
      severity: "high",
      alert_date: "2023-01-01",
      risk_score: 0.9,
      queue_position: 1,
      status: "new",
      assigned_to: null,
      quality_warning: false,
      model_version: "v1",
      schema_version: 1,
      scored_at: "2023-01-01T00:00:00",
      features: {},
      quality_flags: {
        has_zeroed_features: false,
        zero_feature_names: [],
        has_extreme_values: false,
        extreme_feature_names: [],
        quality_warning: false,
      },
      explainability_signals: [],
    };
    mockFetch.mockResolvedValue(ok(detail));
    await fetchAlert("ALRT-001/x");
    const [url] = mockFetch.mock.calls[0];
    expect(url).toContain("ALRT-001%2Fx");
  });

  it("returns parsed AlertDetail", async () => {
    const detail = {
      alert_id: "ALRT-001",
      risk_score: 0.85,
      explainability_signals: [
        { feature: "txn_count_7d", label: "7-day Txn Count", value: 42, display_value: "42", notable: true, flag: "high" },
      ],
      quality_flags: { has_zeroed_features: false, zero_feature_names: [], has_extreme_values: false, extreme_feature_names: [], quality_warning: false },
    };
    mockFetch.mockResolvedValue(ok(detail));
    const result = await fetchAlert("ALRT-001");
    expect(result.risk_score).toBe(0.85);
    expect(result.explainability_signals).toHaveLength(1);
  });
});

describe("ApiError", () => {
  it("has status and body properties", async () => {
    mockFetch.mockResolvedValue(fail(422, { error: "Validation failed", field: "outcome" }));
    try {
      await fetchAlerts();
      fail("should have thrown");
    } catch (err) {
      if (err instanceof ApiError) {
        expect(err.status).toBe(422);
        expect(err.body).toMatchObject({ error: "Validation failed" });
        expect(err.message).toBe("Validation failed");
      } else {
        throw err;
      }
    }
  });
});
