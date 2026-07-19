"use client";

import { useEffect } from "react";

/**
 * Route-level error boundary (Next App Router convention).
 *
 * Fault isolation: without this, one throwing component blanks the whole page. Next renders
 * this instead, and the rest of the app keeps working. Add a nested error.tsx inside any route
 * segment that should fail independently of its siblings.
 *
 * Deliberately does NOT render `error.message` — an unhandled error can carry internal detail
 * (a query fragment, an upstream URL), and the browser is the wrong place to disclose it. The
 * digest is Next's stable id for correlating with the server log.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Replace with your telemetry sink; console keeps it visible without inventing a dependency.
    console.error("Unhandled route error", { digest: error.digest });
  }, [error]);

  return (
    <main>
      <h1>Something went wrong</h1>
      <p>
        This section failed to load. The rest of the app is still available.
      </p>
      {error.digest ? <p>Reference: {error.digest}</p> : null}
      <button type="button" onClick={reset}>
        Try again
      </button>
    </main>
  );
}
