import { SignInButton } from "@/components/SignInButton";

export const metadata = { title: "Sign in · ID round" };

export default async function Login({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <main className="login">
      <h1>ID round</h1>
      <p className="muted">LAU Medical Center · Infectious Diseases. Team accounts only.</p>
      {error ? <p className="banner" role="alert">This Google account is not on the team list. Ask the team lead to add it.</p> : null}
      <SignInButton />
    </main>
  );
}
