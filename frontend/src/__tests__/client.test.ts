import { afterEach, describe, expect, it, vi } from "vitest";
import { analyze } from "../api/client";

describe("api client - analyze()", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs to /api/analyze with pr_url and github_token when a token is provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({ task_id: "task-123" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await analyze("https://github.com/owner/repo/pull/42", "ghp_secret");

    expect(result).toEqual({ task_id: "task-123" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/analyze");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      pr_url: "https://github.com/owner/repo/pull/42",
      github_token: "ghp_secret",
    });
  });

  it("omits github_token from the request body when no token is provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({ task_id: "task-456" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await analyze("https://github.com/owner/repo/pull/7");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ pr_url: "https://github.com/owner/repo/pull/7" });
    expect(body).not.toHaveProperty("github_token");
  });
});
