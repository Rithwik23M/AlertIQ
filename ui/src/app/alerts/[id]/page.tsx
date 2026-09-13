/**
 * AlertIQ — Investigation Workspace Page
 *
 * Server Component shell that resolves the alert ID from the route params
 * and renders the client-side investigation workspace.
 */

import { Suspense } from "react";
import { AlertDetailClient } from "./AlertDetailClient";

interface Props {
  params: { id: string };
}

export default function AlertDetailPage({ params }: Props) {
  const alertId = decodeURIComponent(params.id);

  return (
    <Suspense
      fallback={
        <div className="text-aq-text-dim text-sm py-16 text-center animate-pulse">
          Loading investigation workspace…
        </div>
      }
    >
      <AlertDetailClient alertId={alertId} />
    </Suspense>
  );
}
