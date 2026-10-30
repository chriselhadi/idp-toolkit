// One patient as the recap email shows them, in the email's order. Nothing is added or rephrased.
import Link from "next/link";
import { parseAbxLine } from "@/lib/abx";
import type { RoundPatient } from "@/lib/round";
import { cleanMrn } from "@/lib/mrn";

const isAlert = (s: string) => s.trim().startsWith("!!");

function Lines({ items, className }: { items?: string[]; className?: string }) {
  if (!items?.length) return null;
  return (
    <ul className="lines">
      {items.map((t, i) => <li key={i} className={isAlert(t) ? "alert" : className}>{t}</li>)}
    </ul>
  );
}

function AbxList({ lines }: { lines?: string[] }) {
  if (!lines?.length) return null;
  return (
    <ul className="abx">
      {lines.map((t, i) => {
        const a = parseAbxLine(t);
        return <li key={i} className={isAlert(t) ? "alert" : a.stopped ? "stopped" : undefined}>{a.stopped ? <s>{t}</s> : t}</li>;
      })}
    </ul>
  );
}

function Field({ label, text }: { label: string; text?: string }) {
  if (!text) return null;
  return <div className={isAlert(text) ? "alert" : undefined}><span className="label">{label}:</span> {text}</div>;
}

export function RoundCard({ p, date, link = true }: { p: RoundPatient; date?: string; link?: boolean }) {
  const mrn = cleanMrn(p.mrn);
  const head = (
    <>
      <span className="room">{p.room}</span>
      <span className="name">{p.name}</span>
      {p.new ? <span className="tag">(new)</span> : null}
      {p.uc ? <span className="tag">(UC)</span> : null}
      {p.initials ? <span className="tag">{p.initials}</span> : null}
    </>
  );
  return (
    <article className="card">
      {link && mrn
        ? <Link className="card-head" href={`/patient/${mrn}${date ? `?date=${date}` : ""}`}>{head}</Link>
        : <div className="card-head">{head}</div>}
      <div className="card-body">
        {p.one_liner ? <div className="one-liner">{p.one_liner}</div> : null}
        <Lines items={p.updates_id} className="upd-id" />
        <Lines items={p.updates_other} />
        <Lines items={p.im} />
        {p.issues?.length ? (
          <ol className="issues">
            {p.issues.map((iss, i) => (
              <li key={i}>
                <span className={isAlert(iss.dx) ? "alert" : undefined}>{iss.dx}</span>
                <AbxList lines={iss.abx} />
              </li>
            ))}
          </ol>
        ) : null}
        <AbxList lines={p.abx_other} />
        <Field label="Micro" text={p.micro_recap} />
        <Field label="Status" text={p.status} />
        {p.pendings?.length ? <div><span className="label">Pending:</span> <Lines items={p.pendings} /></div> : null}
        <Field label="ID Plan" text={p.id_plan} />
        <Lines items={p.conflicts} className="alert" />
        <Lines items={p.not_applied} className="alert" />
      </div>
    </article>
  );
}
