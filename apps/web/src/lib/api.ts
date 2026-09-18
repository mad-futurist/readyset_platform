import type { components } from "@readyset/api-client";

const API = "/api/v1";
type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function cookie(name: string): string {
  if (typeof document === "undefined") return "";
  const value = document.cookie
    .split("; ")
    .find((item) => item.startsWith(`${name}=`))
    ?.split("=")[1];
  return value ? decodeURIComponent(value) : "";
}

function errorMessage(value: unknown): string {
  if (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof value.error === "object" &&
    value.error !== null &&
    "message" in value.error &&
    typeof value.error.message === "string"
  ) {
    return value.error.message;
  }
  return "Request failed";
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  organizationId?: string,
): Promise<T> {
  const method = init.method ?? "GET";
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (organizationId) headers.set("X-ReadySet-Organization", organizationId);
  if (!["GET", "HEAD"].includes(method)) headers.set("X-CSRF-Token", cookie("rs_csrf"));
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(errorMessage(body), response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  me: () => request<Schemas["AuthResponse"]>("/auth/me"),
  register: (input: Schemas["RegisterRequest"]) =>
    request<Schemas["RegistrationResponse"]>("/auth/register", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  login: (input: Schemas["LoginRequest"]) =>
    request<Schemas["AuthResponse"]>("/auth/login", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  googleStart: () => request<{ authorization_url: string }>("/auth/google/start"),
  verifyEmail: (token: string) =>
    request<void>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token } satisfies Schemas["TokenRequest"]),
    }),
  confirmPasswordReset: (token: string, password: string) =>
    request<void>("/auth/password-reset/confirm", {
      method: "POST",
      body: JSON.stringify({ token, password } satisfies Schemas["PasswordResetConfirm"]),
    }),
  memberships: () => request<Schemas["MembershipRead"][]>("/organizations"),
  createOrganization: (name: string) =>
    request<Schemas["OrganizationRead"]>("/organizations", {
      method: "POST",
      body: JSON.stringify({ name } satisfies Schemas["OrganizationCreate"]),
    }),
  updateOrganization: (organizationId: string, name: string) =>
    request<Schemas["OrganizationRead"]>(
      "/organizations/current",
      {
        method: "PATCH",
        body: JSON.stringify({ name } satisfies Schemas["OrganizationUpdate"]),
      },
      organizationId,
    ),
  members: (organizationId: string) =>
    request<Schemas["MembershipRead"][]>(
      "/organizations/current/members",
      {},
      organizationId,
    ),
  invite: (
    organizationId: string,
    email: string,
    role: Exclude<Schemas["OrganizationRole"], "OWNER">,
  ) =>
    request<Schemas["InvitationRead"]>(
      "/organizations/current/invitations",
      {
        method: "POST",
        body: JSON.stringify({ email, role } satisfies Schemas["InvitationCreate"]),
      },
      organizationId,
    ),
  acceptInvitation: (token: string) =>
    request<Schemas["MembershipRead"]>("/organizations/invitations/accept", {
      method: "POST",
      body: JSON.stringify({ token } satisfies Schemas["TokenRequest"]),
    }),
  people: (organizationId: string) =>
    request<Schemas["Page_EmployeeProfileRead_"]>("/people", {}, organizationId),
  createPerson: (
    organizationId: string,
    input: Pick<Schemas["EmployeeProfileCreate"], "display_name" | "work_email">,
  ) =>
    request<Schemas["EmployeeProfileRead"]>(
      "/people",
      { method: "POST", body: JSON.stringify(input) },
      organizationId,
    ),
  teams: (organizationId: string) =>
    request<Schemas["Page_TeamRead_"]>("/teams", {}, organizationId),
  createTeam: (
    organizationId: string,
    input: Pick<Schemas["TeamCreate"], "name" | "description">,
  ) =>
    request<Schemas["TeamRead"]>(
      "/teams",
      { method: "POST", body: JSON.stringify(input) },
      organizationId,
    ),
  documents: (organizationId: string) =>
    request<Schemas["Page_DocumentRead_"]>("/documents", {}, organizationId),
  uploadDocument: (organizationId: string, form: FormData) =>
    request<Schemas["DocumentRead"]>(
      "/documents",
      { method: "POST", body: form },
      organizationId,
    ),
  versions: (organizationId: string, documentId: string) =>
    request<Schemas["DocumentVersionRead"][]>(
      `/documents/${documentId}/versions`,
      {},
      organizationId,
    ),
  download: async (organizationId: string, documentId: string, versionId: string) => {
    const response = await fetch(
      `${API}/documents/${documentId}/versions/${versionId}/download`,
      { credentials: "include", headers: { "X-ReadySet-Organization": organizationId } },
    );
    if (!response.ok) throw new ApiError("Download failed", response.status);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "";
    link.click();
    URL.revokeObjectURL(url);
  },
};
