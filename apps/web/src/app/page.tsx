"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { ApiError, api } from "@/lib/api";

type View = "knowledge" | "people" | "teams" | "settings";

export default function WorkspacePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>("knowledge");
  const [organizationId, setOrganizationId] = useState("");
  const session = useQuery({ queryKey: ["session"], queryFn: api.me, retry: false });
  const memberships = useQuery({
    queryKey: ["memberships"],
    queryFn: api.memberships,
    enabled: session.isSuccess,
  });

  useEffect(() => {
    if (session.error instanceof ApiError && session.error.status === 401) router.push("/signin");
  }, [router, session.error]);
  const selectedOrganizationId = organizationId || memberships.data?.[0]?.organization_id || "";

  const current = useMemo(
    () => memberships.data?.find((item) => item.organization_id === selectedOrganizationId),
    [memberships.data, selectedOrganizationId],
  );

  if (session.isLoading || memberships.isLoading) return <main className="loading">Opening your workspace…</main>;
  if (!session.data) return null;
  if (!memberships.data?.length) return <CreateOrganization userName={session.data.user.display_name} onCreated={() => queryClient.invalidateQueries({ queryKey: ["memberships"] })} />;

  return (
    <main className="workspace">
      <aside className="sidebar">
        <div className="brand brand-light">ReadySet<span>•</span></div>
        <select aria-label="Organization" value={selectedOrganizationId} onChange={(event) => setOrganizationId(event.target.value)}>
          {memberships.data.map((membership) => <option key={membership.id} value={membership.organization_id}>{membership.organization?.name ?? membership.organization_id}</option>)}
        </select>
        <nav>{(["knowledge", "people", "teams", "settings"] as View[]).map((item) => <button key={item} className={view === item ? "active" : ""} onClick={() => setView(item)}>{item}</button>)}</nav>
        <div className="identity"><div className="avatar">{session.data.user.display_name.slice(0, 1).toUpperCase()}</div><div><strong>{session.data.user.display_name}</strong><small>{current?.role}</small></div></div>
      </aside>
      <section className="content">
        <header><p className="eyebrow">{current?.organization?.name ?? "Organization"}</p><h1>{title(view)}</h1><p className="muted">{subtitle(view)}</p></header>
        {view === "knowledge" && <Knowledge organizationId={selectedOrganizationId} />}
        {view === "people" && <People organizationId={selectedOrganizationId} />}
        {view === "teams" && <Teams organizationId={selectedOrganizationId} />}
        {view === "settings" && <Settings organizationId={selectedOrganizationId} organizationName={current?.organization?.name ?? "Organization"} membership={current?.role ?? "MEMBER"} />}
      </section>
    </main>
  );
}

function title(view: View) {
  return { knowledge: "Knowledge library", people: "People", teams: "Teams", settings: "Workspace settings" }[view];
}

function subtitle(view: View) {
  return {
    knowledge: "Versioned source files with tenant-safe access controls.",
    people: "Organization-owned employee profiles, separate from login identities.",
    teams: "Groups that can later carry knowledge and onboarding access.",
    settings: "Membership and security posture for this workspace.",
  }[view];
}

function CreateOrganization({ userName, onCreated }: { userName: string; onCreated: () => void }) {
  const mutation = useMutation({ mutationFn: api.createOrganization, onSuccess: onCreated });
  return <main className="auth-shell"><section className="auth-card"><div className="brand">ReadySet<span>•</span></div><p className="eyebrow">Hello, {userName}</p><h1>Create your workspace</h1><p className="muted">Every person and document lives inside a secure organization boundary.</p><form onSubmit={(event) => { event.preventDefault(); mutation.mutate(String(new FormData(event.currentTarget).get("name"))); }}><label>Organization name<input name="name" required /></label><button className="button">Create workspace</button></form></section></main>;
}

function Knowledge({ organizationId }: { organizationId: string }) {
  const client = useQueryClient();
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const documents = useQuery({ queryKey: ["documents", organizationId], queryFn: () => api.documents(organizationId) });
  const upload = useMutation({
    mutationFn: (form: FormData) => api.uploadDocument(organizationId, form),
    onSuccess: () => client.invalidateQueries({ queryKey: ["documents", organizationId] }),
  });
  return <><form className="panel upload" onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); upload.mutate(new FormData(event.currentTarget)); event.currentTarget.reset(); }}><div><h2>Add a source</h2><p className="muted">PDF, Word, Markdown, or plain text up to the configured limit.</p></div><input name="title" aria-label="Document title" placeholder="Document title" required /><select name="visibility" aria-label="Visibility"><option value="ORGANIZATION">Everyone in workspace</option><option value="RESTRICTED">Restricted</option></select><input name="file" aria-label="File" type="file" required /><button className="button" disabled={upload.isPending}>{upload.isPending ? "Uploading…" : "Upload"}</button></form>{upload.error && <p className="error">{upload.error.message}</p>}<div className="grid">{documents.data?.items.map((document) => <article className="card" key={document.id}><div className="file-mark">{document.document_type?.slice(0, 3).toUpperCase() || "DOC"}</div><div><h3>{document.title}</h3><p>{document.description || document.domain || "Enterprise source"}</p><div className="tags"><span>{document.visibility.toLowerCase()}</span><span>versioned</span></div></div><button className="text-button" onClick={() => setSelectedDocumentId(document.id)}>View details</button><button className="text-button" onClick={async () => { const versions = await api.versions(organizationId, document.id); if (versions[0]) await api.download(organizationId, document.id, versions[0].id); }}>Download current</button></article>)}{documents.data?.items.length === 0 && <Empty text="No documents yet. Upload the first trusted source." />}</div>{selectedDocumentId && <DocumentOperations organizationId={organizationId} documentId={selectedDocumentId} onClose={() => setSelectedDocumentId("")} />}</>;
}

function DocumentOperations({ organizationId, documentId, onClose }: { organizationId: string; documentId: string; onClose: () => void }) {
  const client = useQueryClient();
  const document = useQuery({ queryKey: ["document", organizationId, documentId], queryFn: () => api.document(organizationId, documentId) });
  const versions = useQuery({ queryKey: ["versions", organizationId, documentId], queryFn: () => api.versions(organizationId, documentId) });
  const grants = useQuery({ queryKey: ["grants", organizationId, documentId], queryFn: () => api.grants(organizationId, documentId), retry: false });
  const members = useQuery({ queryKey: ["members", organizationId], queryFn: () => api.members(organizationId) });
  const teams = useQuery({ queryKey: ["teams", organizationId], queryFn: () => api.teams(organizationId) });
  const upload = useMutation({ mutationFn: (form: FormData) => api.uploadVersion(organizationId, documentId, form), onSuccess: async () => { await client.invalidateQueries({ queryKey: ["versions", organizationId, documentId] }); await client.invalidateQueries({ queryKey: ["documents", organizationId] }); } });
  const replace = useMutation({ mutationFn: (input: { user_ids: string[]; team_ids: string[] }) => api.replaceGrants(organizationId, documentId, input), onSuccess: () => client.invalidateQueries({ queryKey: ["grants", organizationId, documentId] }) });
  return <section className="panel document-detail" aria-label="Document details"><div className="detail-title"><div><p className="eyebrow">Document detail</p><h2>{document.data?.title ?? "Loading…"}</h2></div><button className="text-button" onClick={onClose}>Close</button></div><form className="inline-form" onSubmit={(event) => { event.preventDefault(); upload.mutate(new FormData(event.currentTarget)); event.currentTarget.reset(); }}><input name="file" aria-label="New version file" type="file" required /><button className="button">Upload new version</button></form>{upload.error && <p className="error">{upload.error.message}</p>}<h3>Version history</h3><div className="history">{versions.data?.map((version) => <div key={version.id}><strong>Version {version.version_number}</strong><span>{version.original_filename} · {version.size_bytes} bytes</span><button className="text-button" onClick={() => api.download(organizationId, documentId, version.id)}>Download</button></div>)}</div>{document.data?.visibility === "RESTRICTED" && !grants.error && <form onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); replace.mutate({ user_ids: form.getAll("user_ids").map(String), team_ids: form.getAll("team_ids").map(String) }); }}><h3>Restricted access</h3><div className="grant-grid"><fieldset><legend>Users</legend>{members.data?.filter((member) => member.status === "ACTIVE").map((member) => <label key={member.id}><input type="checkbox" name="user_ids" value={member.user_id} defaultChecked={grants.data?.user_ids.includes(member.user_id)} />{member.user?.display_name ?? member.user?.primary_email ?? member.user_id}</label>)}</fieldset><fieldset><legend>Teams</legend>{teams.data?.items.map((team) => <label key={team.id}><input type="checkbox" name="team_ids" value={team.id} defaultChecked={grants.data?.team_ids.includes(team.id)} />{team.name}</label>)}</fieldset></div><button className="button">Save access</button></form>}</section>;
}

function People({ organizationId }: { organizationId: string }) {
  const client = useQueryClient();
  const people = useQuery({ queryKey: ["people", organizationId], queryFn: () => api.people(organizationId) });
  const create = useMutation({ mutationFn: (data: { display_name: string; work_email?: string }) => api.createPerson(organizationId, data), onSuccess: () => client.invalidateQueries({ queryKey: ["people", organizationId] }) });
  return <><InlineCreate labels={["Name", "Work email"]} onSubmit={(values) => create.mutate({ display_name: values[0], work_email: values[1] || undefined })} action="Add person" /><div className="table panel"><div className="table-head"><span>Person</span><span>Department</span><span>Status</span></div>{people.data?.items.map((person) => <div className="table-row" key={person.id}><span><strong>{person.display_name}</strong><small>{person.work_email}</small></span><span>{person.department || "—"}</span><span className="status">{person.status}</span></div>)}{people.data?.items.length === 0 && <Empty text="No employee profiles yet." />}</div></>;
}

function Teams({ organizationId }: { organizationId: string }) {
  const client = useQueryClient();
  const teams = useQuery({ queryKey: ["teams", organizationId], queryFn: () => api.teams(organizationId) });
  const create = useMutation({ mutationFn: (input: { name: string; description?: string }) => api.createTeam(organizationId, input), onSuccess: () => client.invalidateQueries({ queryKey: ["teams", organizationId] }) });
  return <><InlineCreate labels={["Team name", "Description"]} onSubmit={(values) => create.mutate({ name: values[0], description: values[1] || undefined })} action="Create team" /><div className="grid">{teams.data?.items.map((team) => <article className="card" key={team.id}><div className="team-mark">{team.name.slice(0, 2).toUpperCase()}</div><div><h3>{team.name}</h3><p>{team.description || "No description"}</p><div className="tags"><span>{team.slug}</span></div></div></article>)}{teams.data?.items.length === 0 && <Empty text="No teams yet." />}</div></>;
}

function InlineCreate({ labels, action, onSubmit }: { labels: string[]; action: string; onSubmit: (values: string[]) => void }) {
  return <form className="panel inline-form" onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); onSubmit(labels.map((_, index) => String(form.get(`field-${index}`) || ""))); event.currentTarget.reset(); }}>{labels.map((label, index) => <input key={label} name={`field-${index}`} aria-label={label} placeholder={label} required={index === 0} />)}<button className="button">{action}</button></form>;
}

function Settings({ organizationId, organizationName, membership }: { organizationId: string; organizationName: string; membership: string }) {
  const client = useQueryClient();
  const canManage = ["OWNER", "ADMIN"].includes(membership);
  const members = useQuery({ queryKey: ["members", organizationId], queryFn: () => api.members(organizationId) });
  const invitations = useQuery({ queryKey: ["invitations", organizationId], queryFn: () => api.pendingInvitations(organizationId), enabled: canManage });
  const rename = useMutation({ mutationFn: (name: string) => api.updateOrganization(organizationId, name), onSuccess: () => client.invalidateQueries({ queryKey: ["memberships"] }) });
  const refreshAdministration = async () => { await client.invalidateQueries({ queryKey: ["members", organizationId] }); await client.invalidateQueries({ queryKey: ["invitations", organizationId] }); await client.invalidateQueries({ queryKey: ["memberships"] }); };
  const invite = useMutation({ mutationFn: ({ email, role }: { email: string; role: "ADMIN" | "MANAGER" | "MEMBER" }) => api.invite(organizationId, email, role), onSuccess: refreshAdministration });
  const changeRole = useMutation({ mutationFn: ({ id, role }: { id: string; role: "ADMIN" | "MANAGER" | "MEMBER" }) => api.changeMemberRole(organizationId, id, role), onSuccess: refreshAdministration });
  const revoke = useMutation({ mutationFn: (id: string) => api.revokeMember(organizationId, id), onSuccess: refreshAdministration });
  const transfer = useMutation({ mutationFn: (id: string) => api.transferOwnership(organizationId, id), onSuccess: refreshAdministration });
  const revokeInvitation = useMutation({ mutationFn: (id: string) => api.revokeInvitation(organizationId, id), onSuccess: refreshAdministration });
  return <div className="settings-stack"><div className="panel settings"><div><p className="eyebrow">Your organization role</p><h2>{membership}</h2></div><div className="security-note"><strong>Security boundary active</strong><p>Every API request revalidates your membership. Browser IDs never grant access.</p></div></div>{canManage && <form className="panel inline-form" onSubmit={(event) => { event.preventDefault(); rename.mutate(String(new FormData(event.currentTarget).get("name"))); }}><input name="name" aria-label="Organization name" defaultValue={organizationName} required /><button className="button">Save name</button></form>}{canManage && <form className="panel inline-form" onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); invite.mutate({ email: String(form.get("email")), role: String(form.get("role")) as "ADMIN" | "MANAGER" | "MEMBER" }); event.currentTarget.reset(); }}><input name="email" aria-label="Invite email" type="email" placeholder="colleague@example.com" required /><select name="role" aria-label="Invitation role"><option value="MEMBER">Member</option><option value="MANAGER">Manager</option><option value="ADMIN">Admin</option></select><button className="button">Invite or reissue</button></form>}{invite.data && <p className="panel" role="status">Delivery: {invite.data.delivery_status}{invite.data.development_token && <> · Development token: <code>{invite.data.development_token}</code></>}</p>}<div className="table panel"><div className="table-head"><span>Member</span><span>Role</span><span>Actions</span></div>{members.data?.map((item) => <div className="table-row" key={item.id}><span><strong>{item.user?.display_name ?? item.user?.primary_email ?? item.user_id}</strong><small>{item.user?.primary_email} · {item.status}</small></span><span>{item.role}</span><span className="actions">{canManage && item.role !== "OWNER" && item.status === "ACTIVE" && <><select aria-label={`Role for ${item.user?.primary_email ?? item.user_id}`} value={item.role} onChange={(event) => changeRole.mutate({ id: item.id, role: event.target.value as "ADMIN" | "MANAGER" | "MEMBER" })}><option value="MEMBER">Member</option><option value="MANAGER">Manager</option><option value="ADMIN">Admin</option></select><button className="text-button" onClick={() => revoke.mutate(item.id)}>Revoke</button>{membership === "OWNER" && <button className="text-button" onClick={() => transfer.mutate(item.id)}>Transfer ownership</button>}</>}</span></div>)}</div>{canManage && <div className="table panel"><div className="table-head"><span>Pending invitation</span><span>Role</span><span>Actions</span></div>{invitations.data?.map((invitation) => <div className="table-row" key={invitation.id}><span><strong>{invitation.email}</strong><small>Expires {new Date(invitation.expires_at).toLocaleDateString()}</small></span><span>{invitation.role}</span><span className="actions"><button className="text-button" onClick={() => invite.mutate({ email: invitation.email, role: invitation.role as "ADMIN" | "MANAGER" | "MEMBER" })}>Reissue</button><button className="text-button" onClick={() => revokeInvitation.mutate(invitation.id)}>Revoke</button></span></div>)}</div>}</div>;
}

function Empty({ text }: { text: string }) { return <div className="empty">{text}</div>; }
