import { roundDay } from "@/lib/sources";
import { ddmm } from "@/lib/dates";
import { Banners, TopBar } from "./TopBar";
import { RoundView } from "./RoundView";

/** A day's round (the newest when no date is given), as stored. */
export async function RoundScreen({ date }: { date?: string | null }) {
  const res = await roundDay(date);
  const day = res.ok ? res.data : null;
  return (
    <>
      <TopBar />
      <main className="wrap">
        <Banners problems={res.ok ? [] : [{ source: res.source, error: res.error }]} />
        {day ? (
          <>
            <h1>Round · {ddmm(day.date)}</h1>
            <RoundView day={day} />
          </>
        ) : res.ok ? (
          <div className="banner" role="status"><strong>No round file yet.</strong><span className="muted">No "IDP Round YYYY-MM-DD.json" in IDP_Data.</span></div>
        ) : null}
      </main>
    </>
  );
}
