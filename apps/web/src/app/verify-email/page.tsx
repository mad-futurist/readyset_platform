"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

export default function VerifyEmailPage() {
  const [message, setMessage] = useState("The verification link is incomplete.");
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) return;
    api.verifyEmail(token).then(
      () => setMessage("Email verified. You can now sign in."),
      (error: Error) => setMessage(error.message),
    );
  }, []);
  return <main className="auth-shell"><section className="auth-card"><div className="brand">ReadySet<span>•</span></div><h1>Email verification</h1><p role="status">{message}</p><p className="switch"><Link href="/signin">Go to sign in</Link></p></section></main>;
}
