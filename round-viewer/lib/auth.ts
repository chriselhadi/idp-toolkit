// Sign-in with Google, limited to the team. Every page and API route sits behind it (middleware.ts).
//   GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET  the OAuth client for sign-in (not the service account)
//   NEXTAUTH_SECRET                         a long random string that signs the session cookie
//   ALLOWED_EMAILS                          comma-separated addresses allowed in
//   ALLOWED_DOMAINS                         comma-separated domains allowed in (e.g. "lau.edu,laumcrh.com"); optional
import type { NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";

const list = (v: string | undefined) => (v ?? "").split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);

/** Whether a verified Google address belongs to the team. Nobody is allowed in when neither list is set. */
export function isAllowed(email: string | null | undefined, emails = list(process.env.ALLOWED_EMAILS), domains = list(process.env.ALLOWED_DOMAINS)): boolean {
  const e = (email ?? "").trim().toLowerCase();
  if (!e.includes("@")) return false;
  return emails.includes(e) || domains.includes(e.split("@")[1]);
}

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
      authorization: { params: { prompt: "select_account" } },
    }),
  ],
  session: { strategy: "jwt", maxAge: 12 * 60 * 60 },
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    async signIn({ profile }) {
      const p = profile as { email?: string; email_verified?: boolean } | undefined;
      return !!p?.email_verified && isAllowed(p.email);
    },
  },
};
