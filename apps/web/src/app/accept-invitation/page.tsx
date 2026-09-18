"use client";

import Link from "next/link";
import { useState } from "react";

import { api } from "@/lib/api";

export default function AcceptInvitationPage() {
  const [message, setMessage] = useState("");
  async function accept() {
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) return setMessage("The invitation link is incomplete.");
    try {
      await api.acceptInvitation(token);
      setMessage("Invitation accepted. Open your ReadySet workspace.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Invitation could not be accepted");
    }
  }
  return <main className="auth-shell"><section className="auth-card"><div className="brand">ReadySet<span>•</span></div><h1>Join the workspace</h1><p className="muted">Sign in with the invited email, then accept this one-time invitation.</p><button className="button" onClick={accept}>Accept invitation</button>{message && <p role="status">{message}</p>}<p className="switch"><Link href="/signin">Sign in</Link></p></section></main>;
}
