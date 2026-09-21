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

/**
 * Build engine: this app builds with WEBPACK, pinned in package.json (`next build --webpack`),
 * not with Next 16's default Turbopack.
 *
 * The reason is the container image. `frontend/Dockerfile` runs `npm run build`, and CI builds
 * that image for linux/arm64 under QEMU emulation. A Turbopack build wedged there — 33 minutes
 * against a 3-minute baseline, with no timeout to stop it — while being perfectly fast natively.
 * Pinning the engine in package.json rather than in the Dockerfile is deliberate: the gate and
 * the image then run the SAME command, so the thing tested is the thing that ships. Splitting
 * them is how a build passes the gate and fails in the registry.
 *
 * docs-site keeps the default: it has no Dockerfile, so it never builds under emulation.
 */
const nextConfig: NextConfig = {
  poweredByHeader: false, // don't advertise the framework/version
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
