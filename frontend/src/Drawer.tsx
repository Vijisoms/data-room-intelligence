// Inspector drawer opened by double-click: entity, entity type, sheet cell or document figure.
import { useEffect, useState, type ReactNode } from "react";
import { q, useFetch, type Catalog, type Fact, type FileDetail, type Interpret, type Link } from "./api";
import { useApp, type DrawerState } from "./store";
import { Cite, Dot, ErrorBox, Icon, IssueBadge, Kv, Loading, Section, SevChip, Tabs, TypeTag, fmtValue } from "./ui";
import { ZONES, basename, clip, issueTotal, nf, typeColor, worst } from "./util";
import { CellDetails, FigureDetail } from "./views/Inputs";
import { TypeSchema } from "./views/Schema";

function Shell({ tag, title, id, chips, actions, tabs, active, onTab, children }: { tag: ReactNode; title: string; id?: string; chips?: ReactNode; actions?: ReactNode; tabs?: [string, ReactNode, number?][]; active?: string; onTab?: (k: string) => void; children: ReactNode }) {
  const { closeDrawer } = useApp();
  return (
    <>
      <div className="drawer-head">
        <div className="row">
          {tag}
          {chips}
          <span style={{ flex: 1 }} />
          <button className="icon-btn" aria-label="Close details" onClick={closeDrawer} autoFocus><Icon name="x" /></button>
        </div>
        <h2 id="drawer-title">{title}</h2>
        {id ? <div className="id">{id}</div> : null}
        {actions ? <div className="acts">{actions}</div> : null}
      </div>
      {tabs && active && onTab ? <Tabs tabs={tabs} active={active} onChange={onTab} /> : <div />}
      <div className="drawer-body">{children}</div>
    </>
  );
}

function RelList({ links }: { links: Link[] }) {
  const { openEntity } = useApp();
  const groups = new Map<string, Link[]>();
  links.forEach((l) => {
    const key = `${l.direction === "out" ? "→" : "←"} ${l.kind}`;
    groups.set(key, [...(groups.get(key) ?? []), l]);
  });
  return (
    <div>
      {[...groups].map(([key, list]) => (
        <div key={key} style={{ marginBottom: 8 }}>
          <div className="small" style={{ fontWeight: 600, marginBottom: 4 }}>
            {`${key} · ${list.length}`}
            {list.some((l) => l.conflict) ? <span className="sev blocking" style={{ marginLeft: 6 }}>conflict</span> : null}
          </div>
          <ul className="list">
            {list.slice(0, 8).map((l, i) => (
              <li key={i}>
                <span style={{ marginTop: 5 }}><Dot color={typeColor(l.other.type)} /></span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <button className="cite" style={{ border: 0, padding: 0, background: "none", fontWeight: 600, fontSize: 12.5 }} onClick={() => openEntity(l.other.id)}>{l.other.label}</button>
                  <div className="small muted">{`${l.method} · ${l.locator ?? "—"}${l.props?.alias ? ` · alias ${String(l.props.alias)}` : ""}`}</div>
                </div>
                <IssueBadge counts={l.other.issues} />
              </li>
            ))}
            {list.length > 8 ? <li className="muted">{`+ ${list.length - 8} more`}</li> : null}
          </ul>
        </div>
      ))}
    </div>
  );
}

function UnitFacts({ facts }: { facts: Fact[] }) {
  const get = (zone: string, measure: string) => facts.find((f) => f.zone === zone && f.measure === measure)?.value;
  const rows = ZONES.map((z) => ({ z, acres: get(z, "net_acres"), wi: get(z, "operational_wi"), gwi: get(z, "gis_wi"), nri: get(z, "total_nri"), gnri: get(z, "gis_nri"), locs: get(z, "gross_locations_10k") }));
  const diffs = rows.filter((r) => r.wi != null && r.gwi != null && Math.abs(r.wi - r.gwi) > 0.0005).length;
  return (
    <div>
      {diffs ? <div className="note warn">{`${diffs} of ${ZONES.length} zones: GIS WI (2026-08-06 unit shapefile) differs from Unit Details operational WI → OWNERSHIP_VALUE_CONFLICT. Both values are kept.`}</div> : null}
      <div className="section" style={{ overflow: "auto" }}>
        <table className="facts">
          <thead><tr>{["Zone", "Net acres", "WI (workbook)", "WI (GIS)", "Δ WI", "NRI total", "NRI (GIS)", "10K locs"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>
            {rows.map((r) => {
              const d = r.wi != null && r.gwi != null ? r.gwi - r.wi : null;
              return (
                <tr key={r.z}>
                  <td>{r.z}</td><td>{nf(r.acres, 1)}</td><td>{nf(r.wi, 4)}</td><td>{nf(r.gwi, 4)}</td>
                  <td className={d != null && Math.abs(d) > 0.0005 ? "diff" : ""}>{d == null ? "—" : `${d > 0 ? "+" : ""}${nf(d, 4)}`}</td>
                  <td>{nf(r.nri, 4)}</td><td>{nf(r.gnri, 4)}</td><td>{nf(r.locs, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ProductionFacts({ facts }: { facts: Fact[] }) {
  const months = new Map<string, Record<string, Fact>>();
  facts.filter((f) => ["oil_bbl", "gas_mcf", "water_bbl", "days_on"].includes(f.measure)).forEach((f) => {
    const key = f.period ?? "—";
    months.set(key, { ...(months.get(key) ?? {}), [f.measure]: f });
  });
  if (!months.size) return null;
  const rows = [...months].sort((a, b) => a[0].localeCompare(b[0]));
  const last = rows[rows.length - 1][1];
  const anyFact = Object.values(last)[0];
  return (
    <Section title={`Monthly production · ${rows.length} months`}>
      <div className="small muted" style={{ marginBottom: 6 }}>From an approved new dataset: <Cite citation={{ file: anyFact.file ?? null, locator: anyFact.locator ?? null, label: `${basename(anyFact.file)} ${anyFact.locator}` }} /></div>
      <table className="simple">
        <thead><tr><th>Month</th><th className="num">Oil bbl</th><th className="num">Gas mcf</th><th className="num">Water bbl</th><th className="num">Days</th></tr></thead>
        <tbody>
          {rows.map(([month, m]) => (
            <tr key={month}><td>{month.slice(0, 7)}</td><td className="num">{nf(m.oil_bbl?.value)}</td><td className="num">{nf(m.gas_mcf?.value)}</td><td className="num">{nf(m.water_bbl?.value)}</td><td className="num">{nf(m.days_on?.value)}</td></tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

function GenericFacts({ facts, total }: { facts: Fact[]; total: number }) {
  const rest = facts.filter((f) => !["oil_bbl", "gas_mcf", "water_bbl", "days_on"].includes(f.measure));
  if (!rest.length) return null;
  return (
    <Section title={`Facts · ${nf(total)}${total > facts.length ? ` (first ${facts.length})` : ""}`}>
      <table className="simple">
        <thead><tr><th>Measure</th><th>Dims</th><th className="num">Value</th><th>Source</th></tr></thead>
        <tbody>
          {rest.slice(0, 150).map((f, i) => (
            <tr key={i} className={f.quality ? "warn" : ""}>
              <td className="mono small">{f.measure}</td>
              <td className="small">{[f.zone, f.period?.slice(0, 7), f.item ? clip(f.item, 22) : null].filter(Boolean).join(" · ") || "—"}</td>
              <td className="num">{fmtValue(f.value, f.unit)}</td>
              <td>{f.file ? <Cite citation={{ file: f.file, locator: f.locator ?? null, label: f.locator ?? "file" }} /> : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

function EntityDrawer({ id }: { id: string }) {
  const { version, focusGraph, ask, go, openSource, closeDrawer } = useApp();
  const [tab, setTab] = useState("overview");
  useEffect(() => setTab("overview"), [id]);
  const result = useFetch<Interpret>(`/api/graph/viz/interpret?${q({ id })}`, version);
  if (result.error) return <Shell tag={<span className="chip">Entity</span>} title={id}><ErrorBox error={result.error} /></Shell>;
  const d = result.data;
  if (!d || d.node.id !== id) return <Shell tag={<span className="chip">Entity</span>} title={id}><Loading label="Loading entity" /></Shell>;
  const n = d.node;
  const open = d.issues.filter((i) => i.status === "open");
  const sev = worst(n.issues);
  const sources = new Map<string, { file: string; locator: string | null; label: string }>();
  const addSource = (file: string | null | undefined, locator: string | null | undefined, label: string) => {
    if (!file) return;
    const key = `${file}|${locator}`;
    if (!sources.has(key)) sources.set(key, { file, locator: locator ?? null, label });
  };
  addSource(n.file, n.locator, `${basename(n.file)} ${n.locator ?? ""}`);
  d.links.forEach((l) => addSource(l.file, l.locator, `${l.kind} · ${basename(l.file)} ${l.locator ?? ""}`));
  d.facts.forEach((f) => addSource(f.file, f.locator, `${f.measure} · ${basename(f.file)} ${f.locator ?? ""}`));
  const tabs: [string, ReactNode, number?][] = [["overview", "Overview"], ["facts", "Facts", d.fact_count || undefined], ["sources", "Sources", sources.size], ["issues", "Issues", d.issues.length], ["schema", "Schema"]];
  let body: ReactNode;
  if (tab === "overview") {
    body = (
      <div>
        <Section title="Properties">
          <Kv pairs={[
            ["Type", <TypeTag type={n.type} />],
            ["ID", <span className="mono">{n.id}</span>],
            ...Object.entries(n.props).filter(([, v]) => v != null && typeof v !== "object").map(([k, v]) => [k, typeof v === "number" ? nf(v, Number.isInteger(v) ? 0 : Math.abs(v) < 10 ? 4 : 2) : String(v)] as [ReactNode, ReactNode]),
            ...(d.aliases.length ? [["Aliases", d.aliases.join(", ")] as [ReactNode, ReactNode]] : []),
          ]} />
        </Section>
        <Section title={`Relationships · ${nf(d.link_count)}`}><RelList links={d.links} /></Section>
      </div>
    );
  } else if (tab === "facts") {
    body = d.fact_count ? (
      <div>
        {n.type === "Unit" ? <UnitFacts facts={d.facts} /> : null}
        <ProductionFacts facts={d.facts} />
        {n.type !== "Unit" ? <GenericFacts facts={d.facts} total={d.fact_count} /> : null}
      </div>
    ) : <div className="section muted">No measured facts for this entity.</div>;
  } else if (tab === "sources") {
    body = (
      <Section title="Source locations">
        <div className="small muted" style={{ marginBottom: 8 }}>Every property, link and fact keeps its file and cell, page or feature. Click to open it in Inputs.</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
          {[...sources.values()].slice(0, 40).map((s) => <Cite key={`${s.file}|${s.locator}`} citation={s} />)}
        </div>
        {sources.size > 40 ? <div className="small muted" style={{ marginTop: 6 }}>{`+ ${sources.size - 40} more`}</div> : null}
      </Section>
    );
  } else if (tab === "issues") {
    body = (
      <Section title={`Issues · ${d.issues.length} (${open.length} open)`}>
        {d.issues.length ? (
          <ul className="list">
            {d.issues.map((i) => (
              <li key={i.issue_id}>
                <SevChip sev={i.status === "open" ? i.severity : "ok"}>{i.status === "open" ? i.severity : "decided"}</SevChip>
                <div style={{ flex: 1 }}><div style={{ fontWeight: 600 }}>{i.rule}</div><div className="small muted">{i.detail}</div></div>
                <button className="btn" onClick={() => { closeDrawer(); go("review", { rule: i.rule, issueId: i.issue_id }); }}>Review</button>
              </li>
            ))}
          </ul>
        ) : <div className="muted">No issues.</div>}
      </Section>
    );
  } else body = <SchemaTab name={n.type} />;
  return (
    <Shell
      tag={<TypeTag type={n.type} />}
      title={n.label}
      id={n.id}
      chips={sev ? <SevChip sev={sev}>{`${issueTotal(n.issues)} open issue${issueTotal(n.issues) > 1 ? "s" : ""}`}</SevChip> : <SevChip sev="ok">clean</SevChip>}
      actions={
        <>
          <button className="btn" onClick={() => focusGraph(n.id)}><Icon name="focus" />Focus graph</button>
          <button className="btn" onClick={() => { closeDrawer(); ask(`Tell me about ${n.label}`, n.id); }}><Icon name="spark" />Ask about this</button>
          {n.file ? <button className="btn" onClick={() => openSource(n.file, n.locator)}><Icon name="open" />Open source</button> : null}
        </>
      }
      tabs={tabs}
      active={tab}
      onTab={setTab}
    >
      {body}
    </Shell>
  );
}

function SchemaTab({ name }: { name: string }) {
  const { version } = useApp();
  const catalog = useFetch<Catalog>("/api/catalog", version).data;
  return catalog ? <TypeSchema catalog={catalog} name={name} /> : <Loading />;
}

function TypeDrawer({ name }: { name: string }) {
  const { go, closeDrawer, version } = useApp();
  const catalog = useFetch<Catalog>("/api/catalog", version).data;
  const def = catalog?.entity_types.find((t) => t.name === name);
  return (
    <Shell
      tag={<TypeTag type={name} />}
      title={name}
      id={def ? `${def.id_prefix}:<${def.key}>` : undefined}
      chips={catalog ? <span className="chip">{`${nf(catalog.counts.entities[name] ?? 0)} instances`}</span> : null}
      actions={<button className="btn" onClick={() => { closeDrawer(); go("schema", { catalog: { kind: "type", name } }); }}><Icon name="book" />Open in Schema</button>}
    >
      {catalog ? <TypeSchema catalog={catalog} name={name} /> : <Loading />}
    </Shell>
  );
}

function FigureDrawer({ fileId, figure }: { fileId: string; figure: string }) {
  const { version } = useApp();
  const detail = useFetch<FileDetail>(`/api/files/${fileId}`, version).data;
  const doc = detail?.document;
  const fig = doc?.figures.find((f) => f.id === figure);
  return (
    <Shell tag={<span className="chip"><Icon name="pdf" />Figure</span>} title={fig?.chart?.title || `Figure ${figure}`} id={`${basename(doc?.file)} · figure ${figure}`} chips={<SevChip sev="warning">approximate</SevChip>}>
      {doc ? <FigureDetail fileId={fileId} doc={doc} figureId={figure} /> : <Loading />}
    </Shell>
  );
}

export function Drawer() {
  const { drawer, closeDrawer } = useApp();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && closeDrawer();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [closeDrawer]);
  const content = (d: DrawerState): ReactNode => {
    if (d.kind === "entity") return <EntityDrawer id={d.id} />;
    if (d.kind === "type") return <TypeDrawer name={d.name} />;
    if (d.kind === "figure") return <FigureDrawer fileId={d.fileId} figure={d.figure} />;
    return (
      <Shell tag={<span className="chip"><Icon name="table" />Cell</span>} title={`${d.sheet}!${d.cell}`} id={d.fileId}>
        <CellDetails fileId={d.fileId} sheet={d.sheet} cell={d.cell} value={d.value} />
      </Shell>
    );
  };
  return (
    <section className={`drawer${drawer ? " open" : ""}`} role="dialog" aria-modal="false" aria-labelledby="drawer-title" aria-hidden={!drawer}>
      {drawer ? content(drawer) : null}
    </section>
  );
}
