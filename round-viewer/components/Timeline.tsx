import { ddmmyy } from "@/lib/dates";
import type { Timeline as T } from "@/lib/timeline";

const day = (iso: string) => Date.parse(`${iso}T00:00:00Z`) / 864e5;

export function Timeline({ t }: { t: T }) {
  if (!t.tracks.length) return <p className="muted">No antibiotic with a readable start date.</p>;
  const lo = day(t.min), span = Math.max(1, day(t.max) - lo + 1);
  return (
    <div className="tl" role="img" aria-label="Antibiotic courses over time, one bar per drug">
      <div className="tl-axis" aria-hidden="true"><span>{ddmmyy(t.min)}</span><span>{ddmmyy(t.max)}</span></div>
      {t.tracks.map((tr) => (
        <div className="tl-row" key={tr.drug}>
          <span>{tr.drug}</span>
          <div className="tl-track">
            {tr.segments.map((s, i) => (
              <span key={i} className={`tl-seg${s.open ? " open" : ""}`} title={s.from}
                style={{ left: `${((day(s.start) - lo) / span) * 100}%`, width: `${((day(s.end) - day(s.start) + 1) / span) * 100}%` }} />
            ))}
          </div>
        </div>
      ))}
      {t.undrawn ? <p className="muted small">{t.undrawn} antibiotic line{t.undrawn === 1 ? "" : "s"} without a readable date not drawn.</p> : null}
    </div>
  );
}
