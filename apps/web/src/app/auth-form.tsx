"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { api } from "@/lib/api";

type AuthMutationResult =
  | Awaited<ReturnType<typeof api.login>>
  | Awaited<ReturnType<typeof api.register>>;

export function AuthForm({ mode }: { mode: "signin" | "signup" }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [email, setEmail] = useState("");
  const resend = useMutation({
    mutationFn: api.resendVerification,
    onSuccess: (result) => setNotice(result.message),
    onError: (cause: Error) => setError(cause.message),
  });
  const mutation = useMutation<AuthMutationResult, Error, FormData>({
    mutationFn: async (form: FormData): Promise<AuthMutationResult> => {
      if (mode === "signin") {
        return api.login({
          email: String(form.get("email")),
          password: String(form.get("password")),
        });
      }
      return api.register({
        email: String(form.get("email")),
        password: String(form.get("password")),
        display_name: String(form.get("name")),
      });
    },
    onSuccess: (result) => {
      if ("message" in result && typeof result.message === "string") {
        setNotice(result.message);
        return;
      }
      router.push("/");
    },
    onError: (cause: Error) => setError(cause.message),
  });

  async function google() {
    try {
      const { authorization_url } = await api.googleStart();
      window.location.assign(authorization_url);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Google sign-in is unavailable");
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="brand">ReadySet<span>•</span></div>
        <p className="eyebrow">Production workspace</p>
        <h1>{mode === "signin" ? "Welcome back" : "Build your secure workspace"}</h1>
        <p className="muted">Identity, people, and enterprise knowledge—properly separated.</p>
        <button className="button secondary" type="button" onClick={google}>Continue with Google</button>
        <div className="divider"><span>or</span></div>
        <form
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            setError("");
            setNotice("");
            mutation.mutate(new FormData(event.currentTarget));
          }}
        >
          {mode === "signup" && <label>Name<input name="name" autoComplete="name" required /></label>}
          <label>Email<input name="email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label>Password<input name="password" type="password" minLength={12} autoComplete={mode === "signin" ? "current-password" : "new-password"} required /></label>
          {error && <p className="error">{error}</p>}
          {notice && <p role="status">{notice}</p>}
          <button className="button" disabled={mutation.isPending}>{mutation.isPending ? "Working…" : mode === "signin" ? "Sign in" : "Create account"}</button>
        </form>
        {mode === "signin" && <p className="switch"><Link href="/forgot-password">Forgot password?</Link> · <button className="link-button" type="button" disabled={!email || resend.isPending} onClick={() => resend.mutate(email)}>Resend verification</button></p>}
        <p className="switch">{mode === "signin" ? "New to ReadySet? " : "Already have an account? "}<Link href={mode === "signin" ? "/signup" : "/signin"}>{mode === "signin" ? "Create account" : "Sign in"}</Link></p>
      </section>
    </main>
  );
}
