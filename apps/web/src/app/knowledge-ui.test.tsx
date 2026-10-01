import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ askKnowledge: vi.fn(), versions: vi.fn(), download: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: mocks }));

import { AskAI, IngestionBadge, locatorText } from "./knowledge-ui";

function renderAsk(organizationId = "org-a") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><AskAI organizationId={organizationId} /></QueryClientProvider>);
}

describe("Evidence-backed knowledge UI", () => {
  beforeEach(() => Object.values(mocks).forEach((mock) => mock.mockReset()));

  it("shows a page citation and opens the exact cited version", async () => {
    mocks.askKnowledge.mockResolvedValue({ answer: "Rotate keys every 30 days [S1]", insufficient_evidence: false,
      citations: [{ organization_id: "org-a", document_id: "doc", document_version_id: "version-two", chunk_id: "chunk",
        title: "Security policy", version_number: 2, source_locator: { kind: "pdf", page: 3 }, excerpt: "Rotate keys every 30 days.", score: 0.03, label: "S1" }] });
    mocks.versions.mockResolvedValue([{ id: "version-two", version_number: 2, original_filename: "policy-v2.pdf", size_bytes: 300, ingestion_status: "READY" }]);
    renderAsk();
    fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "How often should we rotate keys?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask AI" }));
    expect(await screen.findByText("Rotate keys every 30 days [S1]")).toBeTruthy();
    expect(mocks.askKnowledge).toHaveBeenCalledWith("org-a", { query: "How often should we rotate keys?" });
    fireEvent.click(screen.getByRole("button", { name: "[S1] Security policy · Version 2" }));
    expect(await screen.findByText("policy-v2.pdf · 300 bytes")).toBeTruthy();
    expect(mocks.versions).toHaveBeenCalledWith("org-a", "doc");
    fireEvent.click(screen.getByRole("button", { name: "Download cited version" }));
    await waitFor(() => expect(mocks.download).toHaveBeenCalledWith("org-a", "doc", "version-two"));
  });

  it("renders insufficient evidence without source links", async () => {
    mocks.askKnowledge.mockResolvedValue({ answer: "I don't have enough information in the accessible company knowledge.", citations: [], insufficient_evidence: true });
    renderAsk();
    fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "Unknown policy" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask AI" }));
    expect(await screen.findByText(/don't have enough information/)).toBeTruthy();
    expect(screen.queryByText("Sources")).toBeNull();
  });

  it("shows product ingestion labels and structural locators", () => {
    const view = render(<IngestionBadge status="PROCESSING" />);
    expect(screen.getByText("Processing")).toBeTruthy();
    view.rerender(<IngestionBadge status="FAILED" />);
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(locatorText({ kind: "markdown", heading_path: ["Deploy", "Backups"], line_start: 10, line_end: 20 })).toBe("Deploy › Backups · Lines 10–20");
  });
});
