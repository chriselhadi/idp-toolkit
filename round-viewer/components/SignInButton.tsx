"use client";
import { signIn, signOut } from "next-auth/react";

export function SignInButton() {
  return <button type="button" className="btn primary" onClick={() => signIn("google", { callbackUrl: "/" })}>Sign in with Google</button>;
}

export function SignOutButton() {
  return <button type="button" className="btn ghost" onClick={() => signOut({ callbackUrl: "/login" })}>Sign out</button>;
}
