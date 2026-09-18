import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
  googleStart: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    login: mocks.login,
    register: mocks.register,
    googleStart: mocks.googleStart,
  },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));

import { AuthForm } from "./auth-form";

function renderForm(mode: "signin" | "signup") {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthForm mode={mode} />
    </QueryClientProvider>,
  );
}

describe("AuthForm", () => {
  beforeEach(() => {
    mocks.login.mockReset();
    mocks.register.mockReset();
    mocks.push.mockReset();
  });

  it("submits password sign-in and navigates only after authentication", async () => {
    mocks.login.mockResolvedValue({ user: { id: "user" }, memberships: [], csrf_token: "csrf" });
    renderForm("signin");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct horse battery staple" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(mocks.login).toHaveBeenCalledWith({
        email: "user@example.com",
        password: "correct horse battery staple",
      }),
    );
    expect(mocks.push).toHaveBeenCalledWith("/");
  });

  it("keeps a newly registered user unauthenticated pending verification", async () => {
    mocks.register.mockResolvedValue({ message: "Check your email to verify your account." });
    renderForm("signup");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New User" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct horse battery staple" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect((await screen.findByRole("status")).textContent).toContain(
      "Check your email to verify your account.",
    );
    expect(mocks.push).not.toHaveBeenCalled();
  });
});
