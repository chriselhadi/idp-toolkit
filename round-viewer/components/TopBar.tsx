import Link from "next/link";
import { RefreshButton } from "./RefreshButton";
import { SignOutButton } from "./SignInButton";

export function TopBar() {
  return (
    <header className="top">
      <div className="wrap">
        <Link href="/" className="title">ID round</Link>
        <Link href="/days" className="btn ghost">Days</Link>
        <RefreshButton />
        <SignOutButton />
      </div>
    </header>
  );
}

export function Banners({ problems }: { problems: { source: string; error: string }[] }) {
  if (!problems.length) return null;
  return (
    <>
      {problems.map((p) => (
        <div className="banner" role="alert" key={p.source}>
          <strong>Could not read: {p.source}</strong>
          <span className="muted">{p.error}. The rest of the page is shown.</span>
        </div>
      ))}
    </>
  );
}
