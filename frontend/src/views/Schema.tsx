// Schema: the ontology catalog as a data dictionary (entity types, relationships, measures, rules, alias tables).
import type { ReactNode } from "react";
import { useFetch, type Catalog } from "../api";
import { useApp, type CatalogSel } from "../store";
import { Dot, ErrorBox, Icon, Kv, Loading, Section, SevChip } from "../ui";
import { nf, typeColor } from "../util";

export function TypeSchema({ catalog, name }: { catalog: Catalog; name: string }) {
  const def = catalog.entity_types.find((t) => t.name === name);
  if (!def) return <div className="section muted">Unknown type.</div>;
  const rels = catalog.relationship_types.filter((r) => r.source === name || r.target === name);
  const measures = catalog.measures.filter((m) => m.subject === name);
  return (
    <div>
      <Section title="Definition">
        <Kv pairs={[
          ["Entity type", <b>{def.name}</b>],
          ["ID pattern", <span className="mono">{`${def.id_prefix}:<${def.key}>`}</span>],
          ["Key", def.key],
          ["Standard", def.standard ?? "Custom (check against OSDU)"],
          ["Instances", nf(catalog.counts.entities[name] ?? 0)],
          ["Description", def.description],
        ]} />
      </Section>
      <Section title={`Properties · ${def.properties.length}`}>
        <table className="simple">
          <thead><tr><th>Property</th><th>Type / unit</th><th>Description</th></tr></thead>
          <tbody>
            {def.properties.map((p) => (
              <tr key={p.name}><td className="mono">{p.name}{p.required ? " *" : ""}</td><td>{p.type}{p.unit ? ` · ${p.unit}` : ""}</td><td className="small">{p.description ?? "—"}</td></tr>
            ))}
          </tbody>
        </table>
      </Section>
      {measures.length ? (
        <Section title={`Measures (facts) · ${measures.length}`}>
          <table className="simple">
            <thead><tr><th>Measure</th><th>Unit</th><th>Dimensions</th><th>Sources</th></tr></thead>
            <tbody>
              {measures.map((m) => (
                <tr key={m.name} title={m.description}><td className="mono">{m.name}</td><td>{m.unit}</td><td className="small">{m.dimensions.join(", ") || "—"}</td><td className="small mono">{m.sources.join(", ") || "—"}</td></tr>
              ))}
            </tbody>
          </table>
        </Section>
      ) : null}
      <Section title={`Relationship types · ${rels.length}`}>
        <table className="simple">
          <thead><tr><th>Link</th><th>To / from</th><th>Method</th><th className="num">Count</th></tr></thead>
          <tbody>
            {rels.map((r) => (
              <tr key={r.name} title={r.build_rule}><td className="mono">{r.name}</td><td>{r.source === name ? `→ ${r.target}` : `← ${r.source}`}</td><td>{r.method}</td><td className="num">{nf(catalog.counts.relationships[r.name] ?? 0)}</td></tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

export function Schema() {
  const { nav, patch, go, version } = useApp();
  const result = useFetch<Catalog>("/api/catalog", version);
  const origin = (o: string | undefined) => (o === "project" ? <span className="chip" style={{ height: 20, fontSize: 11 }}>project</span> : null);
  if (result.error) return <ErrorBox error={result.error} />;
  const catalog = result.data;
  if (!catalog) return <Loading label="Loading catalog" />;
  const sel = nav.catalog;
  const pick = (s: CatalogSel) => patch({ catalog: s });
  const head = (text: string) => <h3 className="muted" style={{ padding: "14px 14px 4px", margin: 0, fontSize: 11.5, textTransform: "uppercase", letterSpacing: ".06em" }}>{text}</h3>;
  const item = (s: CatalogSel, label: ReactNode, n?: number) => (
    <button key={`${s.kind}:${s.name}`} aria-current={sel.kind === s.kind && sel.name === s.name} onClick={() => pick(s)}>
      {label}
      {n != null ? <span className="n">{nf(n)}</span> : null}
    </button>
  );
  let body: ReactNode = null;
  if (sel.kind === "type") {
    body = (
      <div>
        <h2>{sel.name}</h2>
        <div className="muted" style={{ marginBottom: 12 }}>{catalog.entity_types.find((t) => t.name === sel.name)?.description}</div>
        <TypeSchema catalog={catalog} name={sel.name} />
      </div>
    );
  } else if (sel.kind === "rel") {
    const r = catalog.relationship_types.find((x) => x.name === sel.name);
    body = r ? (
      <div>
        <h2 className="mono">{r.name}</h2>
        <div className="cards">
          <div className="card"><div className="muted small">From → to</div><div className="big" style={{ fontSize: 16 }}>{`${r.source} → ${r.target}`}</div></div>
          <div className="card"><div className="muted small">Method</div><div className="big">{r.method}</div></div>
          <div className="card"><div className="muted small">Links in snapshot</div><div className="big">{nf(catalog.counts.relationships[r.name] ?? 0)}</div></div>
        </div>
        <Section title="Build rule"><div>{r.build_rule}</div>{r.description ? <div className="small muted" style={{ marginTop: 6 }}>{r.description}</div> : null}</Section>
        {(catalog.counts.relationships[r.name] ?? 0) === 0 ? <div className="note warn">No links of this type exist yet: the data needed to build them was not supplied (see the gap report).</div> : null}
      </div>
    ) : null;
  } else if (sel.kind === "measure") {
    const m = catalog.measures.find((x) => `${x.subject}.${x.name}` === sel.name);
    body = m ? (
      <div>
        <h2 className="mono">{`${m.subject}.${m.name}`}</h2>
        <Section title="Definition"><Kv pairs={[["Subject", m.subject], ["Unit", m.unit], ["Dimensions", m.dimensions.join(", ") || "—"], ["Sources", <span className="mono">{m.sources.join(", ") || "—"}</span>], ["Description", m.description]]} /></Section>
      </div>
    ) : null;
  } else if (sel.kind === "rule") {
    const r = catalog.rules.find((x) => x.code === sel.name);
    body = r ? (
      <div>
        <h2 className="mono">{r.code}</h2>
        <div className="cards">
          <div className="card"><div className="muted small">Severity</div><div className="big"><SevChip sev={r.severity} /></div></div>
          <div className="card"><div className="muted small">Issues in snapshot</div><div className="big">{nf(r.count)}</div></div>
          <div className="card"><div className="muted small">Subject</div><div className="big" style={{ fontSize: 16 }}>{r.subject}</div></div>
        </div>
        <Section title={r.title}><Kv pairs={[["Check", r.check], ["Blocks", r.blocks]]} /></Section>
        <button className="btn" onClick={() => go("decisions", { rule: r.code, issueId: null, queue: true })}><Icon name="shield" />Open in Decisions</button>
      </div>
    ) : null;
  } else {
    const table = catalog.aliases[sel.name];
    const entries = Object.entries((table?.entries ?? table?.aliases ?? {}) as Record<string, unknown>);
    body = (
      <div>
        <h2 className="mono">{sel.name}</h2>
        {table?.status ? <div className="banner"><Icon name="alert" />{`Status: ${String(table.status)}. Alias tables are reviewed like catalog changes.`}</div> : null}
        {table?.description ? <div className="muted" style={{ marginBottom: 12 }}>{String(table.description)}</div> : null}
        <table className="simple">
          <thead><tr><th>Source value</th><th>Maps to</th></tr></thead>
          <tbody>
            {entries.map(([k, v]) => <tr key={k} className={v == null ? "warn" : ""}><td className="mono">{k}</td><td className="mono">{v == null ? "— (no approved target)" : String(v)}</td></tr>)}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div className="twopane">
      <nav className="pane-list" aria-label="Catalog">
        {head(`Entity types · ${catalog.entity_types.length}`)}
        {catalog.entity_types.map((t) => item({ kind: "type", name: t.name }, <><Dot color={typeColor(t.name)} />{t.name}{origin(t.origin)}</>, catalog.counts.entities[t.name] ?? 0))}
        {head(`Relationship types · ${catalog.relationship_types.length}`)}
        {catalog.relationship_types.map((r) => item({ kind: "rel", name: r.name }, <><span className="mono small">{r.name}</span>{origin(r.origin)}</>, catalog.counts.relationships[r.name] ?? 0))}
        {head(`Measures · ${catalog.measures.length}`)}
        {catalog.measures.map((m) => item({ kind: "measure", name: `${m.subject}.${m.name}` }, <><span className="mono small">{`${m.subject}.${m.name}`}</span>{origin(m.origin)}</>))}
        {head(`Reconciliation rules · ${catalog.rules.length}`)}
        {catalog.rules.map((r) => item({ kind: "rule", name: r.code }, <><SevChip sev={r.severity}>{r.severity[0].toUpperCase()}</SevChip><span className="mono small">{r.code}</span></>, r.count))}
        {head(`Alias tables · ${Object.keys(catalog.aliases).length}`)}
        {Object.keys(catalog.aliases).map((name) => item({ kind: "alias", name }, <span className="mono small">{name}</span>))}
      </nav>
      <div className="pane-body">
        <div className="banner"><Icon name="alert" />{`Model ${catalog.catalog_version}. The base model is governed centrally (${catalog.status.split(";")[0]}); items marked "project" were added here through approved changes. Every snapshot records the model version it used.`}</div>
        {body}
        {sel.kind === "type" && (catalog.counts.entities[sel.name] ?? 0) > 0 ? (
          <div style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => patch({ modelTab: "graph", mode: "schema", schemaType: sel.name })}><Icon name="graph" />Show on schema graph</button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
