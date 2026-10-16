// Small presentational components shared by the views (ported from the approved prototype).
import type { ReactNode } from "react";
import type { Citation, IssueCounts, Sev } from "./api";
import { useApp } from "./store";
import { TYPE_META, issueTotal, nf, worst } from "./util";

const ICONS: Record<string, string> = {
  graph: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8.2 7.2 15.6 8M7.3 8.2l3.6 7.6M16.8 9.3 13.2 16"/>',
  folder: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 1 6.5 18H20v3H6.5"/>',
  shield: '<path d="M12 3 4 6v6c0 4.4 3.4 8.1 8 9 4.6-.9 8-4.6 8-9V6z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  table: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M3.5 9.5h17M3.5 14.5h17M9.5 4.5v15"/>',
  pdf: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 13h6M9 17h4"/>',
  map: '<path d="m3 6 6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  focus: '<circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
  open: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  send: '<path d="M4 12 20 4l-6 16-3-7z"/>',
  alert: '<path d="M12 4 2.5 20h19z"/><path d="M12 10v4M12 17h.01"/>',
  chat: '<path d="M4 5h16v11H8l-4 4z"/>',
  moon: '<path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9z"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  check: '<path d="m5 12 4.5 4.5L19 7"/>',
  back: '<path d="M19 12H5M11 18l-6-6 6-6"/>',
};

export function Icon({ name }: { name: string }) {
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" dangerouslySetInnerHTML={{ __html: ICONS[name] ?? "" }} />;
}

export function TypeTag({ type }: { type: string }) {
  return (
    <span className="type-tag" style={{ ["--tc" as string]: `var(${TYPE_META[type]?.color ?? "--muted-text"})` }}>
      {TYPE_META[type]?.short ?? type}
    </span>
  );
}

export function Dot({ color }: { color: string }) {
  return <span className="dot" style={{ color, background: color }} />;
}

export function SevChip({ sev, children }: { sev: Sev | "ok" | "ai"; children?: ReactNode }) {
  return <span className={`sev ${sev}`}>{children ?? sev}</span>;
}

export function IssueBadge({ counts, allowed }: { counts: IssueCounts | undefined; allowed?: Sev[] }) {
  const sev = worst(counts, allowed);
  if (!sev) return null;
  return <SevChip sev={sev}>{nf(issueTotal(counts, allowed))}</SevChip>;
}

export function Section({ title, children, aside }: { title?: ReactNode; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="section">
      {title ? (
        <h4>
          {title}
          {aside ? <span style={{ marginLeft: "auto" }}>{aside}</span> : null}
        </h4>
      ) : null}
      {children}
    </div>
  );
}

export function Kv({ pairs }: { pairs: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv">
      {pairs.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A citation chip: opens the cited file at the sheet cell, page or map feature in Inputs. */
export function Cite({ citation }: { citation: Citation }) {
  const { openSource, fileByPath } = useApp();
  const file = fileByPath(citation.file);
  const kind = file?.kind === "pdf" ? "pdf" : file?.kind === "gis_layer" ? "map" : "table";
  return (
    <button className="cite" title={file ? `Open ${citation.locator ?? "file"} in Inputs` : `${citation.file ?? ""} ${citation.locator ?? ""}`} disabled={!file} onClick={() => openSource(citation.file, citation.locator)}>
      <Icon name={kind} />
      <span className="mono">{citation.label}</span>
    </button>
  );
}

export function EntityLink({ id, label, type }: { id: string; label: string; type?: string }) {
  const { openEntity } = useApp();
  return (
    <button className="cite" style={{ border: 0, padding: 0, background: "none", fontWeight: 600, fontSize: 12.5 }} onClick={() => openEntity(id)}>
      {type ? <TypeTag type={type} /> : null}
      <span>{label}</span>
    </button>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" />
      {label}…
    </div>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div className="error-box" role="alert">
      <b>Could not load data.</b> {error}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, active, onChange }: { tabs: [T, ReactNode, number?][]; active: T; onChange: (key: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([key, label, n]) => (
        <button key={key} role="tab" aria-selected={key === active} onClick={() => onChange(key)}>
          {label}
          {n != null ? <span className="n">{nf(n)}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function fmtValue(value: unknown, unit?: string | null): string {
  if (value == null) return "—";
  if (typeof value !== "number") return String(value);
  if (unit === "fraction") return `${nf(value * 100, 2)}%`;
  const digits = Number.isInteger(value) ? 0 : Math.abs(value) < 10 ? 4 : 2;
  return `${nf(value, digits)}${unit && unit !== "count" ? ` ${unit}` : ""}`;
}
