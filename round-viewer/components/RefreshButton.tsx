"use client";
import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { refreshData } from "@/app/actions";

export function RefreshButton() {
  const [pending, start] = useTransition();
  const router = useRouter();
  return (
    <button type="button" className="btn" disabled={pending}
      onClick={() => start(async () => { await refreshData(); router.refresh(); })}>
      {pending ? "Refreshing…" : "Refresh"}
    </button>
  );
}
