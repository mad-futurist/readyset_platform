import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";

describe("API transport security context", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "rs_csrf=csrf-value; path=/";
  });

  it("propagates organization and CSRF headers for mutations", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: crypto.randomUUID(), name: "Renamed", slug: "renamed" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await api.updateOrganization("org-context", "Renamed");

    const init = fetchMock.mock.calls[0][1];
    const headers = new Headers(init?.headers);
    expect(headers.get("X-ReadySet-Organization")).toBe("org-context");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-value");
    expect(init?.credentials).toBe("include");
  });

  it("sends multipart document uploads without overriding the content type", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: crypto.randomUUID() }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const form = new FormData();
    form.set("title", "Policy");
    form.set("file", new File(["policy"], "policy.txt", { type: "text/plain" }));
    await api.uploadDocument("org-upload", form);

    const init = fetchMock.mock.calls[0][1];
    const headers = new Headers(init?.headers);
    expect(init?.body).toBe(form);
    expect(headers.get("Content-Type")).toBeNull();
    expect(headers.get("X-ReadySet-Organization")).toBe("org-upload");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-value");
  });

  it("surfaces authorization failures as typed API errors", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "http_403", message: "Insufficient permission" } }),
        { status: 403, headers: { "Content-Type": "application/json" } },
      ),
    );
    await expect(api.people("org-denied")).rejects.toMatchObject({
      status: 403,
      message: "Insufficient permission",
    });
  });
});
