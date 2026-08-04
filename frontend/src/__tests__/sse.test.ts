import { afterEach, describe, expect, it, vi } from "vitest";
import { subscribeTask } from "../api/sse";

/** Minimal EventSource stand-in for jsdom (which has no native EventSource). */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close(): void {}
}

describe("subscribeTask - terminal handling on connection error", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    FakeEventSource.instances = [];
  });

  it("treats a 404 task-state fetch (unknown/evicted task) as terminal and does not reconnect", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404 });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", FakeEventSource);

    const onError = vi.fn();
    const onStage = vi.fn();
    const unsubscribe = subscribeTask("task-evicted", { onError, onStage });

    expect(FakeEventSource.instances).toHaveLength(1);

    // Simulate the connection dropping; the client then probes task state.
    FakeEventSource.instances[0].onerror?.(new Event("error"));

    await vi.waitFor(() => {
      expect(onError).toHaveBeenCalledWith("not_found", "task not found");
    });
    expect(onStage).not.toHaveBeenCalled();
    // No reconnect: only the first EventSource was ever created.
    expect(FakeEventSource.instances).toHaveLength(1);
    unsubscribe();
  });
});
