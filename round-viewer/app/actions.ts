"use server";
import { revalidatePath } from "next/cache";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { clearCache } from "@/lib/cache";

/** The refresh button: forget the cached Drive reads and read again. */
export async function refreshData(): Promise<void> {
  if (!(await getServerSession(authOptions))) return;
  clearCache();
  revalidatePath("/", "layout");
}
