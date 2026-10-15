// Inputs: every room file with its extracted schema, mappings, issues and cell/page/feature lineage.
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { api, q, useFetch, type CellLineage, type Chart, type ClaimCheck, type DocumentData, type FileDetail, type FileItem, type GeoFeature, type GeoLayer, type Geometry, type GridWindow, type Mapping, type OperationResult, type RebuildResult } from "../api";
import { useApp } from "../store";
import { EntityLink, ErrorBox, Icon, IssueBadge, Kv, Loading, Section, SevChip, Tabs, fmtValue } from "../ui";
import { basename, clip, colIndex, colLetter, methodLabel, nf, splitCell } from "../util";

const GROUPS: [string, (f: FileItem) => boolean][] = [
  ["New datasets", (f) => f.incoming],
  ["Workbooks", (f) => !f.incoming && (f.kind === "excel" || f.kind === "csv")],
  ["Documents", (f) => f.kind === "pdf"],
  ["Map layers", (f) => f.kind === "gis_layer"],
];
const ROWS = 60;
const COLS = 24;

function fileIcon(kind: string): string {
  return kind === "pdf" ? "pdf" : kind === "gis_layer" ? "map" : "table";
}

function ruleSev(rule: string): "blocking" | "warning" | "info" {
  return ["UNIT_ASSIGNMENT_CONFLICT", "OWNERSHIP_VALUE_CONFLICT", "VALUE_FIELD_CONFLICT"].includes(rule) ? "blocking" : ["CROSSWALK_MISSING", "FORMULA_CACHE_MISSING"].includes(rule) ? "info" : "warning";
}

function Upload() {
  const { refresh, patch, notify } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const send = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.upload<RebuildResult>("/api/uploads", file);
      const proposals = result.proposals ?? [];
      refresh();
      patch({ fileId: result.file_id as string, sheet: null, cell: null, side: "mappings" });
      notify(`${file.name}: ${proposals.length} field mappings proposed (${proposals.filter((p) => p.status === "approved").length} approved by header rules, ${proposals.filter((p) => p.status === "proposed").length} awaiting review).`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <div className="upload">
      <b>Add a dataset</b>
      <div className="small muted">Upload a new .xlsx or .csv. The pipeline profiles it, proposes field mappings to the catalog (header rules, key-value overlap, then the model), and waits for your approval before facts enter the graph.</div>
      <input ref={input} type="file" accept=".xlsx,.csv" hidden onChange={(e) => e.target.files?.[0] && send(e.target.files[0])} />
      <button className="btn primary" disabled={busy} onClick={() => input.current?.click()}>
        {busy ? <span className="spinner" /> : <Icon name="upload" />}
        {busy ? "Profiling and proposing…" : "Upload dataset"}
      </button>
      {error ? <div className="small" style={{ color: "hsl(var(--blocking))", marginTop: 6 }}>{error}</div> : null}
    </div>
  );
}

function FileList({ current }: { current: string }) {
  const { files, patch } = useApp();
  return (
    <nav className="files" aria-label="Data room files">
      <Upload />
      {GROUPS.map(([group, test]) => {
        const list = files.filter(test);
        if (!list.length) return null;
        return (
          <div key={group}>
            <h3>{`${group} · ${list.length}`}</h3>
            {list.map((f) => {
              const rules = Object.keys(f.issues);
              const uncached = f.sheets.reduce((s, d) => s + d.uncached_formulas, 0);
              return (
                <button key={f.file_id} className="file" aria-current={f.file_id === current} onClick={() => patch({ fileId: f.file_id, sheet: f.sheets[0]?.sheet ?? null, cell: null, page: 1, figure: null, feature: null })}>
                  <Icon name={fileIcon(f.kind)} />
                  <span className="name">{basename(f.path)}</span>
                  <span className="meta">
                    {`${nf(f.size_bytes / 1024)} KB`}
                    {f.kind === "pdf" ? ` · ${f.pages} pages` : f.sheets.length ? ` · ${f.sheets.length} sheet${f.sheets.length > 1 ? "s" : ""}` : f.sidecars ? ` · ${f.sidecars + 1}-file bundle` : ""}
                    {rules.length ? <SevChip sev={rules.map(ruleSev).sort()[0]}>{`${rules.length} rule${rules.length > 1 ? "s" : ""}`}</SevChip> : <SevChip sev="ok">parsed</SevChip>}
                    {uncached ? <SevChip sev="warning">{`${nf(uncached)} uncached`}</SevChip> : null}
                  </span>
                </button>
              );
            })}
          </div>
        );
      })}
    </nav>
  );
}

/** Mapping proposals for a file, with approve/reject and rebuild. Used for new datasets and any file with proposals. */
export function MappingsPanel({ detail }: { detail: FileDetail }) {
  const { refresh, notify, room } = useApp();
  const [decided, setDecided] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const key = (m: Mapping) => `${m.field_id}|${m.target}`;
  const status = (m: Mapping) => decided[key(m)] ?? m.status;
  const decide = async (m: Mapping, next: "approved" | "rejected") => {
    await api.post("/api/mappings/decision", { field_id: m.field_id, target: m.target, status: next, reviewer: "reviewer", reason: next === "approved" ? "approved in UI" : "rejected in UI" });
    setDecided((d) => ({ ...d, [key(m)]: next }));
  };
  const rebuild = async () => {
    setBusy(true);
    const before = room?.counts;
    try {
      const result = await api.post<RebuildResult>("/api/rebuild");
      refresh();
      const added = result.counts.facts - (before?.facts ?? result.counts.facts);
      notify(`Rebuilt snapshot ${result.snapshot_id}: ${added >= 0 ? "+" : ""}${nf(added)} facts, ${nf(result.counts.issues)} issues.`);
    } catch (e) {
      notify(`Rebuild failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };
  const order = { proposed: 0, approved: 1, rejected: 2 } as Record<string, number>;
  const list = [...detail.mappings].sort((a, b) => (order[status(a)] ?? 3) - (order[status(b)] ?? 3) || a.column.localeCompare(b.column));
  const pending = list.filter((m) => status(m) === "proposed").length;
  const changed = Object.keys(decided).length;
  return (
    <div>
      <Section title={`Field mappings · ${list.length}`} aside={pending ? <SevChip sev="warning">{`${pending} to review`}</SevChip> : <SevChip sev="ok">reviewed</SevChip>}>
        <div className="small muted" style={{ marginBottom: 8 }}>Each source column maps to a catalog property, measure, key or dimension. Approved mappings produce facts with cell citations on the next rebuild; rejections are remembered for this header.</div>
        <button className="btn primary" disabled={busy} onClick={rebuild}>
          {busy ? <span className="spinner" /> : <Icon name="refresh" />}
          {busy ? "Rebuilding…" : changed ? `Rebuild with ${changed} decision${changed > 1 ? "s" : ""}` : "Rebuild snapshot"}
        </button>
      </Section>
      <div className="section">
        {list.length ? list.map((m) => {
          const s = status(m);
          return (
            <div key={key(m)} className="proposal">
              <div className="head">
                <span className="mono small">{m.column}</span>
                <b>{m.header}</b>
                <SevChip sev={s === "approved" ? "ok" : s === "rejected" ? "blocking" : "warning"}>{s}</SevChip>
              </div>
              <div className="target">→ {m.target} <span className="muted">({m.kind})</span></div>
              <div className="why">
                <SevChip sev={m.method === "model" ? "ai" : "info"}>{methodLabel(m)}</SevChip> {m.match_rate ? `${m.match_rate} values match · ` : ""}confidence {nf(m.confidence, 2)} · {m.rationale}
              </div>
              {s === "proposed" ? (
                <div className="acts">
                  <button className="btn primary" onClick={() => decide(m, "approved")}><Icon name="check" />Approve</button>
                  <button className="btn" onClick={() => decide(m, "rejected")}>Reject</button>
                </div>
              ) : null}
            </div>
          );
        }) : <div className="muted small">No mappings for this file.</div>}
      </div>
    </div>
  );
}

function FileIssues({ file }: { file: FileItem }) {
  const { go } = useApp();
  const rules = Object.entries(file.issues).sort((a, b) => b[1] - a[1]);
  return (
    <Section title="Issues citing this file">
      {rules.length ? (
        <ul className="list">
          {rules.map(([rule, count]) => (
            <li key={rule}>
              <SevChip sev={ruleSev(rule)} />
              <div style={{ flex: 1 }}><b>{rule}</b></div>
              <span className="mono">{nf(count)}</span>
              <button className="btn" onClick={() => go("review", { rule, issueId: null })}>Review</button>
            </li>
          ))}
        </ul>
      ) : <div className="muted small">No reconciliation issues cite this file.</div>}
    </Section>
  );
}

function SheetView({ file, detail }: { file: FileItem; detail: FileDetail }) {
  const { nav, patch, version, openDrawer } = useApp();
  const sheet = file.sheets.find((s) => s.sheet === nav.sheet) ?? file.sheets[0];
  const [anchor, setAnchor] = useState<[number, number]>([1, 1]);
  const [goto, setGoto] = useState("");
  useEffect(() => {
    if (nav.cell) {
      const [col, row] = splitCell(nav.cell);
      const c = colIndex(col);
      setAnchor(([r0, c0]) => (row >= r0 && row < r0 + ROWS && c >= c0 && c < c0 + COLS ? [r0, c0] : [Math.max(1, row - 12), Math.max(1, c - 6)]));
    } else setAnchor([1, 1]);
  }, [nav.cell, sheet?.sheet]);
  const [r0, c0] = anchor;
  const wrap = useRef<HTMLDivElement>(null);
  const grid = useFetch<GridWindow>(sheet ? `/api/files/${file.file_id}/grid?${q({ sheet: sheet.sheet, r0, r1: r0 + ROWS - 1, c0, c1: c0 + COLS - 1 })}` : null, version);
  useEffect(() => {
    wrap.current?.querySelector("td.sel")?.scrollIntoView({ block: "center", inline: "center" });
  }, [grid.data, nav.cell]);
  const tables = Object.values(detail.tables).filter((t) => t.sheet === sheet?.sheet);
  const headerOf = (letter: string) => tables.map((t) => t.headers[letter]).find(Boolean)?.join(" › ") ?? null;
  const mappingOf = (letter: string) => detail.mappings.find((m) => m.column === letter && tables.some((t) => t.dataset_id === m.dataset_id));
  const headerRows = new Set(tables.flatMap((t) => t.header_rows));
  if (!sheet) return <div className="note">This file has no readable sheets.</div>;
  const data = grid.data;
  const cols = data ? Array.from({ length: data.c1 - data.c0 + 1 }, (_, k) => colLetter(data.c0 + k)) : [];
  const [selCol, selRow] = nav.cell ? splitCell(nav.cell) : [null, null];
  return (
    <div className="sheet-view">
      <div className="grid-controls">
        <span>{`Rows ${nf(r0)}–${nf(Math.min(r0 + ROWS - 1, data?.max_row ?? r0))} of ${nf(sheet.rows)} · columns ${colLetter(c0)}–${colLetter(Math.min(c0 + COLS - 1, data?.max_col ?? c0))} of ${colLetter(sheet.columns)}`}</span>
        <button className="btn" disabled={r0 <= 1} onClick={() => setAnchor([Math.max(1, r0 - ROWS), c0])}>▲ rows</button>
        <button className="btn" disabled={!data || r0 + ROWS > data.max_row} onClick={() => setAnchor([r0 + ROWS, c0])}>▼ rows</button>
        <button className="btn" disabled={c0 <= 1} onClick={() => setAnchor([r0, Math.max(1, c0 - COLS)])}>◀ cols</button>
        <button className="btn" disabled={!data || c0 + COLS > data.max_col} onClick={() => setAnchor([r0, c0 + COLS])}>cols ▶</button>
        <form onSubmit={(e) => { e.preventDefault(); const v = goto.trim().toUpperCase(); if (/^[A-Z]{1,3}\d{1,6}$/.test(v)) patch({ cell: v }); }} style={{ display: "flex", gap: 6 }}>
          <input aria-label="Go to cell" placeholder="Go to KY2" value={goto} onChange={(e) => setGoto(e.target.value)} />
        </form>
        <span style={{ marginLeft: "auto" }}><span className="line" style={{ borderTopColor: "hsl(var(--ok))", width: 14 }} />mapped <span className="line" style={{ borderTopColor: "hsl(var(--warning))", width: 14, marginLeft: 8 }} />proposed</span>
      </div>
      {sheet.uncached_formulas ? <div className="note warn">{`${nf(sheet.uncached_formulas)} of ${nf(sheet.formula_cells)} formulas have no cached value. They are flagged, never read as zero (FORMULA_CACHE_MISSING).`}</div> : null}
      {grid.error ? <ErrorBox error={grid.error} /> : !data ? <Loading label="Reading sheet" /> : (
        <div className="grid-wrap" ref={wrap}>
          <table className="grid">
            <thead>
              <tr>
                <th className="rown" />
                {cols.map((c) => <th key={c} className={c === selCol ? "col-sel" : ""}>{c}</th>)}
              </tr>
              {tables.length ? (
                <tr className="names">
                  <th className="rown">hdr</th>
                  {cols.map((c) => {
                    const h = headerOf(c);
                    return <th key={c} className={c === selCol ? "col-sel" : ""} title={h ?? ""}>{h ? clip(h, 24) : ""}</th>;
                  })}
                </tr>
              ) : null}
            </thead>
            <tbody>
              {data.rows.map((row, i) => {
                const r = data.r0 + i;
                const formulas = new Set(data.formulas[i]);
                return (
                  <tr key={r}>
                    <th className="rown">{r}</th>
                    {row.map((v, k) => {
                      const c = cols[k];
                      const mapping = mappingOf(c);
                      const isNum = typeof v === "number";
                      const formula = formulas.has(data.c0 + k);
                      let cls = `${isNum ? "num" : ""}${headerRows.has(r) ? " hdr" : ""}`;
                      if (mapping && !headerRows.has(r)) cls += mapping.status === "approved" ? " mapped" : mapping.status === "proposed" ? " proposed" : "";
                      if (mapping && /dcf10_(ky|mf)$/.test(mapping.target) && !headerRows.has(r)) cls += " c-block";
                      if (formula && v == null) cls += " formula";
                      if (c === selCol && r === selRow) cls += " sel";
                      const shown = v == null ? (formula ? "=ƒ (no cache)" : "") : isNum ? (Number.isInteger(v) ? (Math.abs(v as number) > 1e9 ? String(v) : nf(v)) : nf(v, Math.abs(v as number) < 10 ? 4 : 2)) : String(v);
                      return (
                        <td key={c} className={cls} title={`${c}${r}`} onClick={() => patch({ cell: `${c}${r}`, side: "fields" })} onDoubleClick={() => openDrawer({ kind: "cell", fileId: file.file_id, sheet: sheet.sheet, cell: `${c}${r}`, value: v })}>
                          {shown}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function CellDetails({ fileId, sheet, cell, value, compact }: { fileId: string; sheet: string; cell: string; value?: unknown; compact?: boolean }) {
  const { version, openEntity, go, openDrawer } = useApp();
  const lineage = useFetch<CellLineage>(`/api/files/${fileId}/lineage?${q({ sheet, cell })}`, version);
  const data = lineage.data;
  if (lineage.error) return <ErrorBox error={lineage.error} />;
  if (!data) return <Loading label="Tracing lineage" />;
  const m = data.mapping;
  const shown = value !== undefined ? value : data.value;
  return (
    <div>
      <Section title={`Cell ${sheet}!${cell}`} aside={compact ? <button className="btn" onClick={() => openDrawer({ kind: "cell", fileId, sheet, cell, value: shown })}>Open lineage</button> : null}>
        <Kv pairs={[
          ["Value", <b className="mono">{shown == null ? "(empty)" : typeof shown === "number" ? nf(shown, Number.isInteger(shown) ? 0 : 4) : String(shown)}</b>],
          ["Header", m?.header ?? "—"],
          ["Maps to", m ? <span className="mono">{m.target}</span> : "Not mapped"],
          ["Method", m ? <span>{methodLabel(m)} · <SevChip sev={m.status === "approved" ? "ok" : m.status === "rejected" ? "blocking" : "warning"}>{m.status}</SevChip></span> : "—"],
          ["Rationale", m?.rationale ?? "—"],
        ]} />
      </Section>
      <Section title={`Facts from this cell · ${data.facts.length}`}>
        {data.facts.length ? (
          <table className="simple">
            <thead><tr><th>Subject</th><th>Measure</th><th>Dims</th><th className="num">Value</th></tr></thead>
            <tbody>
              {data.facts.slice(0, 12).map((f, i) => (
                <tr key={i}>
                  <td><button className="cite" style={{ border: 0, padding: 0, background: "none" }} onClick={() => openEntity(f.subject)}>{clip(f.subject, 26)}</button></td>
                  <td className="mono small">{f.measure}</td>
                  <td className="small">{[f.zone, f.period?.slice(0, 7), f.item].filter(Boolean).join(" · ") || "—"}</td>
                  <td className="num">{fmtValue(f.value, f.unit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="small muted">No facts cite this exact cell{data.entities.length ? "; the row feeds the entities below" : ""}.</div>}
      </Section>
      {data.entities.length ? (
        <Section title={`Feeds entities · ${data.entities.length}`}>
          <ul className="list">
            {data.entities.slice(0, 8).map((n) => (
              <li key={n.id}><EntityLink id={n.id} label={n.label} type={n.type} /><span style={{ marginLeft: "auto" }}><IssueBadge counts={n.issues} /></span></li>
            ))}
          </ul>
        </Section>
      ) : null}
      {data.issues.length ? (
        <Section title={`Issues citing this cell · ${data.issues.length}`}>
          <ul className="list">
            {data.issues.map((i) => (
              <li key={i.issue_id}>
                <SevChip sev={i.severity} />
                <div style={{ flex: 1 }}><b>{i.rule}</b><div className="small muted">{i.detail}</div></div>
                <button className="btn" onClick={() => go("review", { rule: i.rule, issueId: i.issue_id })}>Review</button>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}

function SheetSide({ file, detail }: { file: FileItem; detail: FileDetail }) {
  const { nav, patch } = useApp();
  const sheet = file.sheets.find((s) => s.sheet === nav.sheet) ?? file.sheets[0];
  const tables = Object.values(detail.tables).filter((t) => t.sheet === sheet?.sheet);
  const datasets = new Set(tables.map((t) => t.dataset_id));
  const mappings = detail.mappings.filter((m) => datasets.has(m.dataset_id));
  const proposals = detail.mappings.filter((m) => m.status === "proposed").length;
  const tabs: [string, ReactNode, number?][] = [["fields", "Fields", mappings.length], ["mappings", "Mappings", proposals || undefined], ["issues", "Issues", Object.keys(file.issues).length]];
  const side = tabs.some(([k]) => k === nav.side) ? nav.side : "fields";
  return (
    <>
      <Tabs tabs={tabs} active={side} onChange={(k) => patch({ side: k })} />
      {side === "fields" ? (
        <div>
          {nav.cell && sheet ? <CellDetails key={`${sheet.sheet}!${nav.cell}`} fileId={file.file_id} sheet={sheet.sheet} cell={nav.cell} compact /> : <div className="section small muted">Select a cell to see its field mapping, the facts it produced and the entities it feeds. Double-click a cell for the full lineage.</div>}
          <Section title="Dataset profile">
            <Kv pairs={[
              ["Sheet", sheet?.sheet],
              ["Used range", sheet ? `${nf(sheet.rows)} rows × ${sheet.columns} columns` : "—"],
              ["Datasets", tables.length ? tables.map((t) => `${t.dataset_id} (${t.family}, ${nf(t.records)} records, header rows ${t.header_rows.join(",")})`).join("; ") : "none detected"],
              ["Formulas", sheet ? `${nf(sheet.formula_cells)} (${nf(sheet.uncached_formulas)} uncached)` : "—"],
            ]} />
          </Section>
          <Section title={`Mapped fields · ${mappings.length}`}>
            {mappings.length ? (
              <table className="simple">
                <thead><tr><th>Col</th><th>Header</th><th>Maps to</th><th>Status</th></tr></thead>
                <tbody>
                  {mappings.map((m) => {
                    const table = tables.find((t) => t.dataset_id === m.dataset_id);
                    const first = (table ? Math.max(...table.header_rows) : 1) + 1;
                    return (
                      <tr key={`${m.field_id}|${m.target}`} className={`clickable${nav.cell?.startsWith(m.column) && /\d/.test(nav.cell.slice(m.column.length, m.column.length + 1)) ? " warn" : ""}`} onClick={() => patch({ cell: `${m.column}${first}` })}>
                        <td className="mono">{m.column}</td>
                        <td>{clip(m.header, 26)}</td>
                        <td className="mono small">{m.target}</td>
                        <td><SevChip sev={m.status === "approved" ? "ok" : m.status === "rejected" ? "blocking" : "warning"}>{m.status}</SevChip></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : <div className="small muted">No catalog mappings for this sheet. Its values are staged in silver and can be mapped later.</div>}
          </Section>
        </div>
      ) : side === "mappings" ? <MappingsPanel detail={detail} /> : <FileIssues file={file} />}
    </>
  );
}

function box(polygon: number[], width: number, height: number): CSSProperties {
  const xs = polygon.filter((_, k) => k % 2 === 0);
  const ys = polygon.filter((_, k) => k % 2 === 1);
  const x0 = Math.max(0, Math.min(...xs));
  const y0 = Math.max(0, Math.min(...ys));
  const x1 = Math.min(width, Math.max(...xs));
  const y1 = Math.min(height, Math.max(...ys));
  return { left: `${(x0 / width) * 100}%`, top: `${(y0 / height) * 100}%`, width: `${((x1 - x0) / width) * 100}%`, height: `${((y1 - y0) / height) * 100}%` };
}

const checkClass = (c: ClaimCheck | undefined) => (c?.check === "match" ? "ok" : c?.check === "mismatch" ? "mismatch" : "");

function PdfView({ file, doc, checks }: { file: FileItem; doc: DocumentData; checks: FileDetail["claim_checks"] }) {
  const { nav, patch, openDrawer } = useApp();
  const [layers, setLayers] = useState({ text: false, figures: true, claims: true });
  const page = doc.pages.find((p) => p.page === nav.page) ?? doc.pages[0];
  const figures = doc.figures.filter((f) => f.page === page.page);
  const claims = doc.claims.filter((c) => c.page === page.page);
  return (
    <div className="pdf">
      <div className="thumbs">
        {doc.pages.map((p) => (
          <button key={p.page} aria-current={p.page === page.page} aria-label={`Page ${p.page}`} onClick={() => patch({ page: p.page, figure: null })}>
            <img src={`/api/files/${file.file_id}/pages/${p.page}.png`} alt="" loading="lazy" />
            <span>{p.page}</span>
          </button>
        ))}
      </div>
      <div>
        <div className="layer-toggles">
          <span className="muted small" style={{ alignSelf: "center" }}>Overlays</span>
          {([["text", `Text lines (${page.lines.length})`], ["figures", `Figures (${figures.length})`], ["claims", `Claims (${claims.length})`]] as const).map(([k, label]) => (
            <button key={k} className="chip" aria-pressed={layers[k]} onClick={() => setLayers((l) => ({ ...l, [k]: !l[k] }))}>{label}</button>
          ))}
        </div>
        <div className={`page${layers.text ? " layer-lines" : ""}`}>
          <img src={`/api/files/${file.file_id}/pages/${page.page}.png`} alt={`${basename(file.path)} page ${page.page}`} />
          {layers.text ? page.lines.map((l, i) => <div key={`l${i}`} className="box line" style={box(l.polygon, page.width, page.height)} title={l.content} />) : null}
          {layers.figures ? figures.map((f) => (
            <div key={f.id} className={`box fig${nav.figure === f.id ? " sel" : ""}`} style={box(f.polygon, page.width, page.height)} title="Click to select; double-click for chart data" onClick={() => patch({ figure: f.id, side: "figures" })} onDoubleClick={() => openDrawer({ kind: "figure", fileId: file.file_id, figure: f.id })}>
              <span className="tag">{`Figure ${f.id} · ${f.chart?.chart_type ?? "figure"}${f.crop.startsWith("page") ? " · region rotated" : ""}`}</span>
            </div>
          )) : null}
          {layers.claims ? claims.map((c) => {
            const check = checks[c.claim_id];
            return (
              <div key={c.claim_id} className={`box claim ${checkClass(check)}`} style={box(c.polygon, page.width, page.height)} title={`${c.raw}: ${check?.check ?? "not checked"}`} onClick={() => patch({ side: "claims" })}>
                <span className="tag">{check?.check === "match" ? "✓ matches" : check?.check === "mismatch" ? "✗ mismatch" : "! check"}</span>
              </div>
            );
          }) : null}
        </div>
      </div>
    </div>
  );
}

function MiniChart({ chart }: { chart: Chart }) {
  const series = chart.series.filter((s) => s.points.length);
  if (!series.length) return null;
  const W = 420;
  const H = 150;
  const pad = 26;
  const max = Math.max(...series.flatMap((s) => s.points.map((p) => p.y ?? 0)), 1);
  const n = Math.max(...series.map((s) => s.points.length));
  const colors = ["hsl(var(--primary))", "hsl(var(--warning))"];
  const bar = /bar/i.test(chart.chart_type);
  return (
    <svg className="mini-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Extracted ${chart.chart_type}`}>
      <line x1={pad} y1={H - pad} x2={W - 6} y2={H - pad} stroke="hsl(var(--border))" />
      {series.map((s, si) =>
        bar ? (
          s.points.map((p, k) => {
            const bw = (W - pad - 6) / n / (series.length + 0.6);
            const h = ((p.y ?? 0) / max) * (H - pad - 10);
            return <rect key={`${si}-${k}`} x={pad + k * ((W - pad - 6) / n) + si * bw} y={H - pad - h} width={bw * 0.92} height={h} fill={colors[si % 2]}><title>{`${s.name} ${p.x}: ${p.y}`}</title></rect>;
          })
        ) : (
          <polyline key={si} fill="none" stroke={colors[si % 2]} strokeWidth={2} points={s.points.map((p, k) => `${pad + (k / Math.max(n - 1, 1)) * (W - pad - 6)},${H - pad - ((p.y ?? 0) / max) * (H - pad - 10)}`).join(" ")} />
        ),
      )}
      <text x={2} y={12}>{nf(max)}</text>
      <text x={pad} y={H - 8}>{String(series[0].points[0].x)}</text>
      <text x={W - 40} y={H - 8}>{String(series[0].points[series[0].points.length - 1].x)}</text>
    </svg>
  );
}

export function FigureDetail({ fileId, doc, figureId }: { fileId: string; doc: DocumentData; figureId: string }) {
  const { version } = useApp();
  const figure = doc.figures.find((f) => f.id === figureId) ?? doc.figures[0];
  const ownership = /ownership/i.test(figure?.chart?.title ?? "");
  const [check, setCheck] = useState<OperationResult | null>(null);
  useEffect(() => {
    if (!ownership) return;
    let live = true;
    api.post<OperationResult>("/api/graph/operations/claim_check", {}).then((r) => live && setCheck(r));
    return () => { live = false; };
  }, [ownership, version]);
  if (!figure) return <div className="section muted">No figures in this document.</div>;
  const chart = figure.chart;
  const rows = (check?.data.chart_checks as { figure: string; rows: { zone: string; chart: number | null; read_as: string; workbook: number; delta: number | null }[] }[] | undefined)?.find((c) => c.figure === figure.id)?.rows;
  return (
    <div>
      <Section title={`Figure ${figure.id} · page ${figure.page}`}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
          <SevChip sev="ai">{figure.status}</SevChip>
          <SevChip sev="warning">approximate</SevChip>
          {figure.crop.startsWith("page") ? <SevChip sev="info">full-page crop</SevChip> : null}
        </div>
        {chart ? <Kv pairs={[["Chart", chart.chart_type], ["Title", chart.title ?? "—"], ["Unit", chart.unit ?? "—"], ["Series", chart.series.map((s) => `${s.name} (${s.points.length})`).join(", ") || "—"]]} /> : null}
        {chart ? <MiniChart chart={chart} /> : null}
        {chart?.notes ? <div className="small muted" style={{ marginTop: 6 }}>{chart.notes}</div> : null}
      </Section>
      {rows ? (
        <Section title="Cross-check against Unit Details (operational WI)">
          <table className="simple">
            <thead><tr><th>Zone</th><th className="num">Chart %</th><th className="num">Workbook %</th><th className="num">Δ</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.zone} className={r.delta == null || Math.abs(r.delta) > 0.5 ? "flag" : ""}>
                  <td>{r.zone}{r.read_as !== r.zone ? <span className="muted small">{` (read "${r.read_as}")`}</span> : null}</td>
                  <td className="num">{nf(r.chart, 1)}</td>
                  <td className="num">{nf(r.workbook, 1)}</td>
                  <td className="num">{r.delta == null ? "—" : `${r.delta > 0 ? "+" : ""}${nf(r.delta, 1)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      ) : chart?.series.length ? (
        <Section title="Extracted values">
          <table className="simple">
            <thead><tr><th>x</th>{chart.series.map((s) => <th key={s.name} className="num">{clip(s.name, 16)}</th>)}</tr></thead>
            <tbody>
              {chart.series[0].points.slice(0, 16).map((p, k) => (
                <tr key={k}><td>{p.x}</td>{chart.series.map((s) => <td key={s.name} className="num">{nf(s.points[k]?.y, 1)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </Section>
      ) : null}
      <Section title="Crop sent to the vision model">
        <img src={`/api/files/${fileId}/figures/${figure.id}.png`} alt={`Crop of figure ${figure.id}`} style={{ width: "100%", borderRadius: 6, background: "#fff" }} />
        <div className="small muted" style={{ marginTop: 6 }}>{`Crop source: ${figure.crop}. Chart values are read from pixels, so they are approximate and never override workbook facts.`}</div>
      </Section>
    </div>
  );
}

function PdfSide({ file, detail }: { file: FileItem; detail: FileDetail }) {
  const { nav, patch, openEntity } = useApp();
  const doc = detail.document as DocumentData;
  const page = doc.pages.find((p) => p.page === nav.page) ?? doc.pages[0];
  const claims = doc.claims.filter((c) => c.page === page.page);
  const tabs: [string, ReactNode, number?][] = [["claims", "Claims", doc.claims.length], ["figures", "Figures", doc.figures.length], ["text", "Text"], ["issues", "Issues", Object.keys(file.issues).length]];
  const side = tabs.some(([k]) => k === nav.side) ? nav.side : "claims";
  const figureId = nav.figure ?? doc.figures.find((f) => f.page === page.page)?.id ?? doc.figures[0]?.id;
  return (
    <>
      <Tabs tabs={tabs} active={side} onChange={(k) => patch({ side: k })} />
      {side === "claims" ? (
        <div>
          <Section title="Layout pass">
            <Kv pairs={[["Model", `${doc.model} · API ${doc.api_version}`], ["Source", doc.source], ["Pages", String(doc.pages.length)], ["Paragraphs", nf(doc.paragraphs.length)], ["Figures", nf(doc.figures.length)], ["Claims", nf(doc.claims.length)]]} />
          </Section>
          <Section title={`Headline claims${claims.length ? ` on page ${page.page}` : ""}`}>
            {(claims.length ? claims : doc.claims).length ? (
              <ul className="list">
                {(claims.length ? claims : doc.claims).map((c) => {
                  const check = detail.claim_checks[c.claim_id];
                  return (
                    <li key={c.claim_id}>
                      <SevChip sev={check?.check === "match" ? "ok" : check?.check === "mismatch" ? "blocking" : "warning"}>{check?.check ?? "unchecked"}</SevChip>
                      <div style={{ flex: 1 }}>
                        <b>{c.raw}</b>
                        <div className="small muted">{check?.computed != null ? `Room: ${nf(check.computed, 2)} (${check.computed_from})` : check?.computed_from ?? "Cannot be computed from the room."}</div>
                      </div>
                      {check?.entity ? <button className="btn" onClick={() => openEntity(check.entity)}>Claim</button> : null}
                    </li>
                  );
                })}
              </ul>
            ) : <div className="small muted">No headline claims detected.</div>}
          </Section>
        </div>
      ) : side === "figures" ? (
        <div>
          <div className="section" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {doc.figures.map((f) => <button key={f.id} className="chip" aria-pressed={f.id === figureId} onClick={() => patch({ figure: f.id, page: f.page })}>{`p${f.page} · ${f.id}`}</button>)}
          </div>
          {figureId ? <FigureDetail fileId={file.file_id} doc={doc} figureId={figureId} /> : null}
        </div>
      ) : side === "text" ? (
        <Section title={`Text on page ${page.page}`}>
          <ul className="list">
            {doc.paragraphs.filter((p) => p.page === page.page).slice(0, 30).map((p, i) => <li key={i}>{p.role ? <span className="chip">{p.role}</span> : null}<span>{p.content}</span></li>)}
          </ul>
        </Section>
      ) : <FileIssues file={file} />}
    </>
  );
}

type Shape = { layer: string; feature: GeoFeature; index: number };

function project(features: Shape[]) {
  const coords: number[][] = [];
  const walk = (g: Geometry) => {
    if (g.type === "Point") coords.push(g.coordinates);
    else if (g.type === "LineString") coords.push(...g.coordinates);
    else if (g.type === "Polygon" || g.type === "MultiLineString") g.coordinates.forEach((ring) => coords.push(...ring));
    else g.coordinates.forEach((poly) => poly.forEach((ring) => coords.push(...ring)));
  };
  features.forEach((s) => walk(s.feature.geometry));
  const lons = coords.map((c) => c[0]);
  const lats = coords.map((c) => c[1]);
  const [x0, x1, y0, y1] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  const kx = Math.cos((((y0 + y1) / 2) * Math.PI) / 180);
  const W = 1000;
  const H = ((y1 - y0) / Math.max((x1 - x0) * kx, 1e-9)) * W;
  const P = (c: number[]) => `${((c[0] - x0) / Math.max(x1 - x0, 1e-9)) * W},${((y1 - c[1]) / Math.max(y1 - y0, 1e-9)) * H}`;
  return { W, H, P };
}

export function geometryPaths(g: Geometry, P: (c: number[]) => string): { kind: "polygon" | "line"; points: string }[] {
  if (g.type === "Polygon") return [{ kind: "polygon", points: g.coordinates[0].map(P).join(" ") }];
  if (g.type === "MultiPolygon") return g.coordinates.map((poly) => ({ kind: "polygon" as const, points: poly[0].map(P).join(" ") }));
  if (g.type === "LineString") return [{ kind: "line", points: g.coordinates.map(P).join(" ") }];
  if (g.type === "MultiLineString") return g.coordinates.map((line) => ({ kind: "line" as const, points: line.map(P).join(" ") }));
  return [];
}

function MapView({ file, onPick, picked }: { file: FileItem; onPick: (s: Shape) => void; picked: string | null }) {
  const { version, openEntity, nav } = useApp();
  const unitsId = file.file_id === "gis-units" ? "gis-units" : "gis-units-pf";
  const units = useFetch<GeoLayer>(`/api/layers/${unitsId}`, version).data;
  const tracts = useFetch<GeoLayer>("/api/layers/gis-leasehold", version).data;
  const wells = useFetch<GeoLayer>("/api/layers/gis-pdp", version).data;
  const shapes = useMemo(() => {
    if (!units || !tracts || !wells) return null;
    const wrap = (layer: string, data: GeoLayer) => data.features.map((feature, index) => ({ layer, feature, index }));
    return [...wrap(unitsId, units), ...wrap("gis-leasehold", tracts), ...wrap("gis-pdp", wells)];
  }, [units, tracts, wells, unitsId]);
  useEffect(() => {
    if (nav.feature == null || !shapes) return;
    const s = shapes.find((x) => x.layer === file.file_id && x.index === nav.feature);
    if (s) onPick(s);
  }, [nav.feature, shapes, file.file_id]);
  if (!shapes) return <Loading label="Loading map layers" />;
  const { W, H, P } = project(shapes);
  const conflicts = shapes.filter((s) => s.layer === "gis-pdp" && (s.feature.properties.issues.blocking ?? 0) > 0).length;
  return (
    <div className="map" style={{ position: "relative" }}>
      <svg viewBox={`-10 -10 ${W + 20} ${H + 20}`} role="img" aria-label="Map of units, leasehold tracts and PDP laterals">
        {shapes.map((s) => {
          const id = s.feature.properties.entity;
          const hot = (s.feature.properties.issues.blocking ?? 0) > 0;
          const cls = s.layer === "gis-pdp" ? `lateral${hot ? " conflict" : ""}` : s.layer === "gis-leasehold" ? "tract" : `unit${hot && s.layer === "gis-units" ? " hot" : ""}`;
          return geometryPaths(s.feature.geometry, P).map((path, k) => {
            const props = { key: `${s.layer}-${s.index}-${k}`, className: `${cls}${id && id === picked ? " sel" : ""}`, points: path.points, onClick: () => onPick(s), onDoubleClick: () => id && openEntity(id) };
            const title = <title>{`${id ?? s.feature.properties.feature_id}${hot && s.layer === "gis-pdp" ? " — unit conflict" : ""}`}</title>;
            return path.kind === "polygon" ? <polygon {...props}>{title}</polygon> : <polyline {...props} fill="none">{title}</polyline>;
          });
        })}
      </svg>
      <div className="overlay map-legend">
        <span><span className="line" style={{ borderTopColor: "hsl(var(--type-unit))" }} />{`units (${units?.features.length})`}</span>
        <span><span className="line" style={{ borderTopColor: "hsl(var(--type-tract))" }} />{`tracts (${tracts?.features.length})`}</span>
        <span><span className="line" style={{ borderTopColor: "hsl(var(--type-well))" }} />{`laterals (${wells?.features.length})`}</span>
        <span><span className="line" style={{ borderTopColor: "hsl(var(--blocking))" }} />{`unit conflict (${conflicts})`}</span>
      </div>
    </div>
  );
}

function MapSide({ file, detail, picked }: { file: FileItem; detail: FileDetail; picked: Shape | null }) {
  const { nav, patch } = useApp();
  const dataset = detail.datasets[0];
  const tabs: [string, ReactNode, number?][] = [["fields", "Feature"], ["schema", "Attributes", dataset?.fields.length], ["issues", "Issues", Object.keys(file.issues).length]];
  const side = tabs.some(([k]) => k === nav.side) ? nav.side : "fields";
  const props = picked?.feature.properties;
  return (
    <>
      <Tabs tabs={tabs} active={side} onChange={(k) => patch({ side: k })} />
      {side === "fields" ? (
        props ? (
          <div>
            <Section title="Selected feature">
              <Kv pairs={[
                ["Entity", props.entity ? <EntityLink id={props.entity} label={props.entity} /> : "not linked"],
                ["Layer", picked?.layer],
                ["Feature", `#${picked?.index}`],
                ["Open issues", <IssueBadge counts={props.issues} />],
              ]} />
              <div className="small muted" style={{ marginTop: 6 }}>Double-click the feature for the entity inspector.</div>
            </Section>
            <Section title="Attributes">
              <Kv pairs={Object.entries(props).filter(([k]) => !["entity", "issues", "feature_id"].includes(k)).slice(0, 40).map(([k, v]) => [<span className="mono">{k}</span>, typeof v === "number" ? nf(v, Number.isInteger(v) ? 0 : 4) : String(v ?? "—")])} />
            </Section>
          </div>
        ) : <div className="section small muted">Click a lateral, unit or tract to select it; double-click for the entity inspector.</div>
      ) : side === "schema" ? (
        <div>
          <Section title="Layer">
            <Kv pairs={[["File", <span className="mono">{file.path}</span>], ["Features", nf(dataset?.record_count)], ["CRS", dataset?.crs ?? "—"], ["Bundle", `${file.sidecars + 1} files (.shp .shx .dbf .prj .cpg)`]]} />
          </Section>
          <Section title={`Attributes · ${dataset?.fields.length ?? 0}`}>
            <table className="simple">
              <thead><tr><th>Field</th><th>Type</th><th>Sample</th><th>Key?</th></tr></thead>
              <tbody>
                {dataset?.fields.slice(0, 60).map((f) => (
                  <tr key={f.field_id}><td className="mono">{f.column_ref}</td><td className="small">{f.inferred_type}</td><td className="small">{clip(f.samples[0], 16)}</td><td>{f.candidate_key ? <SevChip sev="ok">key</SevChip> : null}</td></tr>
                ))}
              </tbody>
            </table>
          </Section>
        </div>
      ) : <FileIssues file={file} />}
    </>
  );
}

export function Inputs() {
  const { nav, patch, version, files } = useApp();
  const file = files.find((f) => f.file_id === nav.fileId) ?? files.find((f) => f.file_id === "combocurve") ?? files[0];
  const detail = useFetch<FileDetail>(file ? `/api/files/${file.file_id}` : null, version);
  const [picked, setPicked] = useState<Shape | null>(null);
  useEffect(() => setPicked(null), [file?.file_id]);
  if (!file) return <Loading label="Loading files" />;
  const d = detail.data && detail.data.entry.file_id === file.file_id ? detail.data : null;
  let tabs: ReactNode = null;
  let body: ReactNode = <Loading label="Loading file" />;
  let side: ReactNode = null;
  if (detail.error) body = <ErrorBox error={detail.error} />;
  else if (d) {
    if (file.kind === "pdf" && d.document) {
      tabs = <Tabs tabs={d.document.pages.map((p) => [String(p.page), `Page ${p.page}`] as [string, ReactNode])} active={String(nav.page)} onChange={(k) => patch({ page: Number(k), figure: null })} />;
      body = <PdfView file={file} doc={d.document} checks={d.claim_checks} />;
      side = <PdfSide file={file} detail={d} />;
    } else if (file.kind === "gis_layer") {
      tabs = <Tabs tabs={[["map", "Map"]]} active="map" onChange={() => undefined} />;
      body = <MapView file={file} picked={picked?.feature.properties.entity ?? null} onPick={setPicked} />;
      side = <MapSide file={file} detail={d} picked={picked} />;
    } else {
      const sheet = file.sheets.find((s) => s.sheet === nav.sheet) ?? file.sheets[0];
      tabs = <Tabs tabs={file.sheets.map((s) => [s.sheet, s.sheet, s.rows] as [string, ReactNode, number?])} active={sheet?.sheet ?? ""} onChange={(k) => patch({ sheet: k, cell: null })} />;
      body = <SheetView file={file} detail={d} />;
      side = <SheetSide file={file} detail={d} />;
    }
  }
  return (
    <div className="inputs">
      <FileList current={file.file_id} />
      <section className="viewer" aria-label="File viewer">
        <div className="viewer-head">
          <h2>{basename(file.path)}</h2>
          <div className="meta">
            <span className="mono">{file.path}</span>
            <span>{`${nf(file.size_bytes / 1024, 1)} KB`}</span>
            <span className="mono">{`sha256 ${file.sha256.slice(0, 12)}…`}</span>
            {file.role ? <span>{`role: ${file.role}`}</span> : null}
            {file.as_of ? <span>{`as of ${file.as_of}`}</span> : null}
            {file.incoming ? <SevChip sev="info">uploaded</SevChip> : null}
          </div>
        </div>
        {tabs ?? <div className="tabs" />}
        <div className="view-body">{body}</div>
      </section>
      <aside className="side" aria-label="Extraction details">{side}</aside>
    </div>
  );
}
