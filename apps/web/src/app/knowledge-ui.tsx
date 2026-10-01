"use client";

import type { components } from "@readyset/api-client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/lib/api";

type Schemas = components["schemas"];

export function IngestionBadge({ status }: { status: Schemas["IngestionStatus"] | null | undefined }) {
  const labels = { PENDING_UPLOAD: "Pending upload", UPLOADED: "Uploaded", PROCESSING: "Processing", READY: "Ready", FAILED: "Failed" };
  return <span className={`ingestion-status ingestion-${status?.toLowerCase() ?? "unknown"}`}>{status ? labels[status] : "Awaiting processing"}</span>;
}

export function locatorText(locator: Record<string, unknown>): string {
  if (locator.kind === "pdf") return `Page ${locator.page}`;
  const headings = Array.isArray(locator.heading_path) ? locator.heading_path.join(" › ") : "";
  if (typeof locator.line_start === "number") return `${headings ? `${headings} · ` : ""}Lines ${locator.line_start}–${locator.line_end}`;
  if (typeof locator.paragraph_start === "number") return `${headings ? `${headings} · ` : ""}Paragraph ${locator.paragraph_start}`;
  if (typeof locator.table === "number") return `Table ${locator.table}`;
  return headings || "Source section";
}

export function AskAI({ organizationId }: { organizationId: string }) {
  const [selected, setSelected] = useState<Schemas["Citation"] | null>(null);
  const ask = useMutation({ mutationFn: (query: string) => api.askKnowledge(organizationId, { query }), onMutate: () => setSelected(null) });
  return <section className="panel ask-ai" aria-label="Ask AI">
    <h2>Ask your company knowledge</h2>
    <p className="muted">Answers use the ready, current sources you can access. Sources being processed are unavailable until ready.</p>
    <form onSubmit={(event) => { event.preventDefault(); ask.mutate(String(new FormData(event.currentTarget).get("question"))); }}>
      <label>Your question<textarea name="question" aria-label="Your question" required maxLength={4000} rows={3} /></label>
      <button className="button" disabled={ask.isPending}>{ask.isPending ? "Finding evidence…" : "Ask AI"}</button>
    </form>
    {ask.error && <p className="error" role="alert">{ask.error.message}</p>}
    {ask.data && <div role="status" className="answer"><p>{ask.data.answer}</p>
      {!!ask.data.citations.length && <h3>Sources</h3>}
      {ask.data.citations.map((citation) => <article key={citation.chunk_id} className="citation">
        <button className="text-button" onClick={() => setSelected(citation)}>[{citation.label}] {citation.title} · Version {citation.version_number}</button>
        <small>{locatorText(citation.source_locator)}</small><blockquote>{citation.excerpt}</blockquote>
      </article>)}
    </div>}
    {selected && <CitationMetadata key={selected.chunk_id} organizationId={organizationId} citation={selected} onClose={() => setSelected(null)} />}
  </section>;
}

function CitationMetadata({ organizationId, citation, onClose }: { organizationId: string; citation: Schemas["Citation"]; onClose: () => void }) {
  const versions = useQuery({ queryKey: ["versions", organizationId, citation.document_id], queryFn: () => api.versions(organizationId, citation.document_id), retry: false });
  const version = versions.data?.find((item) => item.id === citation.document_version_id);
  const download = useMutation({ mutationFn: () => api.download(organizationId, citation.document_id, citation.document_version_id) });
  return <section className="citation-detail" aria-label="Citation source version">
    <h3>{citation.title} · Version {citation.version_number}</h3><p>{locatorText(citation.source_locator)}</p>
    {version && <><p>{version.original_filename} · {version.size_bytes} bytes</p><IngestionBadge status={version.ingestion_status} /><button className="text-button" onClick={() => download.mutate()}>Download cited version</button></>}
    {versions.error && <p className="error">This source is no longer accessible.</p>}
    {download.error && <p className="error">{download.error.message}</p>}
    <button className="text-button" onClick={onClose}>Close source</button>
  </section>;
}
