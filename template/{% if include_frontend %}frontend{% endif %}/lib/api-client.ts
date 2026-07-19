/**
 * Typed HTTP client for the backend API.
 *
 * The backend enforces a consistent error contract; this is the browser half of it. Using
 * `fetch` directly at each call site is how a codebase ends up with a dozen slightly different
 * error-handling behaviours and no timeouts.
 *
 * Contract:
 *  - Non-2xx  -> throws `ApiError` (status + parsed body when JSON).
 *  - Timeout / network failure -> throws `ApiError` with status 0.
 *  - Retries **only idempotent methods** (GET/HEAD) and only on timeout, network failure, 429
 *    or 5xx. Retrying a POST is how you get duplicate writes, so it never happens implicitly —
 *    if a mutation is safe to retry, make it idempotent and call `request` again yourself.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  /** True when retrying the same request could plausibly succeed. */
  get isRetryable(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  /** JSON-serialisable request body. Sets Content-Type automatically. */
  json?: unknown;
  /** Abort after this many ms (default 10000). */
  timeoutMs?: number;
  /** Extra attempts for idempotent requests only (default 2, so 3 attempts total). */
  retries?: number;
}

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const IDEMPOTENT = new Set(["GET", "HEAD"]);

function backoffMs(attempt: number): number {
  // 200ms, 400ms, 800ms... with jitter, so retries don't align across clients.
  return 2 ** attempt * 200 + Math.random() * 100;
}

async function once<T>(path: string, options: RequestOptions): Promise<T> {
  const {
    json,
    timeoutMs = 10_000,
    retries: _retries,
    headers,
    ...init
  } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      ...(json !== undefined ? { body: JSON.stringify(json) } : {}),
    });

    const isJson =
      response.headers.get("content-type")?.includes("application/json") ??
      false;
    const body: unknown = isJson
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      throw new ApiError(
        `${response.status} ${response.statusText}`,
        response.status,
        body,
      );
    }
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const reason =
      error instanceof Error && error.name === "AbortError"
        ? "timeout"
        : "network";
    throw new ApiError(`Request failed (${reason}): ${path}`, 0);
  } finally {
    clearTimeout(timer);
  }
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const attempts = IDEMPOTENT.has(method) ? (options.retries ?? 2) + 1 : 1;

  let lastError: ApiError | undefined;
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await once<T>(path, options);
    } catch (error) {
      lastError = error as ApiError;
      if (!lastError.isRetryable || attempt === attempts - 1) throw lastError;
      await new Promise((resolve) => setTimeout(resolve, backoffMs(attempt)));
    }
  }
  throw lastError as ApiError;
}

export const apiClient = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, json?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", json }),
  put: <T>(path: string, json?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PUT", json }),
  patch: <T>(path: string, json?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PATCH", json }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "DELETE" }),
};
