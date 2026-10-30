import { Fragment } from "react";
import { amsBlocks, cultures, roundDay } from "@/lib/sources";
import { cleanMrn, matchByMrn } from "@/lib/mrn";
import { newestFirst } from "@/lib/cultures";
import { newestStayFirst, STAY_FIELDS, type AmsBlock } from "@/lib/ams";
import { roundAbxLines } from "@/lib/round";
import { buildTimeline } from "@/lib/timeline";
import { ddmm, todayIso } from "@/lib/dates";
import { RoundCard } from "@/components/RoundCard";
import { Timeline } from "@/components/Timeline";
import { Banners, TopBar } from "@/components/TopBar";

export const dynamic = "force-dynamic";

const PREFIX_NOTE = "matched by MRN prefix";

function Stay({ b, prefix, open }: { b: AmsBlock; prefix: boolean; open: boolean }) {
  const fields = STAY_FIELDS.filter((f) => b.stay[f]?.length);
  return (
    <details className="stay" open={open}>
      <summary>
        <strong>{b.stay["Date of Admission"]?.[0] || b.stay["Date of ID Consultation"]?.[0] || "date not recorded"}</strong>
        <span className="muted small">{b.source} · {b.tab}{b.status ? ` · ${b.status}` : ""}</span>
        {prefix ? <span className="match">{PREFIX_NOTE}</span> : null}
      </summary>
      <div className="inner">
        {b.abx.some((a) => a["Indication/ID Diagnosis"]) ? (
          <div><span className="label">Diagnosis:</span> {b.abx.map((a) => a["Indication/ID Diagnosis"]).filter(Boolean).join(" · ")}</div>
        ) : null}
        {b.abx.length ? (
          <div className="tablewrap"><table>
            <thead><tr><th>Antibiotic</th><th>Started</th><th>Ended</th><th>Released by ID</th><th>Duration advice</th></tr></thead>
            <tbody>{b.abx.map((a, i) => (
              <tr key={i}><td>{a["Actual antibiotics"]}</td><td>{a["Date started"]}</td><td>{a["Date ended"]}</td><td>{a["Released by ID"]}</td><td>{a["Duration advice"]}</td></tr>
            ))}</tbody>
          </table></div>
        ) : null}
        {b.cultures.length ? (
          <div className="tablewrap"><table>
            <thead><tr><th>Culture / notes</th><th>Preliminary</th><th>Organism</th><th>Antibiogram</th></tr></thead>
            <tbody>{b.cultures.map((c, i) => (
              <tr key={i}><td>{c["Culture results/Notes"]}</td><td>{c["Preliminary Results"]}</td><td>{c["Organism"]}</td><td>{c["Antibiogram"]}</td></tr>
            ))}</tbody>
          </table></div>
        ) : null}
        {b.plans.length ? (
          <div><span className="label">Plan:</span>
            <ul className="lines">{b.plans.map((p, i) => <li key={i}>{p["Plan Date"] ? `${p["Plan Date"]} · ` : ""}{p["Plan"]}</li>)}</ul>
          </div>
        ) : null}
        {fields.length ? (
          <dl className="fields">
            {fields.map((f) => (<Fragment key={f}><dt>{f}</dt><dd>{b.stay[f]!.join("\n")}</dd></Fragment>))}
          </dl>
        ) : null}
      </div>
    </details>
  );
}

export default async function Patient({ params, searchParams }: { params: Promise<{ mrn: string }>; searchParams: Promise<{ date?: string }> }) {
  const mrn = cleanMrn(decodeURIComponent((await params).mrn));
  const { date } = await searchParams;
  const [round, cult, ams] = await Promise.all([roundDay(date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null), cultures(), amsBlocks()]);

  const day = round.ok ? round.data : null;
  const card = day?.groups.flatMap((g) => g.patients).find((p) => cleanMrn(p.mrn) === mrn) ?? null;
  const cultRows = cult.ok ? matchByMrn(mrn, cult.data, (r) => r.mrn) : [];
  const stays = matchByMrn(mrn, ams.blocks, (b) => b.mrn);
  const ordered = newestStayFirst(stays.map((s) => s.item));
  const prefixOf = new Set(stays.filter((s) => s.match === "prefix").map((s) => s.item));
  const name = card?.name || ordered[0]?.name || cultRows[0]?.item.cells.find((c) => c.header.toLowerCase() === "patient")?.value || "";
  const timeline = buildTimeline(ordered, card ? roundAbxLines(card) : [], card && day ? day.date : null, todayIso());

  const problems = [
    ...(round.ok ? [] : [{ source: round.source, error: round.error }]),
    ...(cult.ok ? [] : [{ source: cult.source, error: cult.error }]),
    ...ams.problems,
  ];

  return (
    <>
      <TopBar />
      <main className="wrap">
        <Banners problems={problems} />
        <h1>{name || "Patient"}</h1>
        <p className="muted">MRN {mrn}</p>

        <h2 className="section">Round{day ? ` · ${ddmm(day.date)}` : ""}</h2>
        {card ? <RoundCard p={card} link={false} /> : <p className="muted">Not on this round.</p>}

        <h2 className="section">Cultures</h2>
        {cultRows.length ? (
          <>
            {cultRows[0].match === "prefix" ? <p className="match">{PREFIX_NOTE}</p> : null}
            <div className="tablewrap"><table>
              <thead><tr><th>Collected</th><th>Specimen</th><th>Organism / result</th><th>Susceptible</th><th>Resistant</th></tr></thead>
              <tbody>{newestFirst(cultRows.map((c) => c.item)).map((r, i) => (
                <tr key={i}>
                  <td>{r.collected}</td><td>{r.specimen}</td>
                  <td>{r.organism || r.result}{r.organism && r.result && r.result !== r.organism ? <div className="muted small">{r.result}</div> : null}</td>
                  <td>{r.astS}</td>
                  <td>{r.astR ? <span className="resist">{r.astR}</span> : null}{r.astNotes ? <div className="muted small">{r.astNotes}</div> : null}</td>
                </tr>
              ))}</tbody>
            </table></div>
          </>
        ) : <p className="muted">{cult.ok ? "No finalised culture for this MRN." : "Cultures could not be read."}</p>}

        <h2 className="section">Admissions</h2>
        {ordered.length
          ? ordered.map((b, i) => <Stay key={`${b.source}-${b.tab}-${b.row}`} b={b} prefix={prefixOf.has(b)} open={i === 0} />)
          : <p className="muted">No AMS or register block for this MRN.</p>}

        <h2 className="section">Antibiotic timeline</h2>
        <Timeline t={timeline} />
      </main>
    </>
  );
}
