/**
 * AlertIQ — Alert Queue Page (Home)
 *
 * Displays the paginated, filterable alert queue with a capacity strip
 * showing how many alerts are in the top-20% priority band.
 *
 * This is a Server Component. Client-side filtering is handled by AlertQueueClient.
 */

import { Suspense } from "react";
import { AlertQueueClient } from "./AlertQueueClient";

export const dynamic = "force-dynamic"; // Always fetch fresh data

export default async function HomePage() {
  return (
    <div>
      {/* Page header */}
      <div className="mb-5">
        <h1 className="text-lg font-semibold text-aq-text tracking-tight">
          Alert Queue
        </h1>
        <p className="text-sm text-aq-text-secondary mt-0.5">
          Prioritised investigation workload
          <span className="mx-2 text-aq-border" aria-hidden="true">·</span>
          <span className="text-aq-text-dim">Capacity policy: Top 20%</span>
        </p>
      </div>

      <Suspense
        fallback={
          <div className="text-aq-text-dim text-sm py-12 text-center">
            Loading alert queue…
          </div>
        }
      >
        <AlertQueueClient />
      </Suspense>
    </div>
  );
}
