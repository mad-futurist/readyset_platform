"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { FormEvent } from "react";

import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const request = useMutation({ mutationFn: api.requestPasswordReset });
  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="brand">ReadySet<span>•</span></div>
        <p className="eyebrow">Account recovery</p>
        <h1>Reset your password</h1>
        <p className="muted">Enter your email. The response is the same whether or not an account exists.</p>
        <form onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          request.mutate(String(new FormData(event.currentTarget).get("email")));
        }}>
          <label>Email<input name="email" type="email" autoComplete="email" required /></label>
          {request.data && <p role="status">{request.data.message}</p>}
          {request.error && <p className="error">{request.error.message}</p>}
          <button className="button" disabled={request.isPending}>Send reset instructions</button>
        </form>
        <p className="switch"><Link href="/signin">Back to sign in</Link></p>
      </section>
    </main>
  );
}
