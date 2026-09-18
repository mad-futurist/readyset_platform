import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  me: vi.fn(),
  memberships: vi.fn(),
  documents: vi.fn(),
  people: vi.fn(),
  teams: vi.fn(),
  members: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@/lib/api", () => {
  class MockApiError extends Error {
    constructor(message: string, public status: number) {
      super(message);
    }
  }
  return {
    ApiError: MockApiError,
    api: {
      ...mocks,
      createOrganization: vi.fn(),
      updateOrganization: vi.fn(),
      invite: vi.fn(),
      createPerson: vi.fn(),
      createTeam: vi.fn(),
      uploadDocument: vi.fn(),
      versions: vi.fn(),
      download: vi.fn(),
    },
  };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));

import { ApiError } from "@/lib/api";
import WorkspacePage from "./page";

function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WorkspacePage />
    </QueryClientProvider>,
  );
}

const firstOrganization = "11111111-1111-4111-8111-111111111111";
const secondOrganization = "22222222-2222-4222-8222-222222222222";

describe("Workspace session and organization context", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
  });

  it("redirects an unauthenticated browser to sign in", async () => {
    mocks.me.mockRejectedValue(new ApiError("Authentication required", 401));
    renderWorkspace();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/signin"));
  });

  it("switches organization context and reloads tenant data", async () => {
    mocks.me.mockResolvedValue({
      user: {
        id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        primary_email: "owner@example.com",
        display_name: "Owner",
        avatar_url: null,
      },
      memberships: [],
      csrf_token: "csrf",
    });
    mocks.memberships.mockResolvedValue([
      {
        id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        organization_id: firstOrganization,
        user_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        role: "OWNER",
        status: "ACTIVE",
        organization: { id: firstOrganization, name: "First", slug: "first" },
      },
      {
        id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        organization_id: secondOrganization,
        user_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        role: "ADMIN",
        status: "ACTIVE",
        organization: { id: secondOrganization, name: "Second", slug: "second" },
      },
    ]);
    mocks.documents.mockResolvedValue({ items: [], page: 1, page_size: 50, total: 0 });
    renderWorkspace();

    const selector = await screen.findByLabelText("Organization");
    await waitFor(() => expect(mocks.documents).toHaveBeenCalledWith(firstOrganization));
    fireEvent.change(selector, { target: { value: secondOrganization } });
    await waitFor(() => expect(mocks.documents).toHaveBeenCalledWith(secondOrganization));
    expect((selector as HTMLSelectElement).value).toBe(secondOrganization);
  });
});
