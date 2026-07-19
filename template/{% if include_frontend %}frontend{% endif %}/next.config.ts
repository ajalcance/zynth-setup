import type { NextConfig } from "next";

/**
 * Baseline security headers.
 *
 * The backend module ships fail-closed config and a hardened runtime; a browser app with no
 * headers is the weakest link in the same system. Each header below is either inert when
 * unused or blocks a real attack class.
 *
 * Two deliberate omissions, because a wrong default is worse than an absent one:
 *
 * - **COEP (`Cross-Origin-Embedder-Policy: require-corp`) is NOT set.** It breaks every
 *   cross-origin image, font and embed that does not opt in, and buys nothing unless you need
 *   cross-origin isolation (SharedArrayBuffer / high-resolution timers). Enable it deliberately.
 * - **`script-src` still allows `'unsafe-inline'`**, which Next's bootstrap requires without a
 *   nonce. Removing it means adding middleware that mints a per-request nonce and threads it
 *   through — worth doing before this app handles sensitive data, but that is a real change,
 *   not a config tweak. Called out in docs/CODING_STANDARDS.md rather than silently pretended.
 */
const isDev = process.env.NODE_ENV === "development";

const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  // 'unsafe-eval' is required by React Fast Refresh in dev only — never in a production build.
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "connect-src 'self'",
  "upgrade-insecure-requests",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  // Ignored over plain HTTP, so it is inert in local dev and correct behind TLS in production.
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
];

const nextConfig: NextConfig = {
  poweredByHeader: false, // don't advertise the framework/version
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
