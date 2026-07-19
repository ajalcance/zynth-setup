import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient, request } from "../lib/api-client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("api-client", () => {
  it("returns the parsed JSON body on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ status: "ok" })),
    );
    await expect(apiClient.get<{ status: string }>("/health")).resolves.toEqual(
      { status: "ok" },
    );
  });

  it("throws ApiError carrying the status and body on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "nope" }, 422)),
    );
    const error = await apiClient.get("/thing").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).body).toEqual({ detail: "nope" });
  });

  it("retries an idempotent GET on a 5xx and succeeds", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "boom" }, 503))
      .mockResolvedValueOnce(jsonResponse({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(request("/health", { retries: 1 })).resolves.toEqual({
      status: "ok",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does NOT retry a POST — a duplicate write is worse than a failure", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ detail: "boom" }, 503));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiClient.post("/things", { a: 1 })).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not retry a non-retryable status such as 404", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ detail: "missing" }, 404),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiClient.get("/missing")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
