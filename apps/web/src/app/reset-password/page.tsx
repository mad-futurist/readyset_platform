"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

import { api } from "@/lib/api";

export default function ResetPasswordPage() {
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = new URLSearchParams(window.location.search).get("token");
    const password = String(new FormData(event.currentTarget).get("password"));
    if (!token) return setMessage("The reset link is incomplete.");
    try {
      await api.confirmPasswordReset(token, password);
      setMessage("Password changed. All existing sessions were revoked.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Password reset failed");
    }
  }
  return <main className="auth-shell"><section className="auth-card"><div className="brand">ReadySet<span>•</span></div><h1>Choose a new password</h1><form onSubmit={submit}><label>New password<input name="password" type="password" minLength={12} required /></label><button className="button">Reset password</button></form>{message && <p role="status">{message}</p>}<p className="switch"><Link href="/signin">Return to sign in</Link></p></section></main>;
}
