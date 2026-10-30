import Link from "next/link";
import { roundFiles } from "@/lib/sources";
import { ddmm } from "@/lib/dates";
import { RoundScreen } from "@/components/RoundScreen";
import { Banners, TopBar } from "@/components/TopBar";

export const dynamic = "force-dynamic";

const ISO = /^\d{4}-\d{2}-\d{2}$/;

export default async function Days({ searchParams }: { searchParams: Promise<{ date?: string }> }) {
  const { date } = await searchParams;
  if (date && ISO.test(date)) return <RoundScreen date={date} />;
  const files = await roundFiles();
  return (
    <>
      <TopBar />
      <main className="wrap">
        <h1>Earlier rounds</h1>
        <Banners problems={files.ok ? [] : [{ source: files.source, error: files.error }]} />
        {files.ok && files.data.length === 0 ? <p className="muted">No round files yet.</p> : null}
        {files.ok ? (
          <ul className="days">
            {files.data.map((f) => (
              <li key={f.id}><Link href={`/days?date=${f.date}`}>{ddmm(f.date)}/{f.date.slice(2, 4)}</Link></li>
            ))}
          </ul>
        ) : null}
      </main>
    </>
  );
}
