"use client";
// The round, grouped as in the file, with a search box over name, room and MRN.
import { useMemo, useState } from "react";
import { RoundCard } from "./RoundCard";
import type { RoundDay } from "@/lib/round";

const norm = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();

export function RoundView({ day }: { day: RoundDay }) {
  const [q, setQ] = useState("");
  const groups = useMemo(() => {
    const t = norm(q);
    if (!t) return day.groups;
    const digits = t.replace(/\D/g, "").replace(/^0+/, "");
    return day.groups
      .map((g) => ({
        ...g,
        patients: g.patients.filter((p) =>
          norm(p.name).includes(t) || norm(p.room).includes(t)
          || (!!digits && p.mrn.replace(/\D/g, "").replace(/^0+/, "").includes(digits))),
      }))
      .filter((g) => g.patients.length);
  }, [q, day.groups]);
  const count = groups.reduce((n, g) => n + g.patients.length, 0);

  return (
    <>
      <label className="muted small" htmlFor="round-search">Search by name, room or MRN</label>
      <input id="round-search" className="search" type="search" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder="Name, room or MRN" autoComplete="off" />
      {q ? <p className="muted small">{count} patient{count === 1 ? "" : "s"}</p> : null}
      {groups.map((g, gi) => (
        <section key={`${g.header}-${gi}`}>
          <h2 className="group">{g.header}</h2>
          {g.patients.map((p, i) => <RoundCard key={`${p.pid}-${i}`} p={p} date={day.date} />)}
        </section>
      ))}
      {!q && day.off_list?.length ? (
        <section>
          <h2 className="group">Not on the ID list</h2>
          <ul className="lines offlist">
            {day.off_list.map((o, i) => <li key={i}><strong>{o.room}</strong> {o.name}{o.line ? ` · ${o.line}` : ""}</li>)}
          </ul>
        </section>
      ) : null}
    </>
  );
}
